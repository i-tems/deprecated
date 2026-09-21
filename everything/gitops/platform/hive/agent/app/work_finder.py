"""Work discovery helpers for the coordinator."""

from __future__ import annotations

import json

from .models import Action, LoopContext, id_field_for
from .scheduler import classify_goal_actions, classify_initiative_actions, deps_satisfied


def find_all_work(ctx: LoopContext, *, exclude_ids: set[str] | None = None, message_flag=None) -> list[Action]:
    """동시성 제어는 loop의 K8s Job active_names로 처리 — 여기서는 후보만 만든다.

    cell 내 issue/project status_index 를 한 번 만들어 scheduler 의 dependency 가드에 넘긴다.

    Project·Initiative 는 통합 5-status 컨테이너 모델 (backlog/active/waiting/done/archive):
    `active` 만 자율 self-action 픽업 (orchestrate), `backlog` 는 pre-launch 라 미픽업
    (launch 게이트), `waiting` 은 사람 대기로 parked — self-action 없이 pending 사용자
    댓글 reply 만 픽업 (active 워커가 needs_human/방향결정/완료추천에 막혀 active→waiting
    으로 parked 한 뒤, 사용자가 댓글을 남기면 재invoke 루프 대신 reply 로만 깨어남),
    `done`/`archive` 는 terminal — 자동 픽업하지 않는다 (INFRA-ISSUE-263: terminal +
    pending reply 가 landing 안 되면 매 cycle 재dispatch 돼 한 엔티티가 하루 수천 워커를
    띄우는 토큰 폭주 루프였다. terminal 은 status 가 이미 정답이라 status 전이로 못 끊어
    아예 픽업을 끊는다). terminal 엔티티에 달린 사용자 댓글은 사람이 처리하거나 새 entity
    로 잇는다. waiting 의 pending reply 만 project/initiative 루프(pending 필드)가 발급한다.

    Issue 는 그대로 8-status 워커 모델. waiting 인 issue 는 사람이 댓글을 남기면 자동 재개한다
    — 사람이 status 를 수동 전이하지 않아도 워커가 픽업해 마지막 phase 부터 이어가도록.
    error 는 자동 픽업 대상이 아니므로 사람이 status 를 명시 전이해야 한다 (retry 폭주 방지).
    """
    exclude = set(exclude_ids or ())
    all_goals = ctx.client.get_all_goals()
    standalone_issues = ctx.client.get_issues_without_project()

    # cell 단위 status_index: dependency lookup 용. cross-cell dep 은 미발견 → 통과.
    status_index: dict[str, str] = {g["project_id"]: g["status"] for g in all_goals}
    for t in standalone_issues:
        status_index[t["issue_id"]] = t["status"]
    # 자식 issue 는 parent project status 에 종속되지 않고 자기 status·hold·dep 으로만
    # pickup 결정. waiting/hold/todo/error parent 의 자식도 fetch 해야 work_queue
    # 에 진입한다 (회귀: parent waiting 으로 자식 todo issue 가 invisible 한 게이트
    # 제거).
    issues_by_project: dict[str, list[dict]] = {}
    for project in all_goals:
        if project["status"] not in ("done", "archive"):
            issues_by_project[project["project_id"]] = ctx.client.get_tasks(project["project_id"])
            for t in issues_by_project[project["project_id"]]:
                status_index[t["issue_id"]] = t["status"]

    # hold=True 인 entity 는 status 와 무관하게 자동 픽업에서 제외한다 (개인 세션
    # 수동 작업 보호). hold 는 **그 entity 자신만** 멈춘다 — project→자식 issue cascade
    # 는 없다. held project 의 project_id 를 exclude 에 넣어 project 자신의 progress·pickup·
    # cleanup 만 차단하고, 자식 issue 처리 경로 (parent status 무관) 는 그대로 살린다.
    # 자식 issue 는 각자 issue.hold 로만 판단된다 (project 을 hold 해도 자식은 안 멈춘다 —
    # 자식까지 막으려면 각 issue 에 개별 hold). project_id·issue_id 는 절대 충돌 안 하므로
    # 두 집합을 한 exclude 로 합쳐도 안전.
    held_issue_ids = {t["issue_id"] for t in standalone_issues if t.get("hold")}
    for _gissues in issues_by_project.values():
        held_issue_ids |= {t["issue_id"] for t in _gissues if t.get("hold")}
    held_project_ids = {g["project_id"] for g in all_goals if g.get("hold")}
    exclude |= held_issue_ids | held_project_ids

    work_queue: list[Action] = []
    # waiting/error pickup 후보: 사람이 댓글 남겼는지 확인하고 phase 결정.
    # 한 번에 모아 처리 — get_events 호출이 N+1 이 되므로 후보 추리고 나서만 호출.
    pickup_candidates: list[tuple[dict, str]] = []

    for project in all_goals:
        status = project["status"]
        if status in ("done", "archive"):
            continue
        project_id = project["project_id"]
        issues = issues_by_project.get(project_id, [])

        # 자식 issue action 발급은 parent project status (컨테이너) 와 무관 — 자식 issue 는
        # 자기 8-status 워커 모델대로 진행. project-self 완료 판단(§B)·decompose(§A) 는
        # `active` 일 때만 classify 가 발급한다. `backlog` 는 pre-launch (launch 게이트):
        # project-self action 은 안 나가고, 만약 자식 issue 가 있다면 그 자식은 자기
        # status 로 그대로 픽업된다 (정상 backlog 엔 자식이 없지만, 가시성 유지를 위해
        # 자식 fetch·픽업은 parent 와 직교하게 둔다). `waiting` 도 classify 는 self-action
        # 을 안 낸다 (active 한정) — 아래 pending reply 분기로만 픽업.
        work_queue.extend(classify_goal_actions(project, issues, exclude, status_index=status_index))

        # waiting Project 의 pending 사용자 댓글 reply 픽업 (self-action 은 없음).
        # active 워커가 사람에 막혀 active→waiting 으로 parked 한 뒤, 사용자가 댓글을
        # 남기면 reply 위해 다시 픽업한다 — initiative 의 pending 분기와 대칭. terminal
        # (done/archive) 은 자동 픽업 대상이 아니다 (INFRA-ISSUE-263).
        if (
            status == "waiting"
            and project_id not in exclude  # held project 제외 (hold=수동 steering 보호)
            and project.get("pending_user_comment_event_ids")
        ):
            work_queue.append(Action(
                "progress", entity=project,
                priority=_PICKUP_PRIORITY.get("project", 5),
            ))

        # 자식 issue 의 waiting pickup 후보 (parent status 무관)
        for t in issues:
            if t["status"] in _PICKUP_STATES and t["issue_id"] not in exclude:
                pickup_candidates.append((t, "issue"))

    # project_id 없는 Issue
    for issue in standalone_issues:
        if issue["issue_id"] in exclude:
            continue
        if issue["status"] == "cleanup":
            work_queue.append(Action("progress", entity=issue, priority=0))
        elif issue["status"] in ("todo", "running") and deps_satisfied(issue, status_index):
            work_queue.append(Action("progress", entity=issue, priority=1))
        elif issue["status"] in _PICKUP_STATES:
            pickup_candidates.append((issue, "issue"))

    # Initiative (active leaf 한정) — decompose(§A) vs decide(§B) 분기를 status 가 아니라
    # 자식 Project 존재 여부로 대신한다. 자식 Project 자체는 위 project 루프가 이미 처리하므로 여기선
    # initiative self-action (§A 자식 생성 / §B 완료 판단) 과 pending 댓글 reply 만.
    # hold 는 그 entity 자신만 멈춘다 — 자식 Project 엔 cascade 없음 (project 와 대칭).
    #
    # frame(상위) initiative 제외: 자식이 sub-initiative 인 frame 은 직속 Project 가
    # 없어 §A 로 잘못 진입(직속 Project 생성)한다. 그 "work" 는 sub-initiative tree 라
    # 영구 frame 으로 보고 사람/CEO(directing-cells)가 관리한다 (initiative_model §6).
    # active sub-initiative 만이 아니라 *어떤 status 의 자식이라도* 있으면 frame 으로
    # 판정 — leaf(자식 없음)만 자율 오케스트레이션. all-initiatives 1회 조회로 parentage
    # 집합을 만들어 N+1 회피.
    all_initiatives = ctx.client.get_all_initiatives()
    _frame_ids = {
        i["parent_initiative_id"] for i in all_initiatives
        if i.get("parent_initiative_id")
    }
    for initiative in all_initiatives:
        status = initiative.get("status")
        # active = self-action(§A/§B) + pending reply. waiting = 사람 대기로 parked —
        # self-action 은 없고 pending 사용자 댓글 reply 만 (active→waiting 으로 재invoke
        # 루프 차단 후, 사용자 댓글이 오면 깨워 reply). 그 외(backlog/done/archive)는 skip.
        if status not in ("active", "waiting"):
            continue
        iid = initiative["initiative_id"]
        if initiative.get("hold") or iid in exclude or iid in _frame_ids:
            continue
        projects = ctx.client.get_initiative_projects(iid)
        self_actions = classify_initiative_actions(initiative, projects) if status == "active" else []
        if self_actions:
            work_queue.extend(self_actions)
        elif initiative.get("pending_user_comment_event_ids"):
            # active: 자식 Project 활동 중이라 self-action 은 없지만 미응답 사용자 댓글엔
            #   §C-0 reply. waiting: parked 됐지만 새 사용자 댓글이 오면 reply 위해 픽업.
            # pending 필드는 hub 가 event.add 시점에 갱신하므로 get_events N+1 을 피한다.
            work_queue.append(Action("progress", entity=initiative, priority=_INITIATIVE_PICKUP_PRIORITY))

    for entity, entity_type in pickup_candidates:
        action = _build_pickup_action(entity, entity_type, ctx)
        if action is not None:
            work_queue.append(action)

    return work_queue


# 자식 ISSUE 전용 댓글 pickup 상태 (8-status 워커 모델). Project·Initiative 컨테이너는
# 이 집합으로 self-pick 하지 않는다 — 컨테이너엔 waiting/cleanup/error 가 없고 `active`
# 일 때만 classify 가 self-action 을 발급한다. error 는 issue 라도 자동 픽업 대상이 아니다
# — 시스템 실패 신호이므로 사람이 직접 상태를 정리하고 명시적으로 재시작해야 한다
# (자동 retry 폭주를 막기 위해 정책상 waiting 만 허용).
_PICKUP_STATES = ("waiting",)

# pickup 우선순위 — issue 가 project 보다 먼저 (일반 정상 흐름과 같은 priority).
_PICKUP_PRIORITY = {"issue": 1, "project": 2}

# initiative 는 전략 tier — issue/project 뒤. scheduler._INITIATIVE_PRIORITY 와 동일.
_INITIATIVE_PICKUP_PRIORITY = 3


def _build_pickup_action(entity: dict, entity_type: str, ctx: LoopContext) -> Action | None:
    """waiting entity 에 미응답 사용자 댓글이 있을 때만 progress Action 생성.

    phase 분기는 prompt spec 안에서 LLM 이 결정 (description / 자식 entity 상태 / status 로) —
    여기서는 단일 `progress` action 만 발급한다.
    """
    entity_id = entity[id_field_for(entity_type)]
    events = ctx.client.get_events(entity_id, entity_type, kinds=_DELTA_EVENT_KINDS)
    pending = _find_pending_user_comments(events)
    if not pending:
        return None

    return Action("progress", entity=entity, priority=_PICKUP_PRIORITY.get(entity_type, 5))


# ---------------------------------------------------------------------------
# Loop 컨텍스트 — 풀/델타 섹션 빌더
# 핸드오프 정본:
#   cells/personal-default/knowledge/handoff/2026-04-28_loop-context-table.md
#   cells/personal-default/knowledge/handoff/2026-04-28_loop-context-delta-injection.md
# ---------------------------------------------------------------------------

_CAP_SIBLINGS = 30
_CAP_EVENTS = 20
_CAP_SIGNALS = 20

# Activity feed에서 AI 프롬프트로 전달할 이벤트 종류.
# comment(사람·AI) + status_change가 사람-AI 협업의 핵심 신호.
_DELTA_EVENT_KINDS = ["status_change", "comment"]


def _slim_sibling_issue(t: dict) -> dict:
    return {k: t.get(k) for k in ("issue_id", "title", "status", "intent", "description")}


def _signal_created_at(s: dict) -> str:
    """기존 데이터(`ts_emitted`)와 신규 필드(`created_at`) 모두 호환."""
    return s.get("created_at") or s.get("ts_emitted") or ""


def _slim_signal(s: dict) -> dict:
    detail = s.get("detail") or {}
    return {
        "signal_id": s.get("signal_id"),
        "type": s.get("type"),
        "impact": s.get("impact"),
        "severity": s.get("severity"),
        "message": detail.get("message"),
        "created_at": _signal_created_at(s) or None,
    }


def _slim_event(item: dict) -> dict:
    """event.list feed item을 slim 형태로 변환."""
    data = item.get("data") or {}
    out: dict = {
        "ts": item.get("ts"),
        "kind": item.get("kind"),
        "principal_type": item.get("principal_type"),
    }
    if item.get("kind") == "comment":
        out["text"] = data.get("text")
        out["event_id"] = item.get("event_id")
        if data.get("parent_event_id"):
            out["parent_event_id"] = data["parent_event_id"]
    elif item.get("kind") == "status_change":
        out["from"] = data.get("from") or data.get("from_status")
        out["to"] = data.get("to") or data.get("to_status")
    return out


def _json_block(title: str, payload) -> str:
    return f"\n## {title}\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _delta_block(title: str, payload) -> str:
    return f"### {title}\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _find_pending_user_comments(events: list[dict]) -> list[dict]:
    """User comment 중 AI/worker reply 가 매칭되지 않은 chain head 들을 시간순으로 반환.

    - 사용자 자기-reply(`principal_type=="user"`)는 부모를 replied 로 마킹하지 않는다 — 부모는
      여전히 사람이 응답 받기를 기다리는 상태이기 때문(ITEMS-ISSUE-15 회귀).
    - 한 chain 안에 여러 user comment 가 pending 이면 가장 위(가장 오래된) 코멘트만
      head 로 반환하고, 후손 pending 들은 `_pending_chains` 가 `replies` 배열로 묶어
      같이 노출한다. head dedup 으로 동일 chain 이 항목 두 번 나오는 것을 막는다.
    """
    user_comments = [
        e for e in events
        if e.get("kind") == "comment" and e.get("principal_type") == "user"
    ]
    replied_to: set[str] = set()
    for e in events:
        if e.get("kind") != "comment":
            continue
        if e.get("principal_type") == "user":
            continue
        pid = (e.get("data") or {}).get("parent_event_id")
        if pid:
            replied_to.add(pid)
    pending_ids = {
        c.get("event_id") for c in user_comments
        if c.get("event_id") and c.get("event_id") not in replied_to
    }
    by_event = {
        e.get("event_id"): e for e in events
        if e.get("kind") == "comment" and e.get("event_id")
    }

    def _has_pending_ancestor(c: dict) -> bool:
        pid = (c.get("data") or {}).get("parent_event_id")
        while pid:
            if pid in pending_ids:
                return True
            parent = by_event.get(pid)
            if not parent:
                break
            pid = (parent.get("data") or {}).get("parent_event_id")
        return False

    heads = [
        c for c in user_comments
        if c.get("event_id") in pending_ids and not _has_pending_ancestor(c)
    ]
    heads.sort(key=lambda c: c.get("ts") or "")
    return heads


def _pending_chains(heads: list[dict], events: list[dict]) -> list[dict]:
    """각 head 의 자손 comment 들을 시간순으로 묶어 `[{head, replies}, ...]` 반환."""
    children_of: dict[str, list[dict]] = {}
    for e in events:
        if e.get("kind") != "comment":
            continue
        pid = (e.get("data") or {}).get("parent_event_id")
        if pid:
            children_of.setdefault(pid, []).append(e)

    def _descendants(root_id: str) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        queue = list(children_of.get(root_id, []))
        while queue:
            e = queue.pop(0)
            eid = e.get("event_id")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            out.append(e)
            queue.extend(children_of.get(eid, []))
        out.sort(key=lambda e: e.get("ts") or "")
        return out

    return [
        {"head": h, "replies": _descendants(h.get("event_id") or "")}
        for h in heads
    ]


def _slim_pending(item: dict) -> dict:
    data = item.get("data") or {}
    return {
        "event_id": item.get("event_id"),
        "ts": item.get("ts"),
        "principal_id": item.get("principal_id"),
        "principal_type": item.get("principal_type"),
        "text": data.get("text"),
    }


def _pending_block(pending: list[dict], events: list[dict]) -> str:
    # 헤더 라벨은 spec(issue_progress.md §C-0 / 활동 테이블)이 이름으로 참조하는 앵커라 유지.
    chains = _pending_chains(pending, events)
    payload = [
        {**_slim_pending(c["head"]), "replies": [_slim_pending(r) for r in c["replies"]]}
        for c in chains
    ]
    return (
        "\n## Pending User Comments — REPLY REQUIRED\n"
        "아래는 AI/worker reply 가 직접 매칭되지 않은 사용자 comment chain 입니다. "
        "각 chain 의 head(루트)와 replies 안의 모든 `actor:\"human\"` 코멘트마다 "
        "`event.add(parent_event_id=<event_id>, text=...)` 로 답해야 합니다. "
        "replies 안의 AI/worker 코멘트는 이미 응답이 끝난 항목이라 다시 답하지 마세요.\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def format_full_context_section(*, issue: dict, project: dict, ctx: LoopContext) -> str:
    """풀 컨텍스트 섹션 마크다운.

    activity feed(사람·AI comment + status_change)를 프롬프트에 주입한다. 새 comment 는 reply
    대상이 될 수 있도록 event_id 를 포함한다. pending user comment 의 reply 강제는 hub 가
    pre-check 로 처리하므로 별도 event_id 반환은 필요 없다.
    """
    issue_id = issue["issue_id"]
    project_id = project.get("project_id") if project else None
    parts: list[str] = []

    if project_id:
        siblings = ctx.client.get_sibling_tasks(project_id, issue_id)[:_CAP_SIBLINGS]
        if siblings:
            parts.append(_json_block("Sibling Issues", [_slim_sibling_issue(t) for t in siblings]))

    signals = [_slim_signal(s) for s in ctx.client.get_signals(issue_id)[:_CAP_SIGNALS]]
    if signals:
        parts.append(_json_block("Self Signals", signals))

    all_events = ctx.client.get_events(issue_id, "issue", kinds=_DELTA_EVENT_KINDS)
    pending = _find_pending_user_comments(all_events)
    if pending:
        parts.append(_pending_block(pending, all_events))

    events = all_events[-_CAP_EVENTS:]
    if events:
        parts.append(_json_block("Activity Events", [_slim_event(e) for e in events]))

    return "\n".join(parts)


def format_delta_section(*, issue: dict, project: dict, since: str, ctx: LoopContext) -> str:
    """직전 사이클 이후 변경된 항목만 추려 마크다운으로 반환.

    Loop runner의 last_prompt_at 커서를 since로 받아, 그 이후 등장한 event/signal만 첨부.
    Pending user comment는 since 이전이라도 항상 별도 블록으로 노출한다.
    """
    issue_id = issue["issue_id"]
    parts: list[str] = []

    all_events = ctx.client.get_events(issue_id, "issue", kinds=_DELTA_EVENT_KINDS)
    pending = _find_pending_user_comments(all_events)
    pending_section = _pending_block(pending, all_events) if pending else ""

    new_events = [_slim_event(e) for e in all_events if (e.get("ts") or "") >= since][-_CAP_EVENTS:]
    if new_events:
        parts.append(_delta_block("새 Activity", new_events))

    new_signals_raw = ctx.client.get_signals(issue_id)
    new_signals = [
        _slim_signal(s) for s in new_signals_raw
        if _signal_created_at(s) >= since
    ][:_CAP_SIGNALS]
    if new_signals:
        parts.append(_delta_block("새 Signal", new_signals))

    header = f"\n\n## 이전 사이클 이후 변경 (since {since})\n"
    # delta 0건은 사실 노트만 — "계속 진행" 류 행동 지시는 spec/skill 이 담당.
    body = "\n\n".join(parts) if parts else "변경 없음."
    return pending_section + header + body + "\n"


def _slim_child(entity: dict, id_key: str) -> dict:
    """자식 status roster 용 — description 등 정적 대형 필드 제외, 휘발 필드만."""
    return {id_key: entity.get(id_key), "title": entity.get("title"), "status": entity.get("status")}


def format_goal_full_context_section(*, project: dict, ctx: LoopContext) -> str:
    """Project 첫 turn 풀 컨텍스트: pending user comment + activity feed.

    Issue 의 format_full_context_section 과 대칭. Project 은 self-signal / sibling 이
    없으므로 comment·status_change activity 와 pending 만 주입한다.
    """
    project_id = project["project_id"]
    parts: list[str] = []

    all_events = ctx.client.get_events(project_id, "project", kinds=_DELTA_EVENT_KINDS)
    pending = _find_pending_user_comments(all_events)
    if pending:
        parts.append(_pending_block(pending, all_events))

    events = all_events[-_CAP_EVENTS:]
    if events:
        parts.append(_json_block("Activity Events", [_slim_event(e) for e in events]))

    return "\n".join(parts)


def format_goal_delta_section(
    *, project: dict, issues: list[dict], since: str, ctx: LoopContext
) -> str:
    """Project resume 컨텍스트. 정적 재덤프(project slim·자식 description) 제거.

    Issue delta 와 구조는 같지만 분리 기준이 다르다 — Project worker 의 핵심 입력인
    자식 issue status 는 매 turn 휘발하므로, description 을 뺀 compact
    roster 를 since 와 무관하게 항상 첨부한다. comment/status_change 는 since 이후
    delta 만, pending user comment 는 since 이전이라도 항상 별도 블록.

    자식 issue 의 status_change 도 since 이후만 별도 블록으로 합친다 — 부모
    project 의 event feed 에는 자식 transition 이 들어가지 않으므로 (`emit_event` 가
    entity_id 단일 키로 저장; cascade 는 wake 알림만), 자식 roster status 가
    conversation memory 와 다를 때 그 변화의 원인이 prompt 에 안 보이면 claude 가
    옛 인상으로 잘못 판단할 수 있다 (예: cleanup→done 전이를 놓치고 idle 코멘트로
    종료 → no_progress 가드에 잡혀 강제 error).
    """
    project_id = project["project_id"]
    parts: list[str] = []

    all_events = ctx.client.get_events(project_id, "project", kinds=_DELTA_EVENT_KINDS)
    pending = _find_pending_user_comments(all_events)
    pending_section = _pending_block(pending, all_events) if pending else ""

    roster = {"issues": [_slim_child(t, "issue_id") for t in issues]}
    parts.append(_delta_block("자식 상태 roster", roster))

    new_events = [_slim_event(e) for e in all_events if (e.get("ts") or "") >= since][-_CAP_EVENTS:]
    if new_events:
        parts.append(_delta_block("새 Activity", new_events))

    child_events: list[dict] = []
    for t in issues:
        tid = t.get("issue_id")
        if not tid:
            continue
        for e in ctx.client.get_events(tid, "issue", kinds=["status_change"]):
            if (e.get("ts") or "") < since:
                continue
            slim = _slim_event(e)
            slim["child_id"] = tid
            slim["child_title"] = t.get("title")
            child_events.append(slim)
    if child_events:
        child_events.sort(key=lambda e: e.get("ts") or "")
        parts.append(_delta_block("자식 status_change (since)", child_events[-_CAP_EVENTS:]))

    header = f"\n\n## 이전 사이클 이후 변경 (since {since})\n"
    body = "\n\n".join(parts)
    return pending_section + header + body + "\n"


def format_initiative_full_context_section(*, initiative: dict, ctx: LoopContext) -> str:
    """Initiative 첫 turn 풀 컨텍스트: pending user comment + activity feed.

    format_goal_full_context_section 과 대칭 (한 tier 위). self-signal/sibling 없음.
    """
    initiative_id = initiative["initiative_id"]
    parts: list[str] = []

    all_events = ctx.client.get_events(initiative_id, "initiative", kinds=_DELTA_EVENT_KINDS)
    pending = _find_pending_user_comments(all_events)
    if pending:
        parts.append(_pending_block(pending, all_events))

    events = all_events[-_CAP_EVENTS:]
    if events:
        parts.append(_json_block("Activity Events", [_slim_event(e) for e in events]))

    return "\n".join(parts)


def format_initiative_delta_section(
    *, initiative: dict, projects: list[dict], since: str, ctx: LoopContext
) -> str:
    """Initiative resume 컨텍스트. format_goal_delta_section 의 한 tier 위 (자식=Project).

    자식 Project status roster 는 매 turn 휘발하므로 since 무관하게 항상 첨부.
    comment/status_change 는 since 이후 delta, pending user comment 는 항상 별도 블록.
    자식 Project 의 status_change(특히 done — child→initiative cascade wake 의 원인)도
    since 이후만 별도 블록으로 합친다 (부모 initiative event feed 엔 자식 transition 이
    안 들어가므로, roster 변화의 원인을 prompt 에 보여 §B 오판 방지).
    """
    initiative_id = initiative["initiative_id"]
    parts: list[str] = []

    all_events = ctx.client.get_events(initiative_id, "initiative", kinds=_DELTA_EVENT_KINDS)
    pending = _find_pending_user_comments(all_events)
    pending_section = _pending_block(pending, all_events) if pending else ""

    roster = {"projects": [_slim_child(p, "project_id") for p in projects]}
    parts.append(_delta_block("자식 Project roster", roster))

    new_events = [_slim_event(e) for e in all_events if (e.get("ts") or "") >= since][-_CAP_EVENTS:]
    if new_events:
        parts.append(_delta_block("새 Activity", new_events))

    child_events: list[dict] = []
    for p in projects:
        pid = p.get("project_id")
        if not pid:
            continue
        for e in ctx.client.get_events(pid, "project", kinds=["status_change"]):
            if (e.get("ts") or "") < since:
                continue
            slim = _slim_event(e)
            slim["child_id"] = pid
            slim["child_title"] = p.get("title")
            child_events.append(slim)
    if child_events:
        child_events.sort(key=lambda e: e.get("ts") or "")
        parts.append(_delta_block("자식 Project status_change (since)", child_events[-_CAP_EVENTS:]))

    header = f"\n\n## 이전 사이클 이후 변경 (since {since})\n"
    body = "\n\n".join(parts)
    return pending_section + header + body + "\n"
