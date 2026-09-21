"""Phase dispatch — 단일 `progress` action. entity type 으로 issue/project 분기."""

from __future__ import annotations

from ..models import Action, LoopContext, WorkItem, WorkResult, entity_type_of
from .pre import pre_issue_progress, pre_project_progress, pre_initiative_progress
from .post import post_turn_guard, _classify_cli_error, rate_limit_backoff_seconds


def pre_dispatch(ctx: LoopContext, action: Action) -> WorkItem | None:
    if action.type != "progress":
        return None
    et = entity_type_of(action.entity)
    if et == "issue":
        return pre_issue_progress(ctx, action)
    if et == "project":
        return pre_project_progress(ctx, action)
    if et == "initiative":
        return pre_initiative_progress(ctx, action)
    return None


def post_dispatch(ctx: LoopContext, wr: WorkResult) -> int:
    """claude CLI 자체 에러는 카테고리별 정책으로 분기(`post_turn_guard`).

    반환값은 worker 의 다음 sleep 초다 — rate_limit 이면 reset 시각까지의 backoff,
    그 외엔 0(worker 가 POLL_INTERVAL 폴백). rate_limit 은 계정 전역 조건이라
    busy-retry(POLL_INTERVAL)가 reset 전까지 halt event 만 피드에 쌓는다.
    """
    work_ctx = wr.work_item.context
    session_type = work_ctx.get("session_type")
    entity_type = work_ctx.get("entity_type")
    claude_result = wr.claude_result

    if entity_type not in ("issue", "project", "initiative"):
        ctx.log.warning(f"[post_dispatch] 알 수 없는 entity_type={entity_type!r} session_type={session_type!r}")
        return 0

    entity = work_ctx[entity_type]
    entity_id = entity[f"{entity_type}_id"]
    log_label = session_type.replace("_", "/") if session_type else entity_type
    # initiative 는 title 대신 name.
    title = entity.get("title") or entity.get("name")
    ctx.log_usage(session_type=log_label, entity_id=entity_id, title=title, result=claude_result)

    if claude_result.get("is_error"):
        post_turn_guard(ctx, entity, entity_type, claude_result, phase="progress")
        category, error_msg = _classify_cli_error(claude_result)
        if category == "rate_limit":
            return rate_limit_backoff_seconds(error_msg)

    return 0
