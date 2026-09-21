"""Event emission and inbox helpers."""

import re
from datetime import datetime, timezone
from pathlib import Path

from .storage import append_jsonl, today_path
from .storage.idgen import new_entity_id

# `.../cells/<cell_id>/events` 형태에서 cell_id 추출 (event_id scope 용).
_CELL_FROM_PATH_RE = re.compile(r"/cells/([^/]+)/")


def _cell_from_dir(directory: Path) -> str | None:
    m = _CELL_FROM_PATH_RE.search(str(directory))
    return m.group(1) if m else None


def emit_event(
    entity_type: str,
    entity_id: str,
    event_type: str,
    data: dict,
    *,
    event_dir: Path,
    session_id: str | None = None,
    principal=None,
    cascade_to: list[str] | None = None,
):
    """엔티티 활동 이벤트를 기록.

    event_dir 는 cell-scoped 경로(`cp.event_dir`) 필수 — cell context 없는
    경로는 event 발행 자격이 없다.

    principal_id·principal_type은 인증된 principal에서 도출한다 (auth
    middleware가 항상 채워줌; 없는 흐름은 둘 다 미기록). trace
    컨텍스트(trace_id/span_id/parent_span_id)는 ContextVar에서 자동 추출 —
    호출자가 별도로 넘길 필요 없음.

    cascade_to: 자식 cascade. 자식 issue done 시 부모 project_id 등 추가 entity_id 를
    전달하면 그쪽 long-poll wait 도 함께 깨운다. emit 끝나면 자기 entity_id +
    cascade_to 각각에 `wake_bus.notify` 호출.
    """
    from .tracing import get_trace_context
    from . import wake_bus

    now = datetime.now(timezone.utc).isoformat()
    event_id, _seq = new_entity_id(_cell_from_dir(event_dir), "event")
    record = {
        "event_id": event_id,
        "ts": now,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "type": event_type,
        "data": data,
    }
    if principal:
        record["principal_id"] = principal.id
        record["principal_type"] = principal.type
    if session_id:
        record["session_id"] = session_id
    trace_id, span_id, parent_span_id = get_trace_context()
    if trace_id:
        record["trace_id"] = trace_id
    if span_id:
        record["span_id"] = span_id
    if parent_span_id:
        record["parent_span_id"] = parent_span_id
    append_jsonl(today_path(event_dir), record)
    # 덱(Deck) 신호: 코멘트·상태전이는 "본 이후 변화" 로 잡을 의미 있는 활동 →
    # 엔티티에 last_activity_ts(단조) 기록. emit_event 가 유일한 choke point 이고
    # 모든 comment·status_change 가 entity_lock 밖에서 여기를 지나므로 한 곳에서 처리.
    if event_type in ("comment", "status_change") and entity_type in ("issue", "project", "initiative"):
        _touch_entity_activity(event_dir, entity_type, entity_id, now)
    # push 알림 — wake.wait_for_change long-poll 중인 worker 즉시 깨움.
    wake_bus.notify(entity_id)
    for wake_target in (cascade_to or []):
        wake_bus.notify(wake_target)
    return record


def _touch_entity_activity(event_dir: Path, entity_type: str, entity_id: str, ts: str) -> None:
    """엔티티의 last_activity_ts 를 ts 로 전진(단조) — 덱 changed_since_view 계산용.

    updated_at 은 모든 필드 touch 에 bump 돼 "코멘트 OR 상태전이"보다 과하게 잡힌다.
    그 둘만 의미 있는 변화로 보고 전용 단조 필드를 둔다. best-effort: 활동 추적 실패가
    event emit(critical path)을 막지 않도록 예외를 삼킨다. 지연 import 로 순환참조 회피.
    """
    try:
        from .config import CellPaths
        from .helpers import entity_lock
        from .storage.sql import cas_update_entity, parse_entity_path
        cell_id = _cell_from_dir(event_dir)
        if not cell_id:
            return
        cp = CellPaths(cell_id)
        entity_file = {
            "issue": cp.issue_file,
            "project": cp.project_file,
            "initiative": cp.initiative_file,
        }[entity_type]

        def _touch(found):
            if not found or (found.get("last_activity_ts") or "") >= ts:
                return (None, None)  # 행 없음 or 이미 최신 — 쓰기 안 함
            found["last_activity_ts"] = ts
            return (None, found)

        table = parse_entity_path(entity_file)["table"]
        with entity_lock(entity_file):
            cas_update_entity(table, f"{entity_type}_id", cell_id, entity_id, _touch)
    except Exception:
        pass


def emit_inbox(
    inbox_type: str,
    entity_id: str,
    summary: str,
    *,
    cell_id: str | None = None,
    owner: str | None = None,
    body: str | None = None,
):
    """사람 확인용 inbox 항목 발행. Issue/Project done 시 자동 호출 + inbox.add 외부 진입점."""
    from .config import INBOX_DIR

    now = datetime.now(timezone.utc).isoformat()
    inbox_id, _seq = new_entity_id(cell_id, "inbox")
    record = {
        "inbox_id": inbox_id,
        "type": inbox_type,
        "status": "unread",
        "ref": entity_id,
        "summary": summary,
        "owner": owner,
        "cell_id": cell_id,
        "created_at": now,
    }
    if body is not None:
        record["body"] = body
    append_jsonl(today_path(INBOX_DIR), record)
    from .slack_inbox import _emit_slack_inbox
    _emit_slack_inbox(record)
    # 모든 inbox 항목 생성의 단일 funnel — 여기서 inbox scope 를 깨우면
    # signal.emit / issue·project done·waiting 등 모든 경로가 균일하게 push 된다.
    if cell_id:
        from . import wake_bus
        wake_bus.notify(f"inbox:{cell_id}")
    return record
