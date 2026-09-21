"""세션 종료 후 entity 처리.

LLM 이 세션 중 MCP capability 를 직접 호출해 status·description·reply 를 처리한다.
post-handler 는 claude CLI 자체 에러(timeout / max_turns / runtime / input_too_long /
api_error) 와 비에러 cycle 의 silent deadlock(running/cleanup 에서 전이 없이 종료)
두 경로를 한 입구(`post_turn_guard`)로 모은다. AI 가 status 미전이·자식 미생성 같은
spec 위반을 해도 시스템은 status 를 임의로 뒤집지 않으며, 카테고리·현재 status 에
따라 force_error / halt_event(passive: status 유지) / handoff(사람 인계) 로 분기한다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..config import POLL_INTERVAL
from ..models import LoopContext, id_field_for

# rate_limit busy-retry 방지용 backoff bound. rate_limit 은 계정 전역 조건이라
# reset 전 재시도는 같은 한도에 막혀 halt event 만 피드에 쌓는다 — reset 시각까지
# 한 번에 sleep 한다. 파싱 실패 시 _RATE_LIMIT_FALLBACK_BACKOFF_S, 상한은 오파싱
# (타임존 등)으로 워커가 과도하게 잠드는 것을 막는 안전 캡.
_RATE_LIMIT_FALLBACK_BACKOFF_S = 600
_RATE_LIMIT_MAX_BACKOFF_S = 3600
# "resets 3:40pm (UTC)" / "resets 11pm" 형태. 분은 선택. 시각은 UTC 가정(메시지가
# 항상 (UTC) 표기) — 다른 타임존이면 캡이 손해를 bound 한다.
_RESET_RE = re.compile(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)", re.IGNORECASE)


def rate_limit_backoff_seconds(error_msg: str, *, now: datetime | None = None) -> int:
    """rate_limit 메시지의 'resets H[:MM]am/pm' → 지금부터 reset 까지 초.

    파싱 실패 시 fallback. [POLL_INTERVAL, _RATE_LIMIT_MAX_BACKOFF_S] 로 bound.
    busy-retry(POLL_INTERVAL=30s) 대신 quota 회복 시점까지 한 번에 backoff 하기 위함.
    """
    now = now or datetime.now(timezone.utc)
    m = _RESET_RE.search(error_msg or "")
    if not m:
        return _RATE_LIMIT_FALLBACK_BACKOFF_S
    hour = int(m.group(1)) % 12
    if m.group(3).lower() == "pm":
        hour += 12
    minute = int(m.group(2) or 0)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:  # 이미 지난 시각이면 다음 날 같은 시각.
        target += timedelta(days=1)
    secs = int((target - now).total_seconds())
    return max(POLL_INTERVAL, min(secs, _RATE_LIMIT_MAX_BACKOFF_S))


# claude CLI subtype → 본 모듈의 카테고리.
_CLAUDE_SUBTYPE_CATEGORY = {
    "error_max_turns": "max_turns",
    "error_during_execution": "runtime_error",
    "error_input_too_long": "input_too_long",
}

# Issue 전용 passive 집합 (컨테이너는 아래 entity_type 분기에서 early-return 되므로
# 이 집합에 안 닿는다). pre_dispatch 가 잡아 온 issue snapshot 이 cycle 동안 stale
# 되는 케이스(LLM 이 세션 안에서 status 를 waiting/done/cancelled 로 이미 전이) 를
# 대비해 force_update 직전 fresh status 와 비교한다. cleanup 도 passive 에 포함 —
# 능동 status 데드락 가드는 별도(`no_progress` 카테고리)가 담당하므로 cleanup 보호와 무관.
_PASSIVE_STATES = ("waiting", "cleanup", "done", "cancelled")

# 카테고리별 active(running/None) 정책. passive 는 모든 카테고리 공통 = halt event.
#   force_error : status=error 강제 전이 + halt event + session reset.
#                 silent deadlock 가드 + 분류 불가 안전측.
#   handoff     : status=waiting + handoff comment + session reset.
#                 사람만 풀 수 있는 카테고리 — input_too_long.
#
# 정책: 실패는 재시도(=soft_event, status 유지 → agent-loop 재픽업)하지 않고 곧장
# error 로 보낸다. soft_event 유지 시 전이가 안 일어나 work_finder 가 매 cycle
# 재발행 → 한 엔티티가 하루 수천 trace 의 토큰 폭주 루프(INFRA-ISSUE-122 1232·
# INFRA-TASK-129 3100). error 는 사람이 todo 로 재시도(HandoffCallout) — 자동 재시도
# 루프 제거. (트레이드오프: rate_limit 은 계정 전역 조건이라 그 윈도우에 active
# 워커가 동시 error 날 수 있다 — 단, 무한 재발행보다 복구 비용 낮음.)
_CATEGORY_POLICY = {
    "max_turns": "force_error",
    "runtime_error": "force_error",
    "timeout": "force_error",
    "input_too_long": "handoff",
    "api_error": "force_error",
    "rate_limit": "force_error",
    "uncategorized": "force_error",
    "no_progress": "force_error",
}


def _classify_cli_error(result: dict) -> tuple[str, str]:
    """claude_result → (category, error_msg). subtype 우선, raw text 보조."""
    subtype = (result.get("subtype") or "").strip()
    error_msg = str(result.get("result") or "").strip() or subtype or "unknown"
    if subtype in _CLAUDE_SUBTYPE_CATEGORY:
        return _CLAUDE_SUBTYPE_CATEGORY[subtype], error_msg
    raw = error_msg.lower()
    if "timeout" in raw:
        return "timeout", error_msg
    if "hit your limit" in raw or "rate limit" in raw:
        return "rate_limit", error_msg
    if error_msg == "unknown":
        return "uncategorized", error_msg
    return "api_error", error_msg


def _fetch_status(ctx: LoopContext, entity_type: str, eid: str) -> str | None:
    """force_update 직전 entity 의 최신 status. 실패 시 None — fallback 은 호출자."""
    try:
        resp = ctx.client.api(f"{entity_type}.get", {id_field_for(entity_type): eid})
    except Exception as e:
        ctx.log.warning(f"post_turn_guard: fresh status fetch 실패 ({eid}) — fallback. err={e}")
        return None
    data = (resp or {}).get("data") or {}
    return data.get("status")


def _emit_event(
    ctx: LoopContext, entity_type: str, eid: str, *,
    text: str, subtype: str, payload: dict, tid: str | None, label: str,
) -> None:
    ctx.client.api_safe(
        "event.add",
        {"entity_type": entity_type, "entity_id": eid,
         "text": text, "subtype": subtype, "payload": payload},
        issue_id=tid, label=label,
    )


# UI HandoffCallout 의 원클릭 버튼 — 자동 발행 handoff/halt 코멘트에 동봉.
# 스키마 정본: handoff_patterns.md §payload.options.
def _handoff_options_for_issue(category: str, status: str) -> list[dict]:
    """post_turn_guard 자동 인계 시 issue 콜아웃에 띄울 사람 행동 후보.

    waiting (input_too_long) 은 사람이 intent/plan 축약 후 재진입 / 취소,
    error (max_turns/no_progress/uncategorized) 는 todo 로 되돌려 재시도 / 취소.
    options 가 비어 있으면 HandoffCallout 은 본문만 — 하위 호환.
    """
    if status == "waiting" and category == "input_too_long":
        return [
            {"label": "intent/plan 단축 — 재진입", "key": "r", "tone": "primary",
             "action": {"type": "reply",
                        "text": "intent/plan 단축 완료 — 진행 재개해주세요."}},
            {"label": "취소", "key": "c", "tone": "danger",
             "action": {"type": "transition", "status": "cleanup",
                        "comment": "취소 진입 (input_too_long)"}},
        ]
    if status == "error":
        return [
            {"label": "todo 로 재시도", "key": "r", "tone": "primary",
             "action": {"type": "transition", "status": "todo",
                        "comment": "사람 재시도 결정 (error → todo)"}},
            {"label": "취소", "key": "c", "tone": "danger",
             "action": {"type": "transition", "status": "cleanup",
                        "comment": "취소 진입 (error → cleanup)"}},
        ]
    return []


def post_turn_guard(
    ctx: LoopContext,
    entity: dict,
    entity_type: str,
    cycle_result: dict,
    *,
    phase: str = "progress",
    fresh_status: str | None = None,
    no_progress: bool = False,
) -> None:
    """post-turn entity continuity 가드 — 두 트리거 단일 입구.

    1) claude CLI 자체 에러(`cycle_result.is_error=True`) — subtype/raw text 로
       카테고리 분류 후 `_CATEGORY_POLICY` 적용.
    2) 비에러 cycle 이 끝났는데 entity 가 진전 없이 능동 status 로 남음
       (`no_progress=True`) — silent deadlock 가드.
       - issue (running/cleanup): force_error.
       - container (active + 이번 turn mutation 0): status=waiting 으로 parked
         (사람 댓글로 복구). worker.py 가 mutation 유무를 판정해 mutation 없을 때만 호출.

    `fresh_status` 가 호출자 측에서 이미 알려져 있으면 인자로 주입(refetch 생략).
    fetch 실패 시 fresh_status=None 으로 진입 → `_CATEGORY_POLICY` 의 active 분기를
    그대로 따른다(안전측: force_error 카테고리는 force, soft 카테고리는 status 유지).
    """
    idf = id_field_for(entity_type)
    eid = entity[idf]
    tid = eid if entity_type == "issue" else None

    if no_progress:
        category = "no_progress"
        error_msg = (
            f"능동 status({fresh_status})인데 mutation 없이 turn 종료 — 상태 전이/자식 생성/"
            f"entity 갱신 capability 미호출 의심 (deadlock 방지: issue=error, container=waiting)"
        )
    else:
        category, error_msg = _classify_cli_error(cycle_result)
        if category == "uncategorized":
            ctx.log.error(f"에스컬레이션: 분류 불가 — 원본 result={cycle_result!r}")

    short_msg = str(error_msg)[:500]
    ctx.log.error(
        f"post_turn_guard: {entity.get('title')} — category={category} "
        f"phase={phase} msg={short_msg[:200]}"
    )

    if fresh_status is None and not no_progress:
        # no_progress 경로는 caller(worker.py)가 이미 refresh 한 fresh_status 를
        # 주입한다 — 그쪽에서 None 으로 들어왔다면 caller 버그라기보다 refresh
        # 자체가 실패한 경우이므로 None 그대로 active 분기로 떨어진다.
        fresh_status = _fetch_status(ctx, entity_type, eid)

    # passive skip 은 CLI 에러 경로(no_progress=False)에서만 적용한다.
    # no_progress 는 능동 status 데드락 가드 — worker.py 가 fresh_status ∈
    # (running, cleanup) 일 때만 호출하므로 항상 force_error 분기로 떨어진다.
    is_passive = (fresh_status in _PASSIVE_STATES) and not no_progress
    action = "halt_event" if is_passive else _CATEGORY_POLICY.get(category, "force_error")

    base_comment = f"agent-loop {phase} {category}: {short_msg}"
    common_payload = {
        "category": category, "phase": phase, "error_msg": short_msg,
    }

    if entity_type in ("initiative", "project"):
        # 통합 컨테이너 모델 (backlog/active/waiting/done/archive). error/cleanup status 는
        # 없다 (active 한정 워커). 두 갈래로 분기:
        #
        #   (a) no_progress (비에러 turn 인데 active 인 채 이번 turn 에 mutation 0):
        #       데드락 가드 — status="waiting" 으로 parked (사람 댓글로만 재개). 이게
        #       active 인 채 self-action 이 매 cycle 재발급돼 워커가 영구 re-invoke 되는
        #       루프를 끊는다 (issue 의 running→error 가드의 컨테이너 아날로그, 단 error
        #       대신 댓글로 복구 가능한 waiting). worker.py 가 *mutation 없음* 일 때만 이
        #       경로로 들여보낸다 — mutation 이 있었으면(자식 생성·status 전이·entity update)
        #       정상 idle 이라 호출 자체가 안 된다.
        #
        #   (b) CLI 에러 카테고리: soft(runtime/timeout/api_error/rate_limit)는 status 유지
        #       → 다음 cycle fresh session 재시도. hard(max_turns/uncategorized/input_too_long)
        #       는 hold=true 로 자동 re-spawn 루프 차단 (사람이 원인 해소 후 hold 해제).
        #       어느 쪽이든 halt event + session reset, status 는 그대로.
        if no_progress:
            ctx.log.info(
                f"post_turn_guard {entity_type}: no_progress (mutation 0, status={fresh_status}) "
                f"— status=waiting 으로 parked (사람 댓글 reply 까지), session reset"
            )
            _emit_event(
                ctx, entity_type, eid, text=base_comment, subtype="halt",
                payload={**common_payload, "parked_to_waiting": True}, tid=None,
                label=f"{entity_type} post_turn_guard halt-event 게시 실패 ({eid})",
            )
            ctx.client.api_safe(
                f"{entity_type}.update",
                {idf: eid, "status": "waiting",
                 "comment": base_comment, "comment_subtype": "handoff"},
                label=f"{entity_type} -> waiting (post_turn_guard no_progress)",
            )
            ctx.session_store.reset(eid)
            return

        policy = _CATEGORY_POLICY.get(category, "force_error")
        hard = policy in ("force_error", "handoff")
        ctx.log.info(
            f"post_turn_guard {entity_type}: category={category} hard={hard} — "
            f"halt event{', hold=true' if hard else ''}, session reset (status 유지)"
        )
        _emit_event(
            ctx, entity_type, eid, text=base_comment, subtype="halt",
            payload={**common_payload, "hard": hard}, tid=None,
            label=f"{entity_type} post_turn_guard halt-event 게시 실패 ({eid})",
        )
        if hard:
            ctx.client.api_safe(
                f"{entity_type}.update", {idf: eid, "hold": True},
                label=f"{entity_type} -> hold (post_turn_guard {category})",
            )
        ctx.session_store.reset(eid)
        return

    if action == "halt_event":
        # passive — 모든 카테고리 공통. ISSUE-116 정책: status 유지, halt event 만.
        ctx.log.info(
            f"post_turn_guard skip force: status={fresh_status} (passive) — "
            f"category={category} halt event 로만 기록, status 유지"
        )
        _emit_event(
            ctx, entity_type, eid, text=base_comment, subtype="halt",
            payload={**common_payload, "current_status": fresh_status, "force_error_skipped": True},
            tid=tid, label=f"{entity_type} post_turn_guard halt-event 게시 실패 ({eid})",
        )
        ctx.session_store.reset(eid)
        return

    # 이하 issue 전용 — 컨테이너(project/initiative)는 위에서 early-return 됐다.
    if action == "handoff":
        # input_too_long × active — 사람만 풀 수 있음. waiting+handoff 로 인계.
        handoff_text = (
            f"agent-loop {phase} 사람 인계 ({category}): prompt 가 너무 길어 LLM 진행 불가. "
            f"intent/plan 축약 후 댓글 회신 필요. error_msg={short_msg}"
        )
        update_fields = {
            idf: eid, "status": "waiting",
            "comment": handoff_text, "comment_subtype": "handoff",
            "comment_payload": {
                "reason": category, "phase": phase, "error_msg": short_msg,
                "options": _handoff_options_for_issue(category, "waiting"),
            },
        }
        ctx.client.api_safe(
            f"{entity_type}.force_update", update_fields,
            issue_id=tid, label=f"{entity_type} -> waiting (handoff:{category})",
        )
        ctx.session_store.reset(eid)
        return

    # action == "force_error" — max_turns / uncategorized × active, no_progress.
    update_fields = {
        idf: eid, "status": "error",
        "comment": base_comment, "comment_subtype": "halt",
        "comment_payload": {
            **common_payload,
            "options": _handoff_options_for_issue(category, "error"),
        },
    }
    ctx.client.api_safe(
        f"{entity_type}.force_update", update_fields,
        issue_id=tid, label=f"{entity_type} -> error",
    )
    ctx.session_store.reset(eid)
