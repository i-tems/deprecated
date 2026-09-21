"""작업 준비: entity 조회 → 프롬프트 빌드 → WorkItem 생성.

단일 `progress` action 만 사용한다 (entity type 으로 issue/project 분기).
plan 작성·실행·cleanup·완료 판단의 phase 분리는 prompt spec 안에서 LLM 이 결정한다.
"""

from __future__ import annotations

from ..models import Action, LoopContext, WorkItem, id_field_for
from ..work_finder import (
    format_delta_section,
    format_full_context_section,
    format_goal_delta_section,
    format_goal_full_context_section,
    format_initiative_delta_section,
    format_initiative_full_context_section,
)


# Issue worker 진입 가능 status (8-status 모델) = work_finder 가 실제 enqueue 하는 status.
# waiting 은 pending user comment 가 있을 때만 픽업 후보로 올린다. terminal(done/cancelled)
# 은 INFRA-ISSUE-263 이후 미픽업이라 제외 — fetch 후 fresh status 가 terminal 이면 race
# (enqueue 후 사람이 종결)이므로 TOCTOU 가드가 skip 한다. error 도 미픽업이라 제외.
_VALID_STATUSES = {"todo", "running", "waiting", "cleanup"}
# 컨테이너(Project/Initiative) 진입 가능 status (통합 5-status). active=self-action 워커,
# waiting=사람 대기 parked 의 pending 댓글 reply 진입. terminal(done/archive)·backlog 는
# 미픽업이라 제외 (위 issue 와 동일 — fresh 가 terminal 이면 race, 가드가 skip).
_VALID_STATUSES_CONTAINER = {"active", "waiting"}


def _fetch_goal_or_empty(ctx: LoopContext, project_id: str | None, **api_kwargs) -> dict:
    """Project 조회. 실패하거나 project_id가 없으면 빈 dict 대신 project_id만 보존한 dict를 반환."""
    if not project_id:
        return {}
    resp = ctx.client.api_safe("project.get", {"project_id": project_id}, **api_kwargs, label="Project 조회 실패")
    project = (resp or {}).get("data", {})
    if not project:
        ctx.log.warning(f"Project 조회 실패 — project_id={project_id} 유지하여 진행")
        return {"project_id": project_id}
    return project


def _fetch_and_guard(ctx: LoopContext, entity_type: str, entity_id: str, valid_statuses: set[str], **api_kwargs) -> dict | None:
    """Entity 조회 + TOCTOU 가드. 통과 시 entity dict, 실패 시 None."""
    idf = id_field_for(entity_type)
    resp = ctx.client.api_safe(f"{entity_type}.get", {idf: entity_id}, **api_kwargs, label=f"{entity_type.title()} 조회 실패")
    if not resp:
        return None
    entity = resp.get("data", {})
    if entity.get("status") not in valid_statuses:
        ctx.log.warning(f"TOCTOU: {entity_type} {entity_id} -> {entity.get('status')}, skip")
        return None
    return entity


def pre_issue_progress(ctx: LoopContext, action: Action) -> WorkItem | None:
    """Issue 단일 phase 진입. todo/running/waiting(pickup)/cleanup 모두 처리."""
    issue_id = action.entity["issue_id"]
    project_id = action.entity.get("project_id")
    issue = _fetch_and_guard(ctx, "issue", issue_id, _VALID_STATUSES, issue_id=issue_id)
    if not issue:
        return None

    project = _fetch_goal_or_empty(ctx, project_id, issue_id=issue_id)
    session = ctx.session_store.get_or_create(issue_id)
    tier = issue.get("model") or ctx.exec_tier_default
    model = ctx.resolve_model(tier)

    # plan 미작성 시점에는 model 이 비어있을 수 있다. PromptFactory 가 spec 만 주입하고
    # LLM 이 description / status 를 보고 단계 분기를 판단하므로 별도의 phase 분기 없이 단일 빌더.
    # is_first 면 PromptFactory 가 header + entity slim + spec refs 를 통째로 주입.
    # 이후 cycle (resume) 은 SDK conversation 이 이전 history 를 갖고 있으므로 동일 블록
    # 재주입은 토큰 낭비. delta section 만 새 user turn 으로 넘긴다.
    is_first = session.session_id is None or not session.last_prompt_at
    if is_first:
        prompt = ctx.prompt_factory.build_issue_progress(issue, project)
        prompt += format_full_context_section(issue=issue, project=project, ctx=ctx)
        ctx.log.info(f"[pre/progress/issue] {issue['title']} status={issue['status']} (model={model}) — full context")
    else:
        since = session.last_prompt_at
        prompt = format_delta_section(issue=issue, project=project, since=since, ctx=ctx)
        ctx.log.info(f"[pre/progress/issue] {issue['title']} status={issue['status']} (model={model}) — delta only since {since}")

    return WorkItem(
        action=action, prompt=prompt, session=session, model=model,
        context={"session_type": "issue_progress", "entity_type": "issue", "project": project, "issue": issue},
    )


def pre_project_progress(ctx: LoopContext, action: Action) -> WorkItem | None:
    """Project 단일 phase 진입. 자식 entity 컨텍스트를 자동 주입해 LLM 이 분기 판단."""
    project_id = action.entity["project_id"]
    project = _fetch_and_guard(ctx, "project", project_id, _VALID_STATUSES_CONTAINER)
    if not project:
        return None

    all_tasks = ctx.client.get_tasks(project_id) or []
    session = ctx.session_store.get_or_create(project_id)

    # Issue 와 대칭: is_first 면 풀(project slim + 자식 JSON + activity), resume 면
    # SDK conversation history 가 정적 부분을 들고 있으므로 동일 블록 재주입은
    # 토큰 낭비 — delta 만 넘긴다. 단 자식 status roster 는 매 turn 휘발하므로
    # delta 섹션이 description 뺀 compact roster 로 항상 갱신한다.
    is_first = session.session_id is None or not session.last_prompt_at
    if is_first:
        prompt = ctx.prompt_factory.build_project_progress(project, issues=all_tasks)
        prompt += format_goal_full_context_section(project=project, ctx=ctx)
        ctx.log.info(f"[pre/progress/project] {project['title']} status={project['status']} (issues={len(all_tasks)}) — full context")
    else:
        since = session.last_prompt_at
        prompt = format_goal_delta_section(project=project, issues=all_tasks, since=since, ctx=ctx)
        ctx.log.info(f"[pre/progress/project] {project['title']} status={project['status']} (issues={len(all_tasks)}) — delta only since {since}")

    model = ctx.resolve_model("high")
    return WorkItem(
        action=action, prompt=prompt, session=session, model=model,
        context={"session_type": "project_progress", "entity_type": "project", "project": project},
    )


def pre_initiative_progress(ctx: LoopContext, action: Action) -> WorkItem | None:
    """Initiative 단일 phase 진입 (active 한정). 자식 Project 컨텍스트를 주입해
    LLM 이 §A(자식 생성)/§B(완료 판단)/reply 를 자식 수·status 로 분기 판단."""
    initiative_id = action.entity["initiative_id"]
    initiative = _fetch_and_guard(ctx, "initiative", initiative_id, _VALID_STATUSES_CONTAINER)
    if not initiative:
        return None

    projects = ctx.client.get_initiative_projects(initiative_id) or []
    session = ctx.session_store.get_or_create(initiative_id)
    name = initiative.get("name") or initiative_id

    # Project 와 대칭: is_first 면 풀(initiative slim + 자식 Project JSON + activity),
    # resume 면 SDK conversation 이 정적 부분을 들고 있으므로 delta 만. 자식 Project
    # roster 는 매 turn 휘발하므로 delta 섹션이 항상 갱신한다.
    is_first = session.session_id is None or not session.last_prompt_at
    if is_first:
        prompt = ctx.prompt_factory.build_initiative_progress(initiative, projects=projects)
        prompt += format_initiative_full_context_section(initiative=initiative, ctx=ctx)
        ctx.log.info(f"[pre/progress/initiative] {name} status={initiative['status']} (projects={len(projects)}) — full context")
    else:
        since = session.last_prompt_at
        prompt = format_initiative_delta_section(initiative=initiative, projects=projects, since=since, ctx=ctx)
        ctx.log.info(f"[pre/progress/initiative] {name} status={initiative['status']} (projects={len(projects)}) — delta only since {since}")

    model = ctx.resolve_model("high")
    return WorkItem(
        action=action, prompt=prompt, session=session, model=model,
        context={"session_type": "initiative_progress", "entity_type": "initiative", "initiative": initiative},
    )
