"""Per-user read-state — 사용자가 엔티티를 마지막으로 본 시각.

덱(Deck) attention surface 가 "내가 본 이후 변화(새 코멘트·상태전이)"를 강조하고 이미
보고 안 바뀐 항목을 가라앉히기 위한 per-user 신호. 저장소는 user_settings 와 동일
패턴 — 볼륨(/var/data)의 단일 JSON 파일(email→{entity_key→iso ts}). cross-cell 글로벌:
entity_id 가 cell-prefix 라 충돌 없음.

판정(INFRA-ISSUE-266):
- viewed = detail 페이지 열람 시 UI 가 view.mark 호출 (자동).
- changed_since_view = 한 번도 안 봤거나(신규) 마지막 본 이후 활동(코멘트/상태전이)이
  있으면 True. 활동 시각은 entity.last_activity_ts(events.emit_event 가 갱신), 없으면
  updated_at 폴백.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse
from ..auth import request_auth_payload

router = APIRouter()

# 기본값은 PVC(hive-data) 마운트 경로 /data — user_settings 와 동일 볼륨. configmap 이
# VIEW_STATE_PATH 로 오버라이드(명시).
VIEW_STATE_PATH = Path(os.environ.get("VIEW_STATE_PATH", "/data/view_state.json"))

_ENTITY_TYPES = ("issue", "project", "initiative")


def _caller_email(request: Request) -> str | None:
    """호출자 이메일(소문자). caller token 은 state.user_email, console JWT 는 sub."""
    email = getattr(request.state, "user_email", None)
    if not email:
        payload = request_auth_payload(request)
        if payload:
            email = payload.get("sub")
    email = str(email or "").strip().lower()
    return email or None


def _load() -> dict[str, dict]:
    if not VIEW_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(VIEW_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict]) -> None:
    VIEW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    VIEW_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def _key(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}:{entity_id}"


def attach_read_state(entities: list[dict], *, id_field: str, entity_type: str, request: Request) -> None:
    """list 응답 page 항목에 last_viewed_at·changed_since_view derived 필드 부착.

    호출자 미식별이면 no-op (필드 부재 → UI 가 read-state 미적용으로 처리). view_state
    파일은 호출당 1회 read (page O(1) 비교) — 5s 폴링 경로라 O(N) event 재읽기를 피한다.
    """
    email = _caller_email(request)
    if not email:
        return
    views = _load().get(email) or {}
    for e in entities:
        eid = e.get(id_field)
        if not eid:
            continue
        viewed = views.get(_key(entity_type, eid))
        # 활동 = 코멘트/상태전이만(last_activity_ts). updated_at 폴백을 쓰지 않는다 —
        # 단순 필드 편집(updated_at 만 bump)은 사용자 선택상 "변화"가 아니다(INFRA-ISSUE-266).
        activity = e.get("last_activity_ts")
        e["last_viewed_at"] = viewed
        e["changed_since_view"] = (viewed is None) or bool(activity and activity > viewed)


class ViewMarkRequest(BaseModel):
    entity_type: str = Field(description='"issue" | "project" | "initiative".')
    entity_id: str


@router.post("/view.mark")
async def view_mark(req: ViewMarkRequest, request: Request) -> CapabilityResponse:
    """엔티티를 호출자가 "지금 봤다"고 기록 — detail 페이지 열람 시 UI 가 호출.

    per-user last_viewed_at 을 now 로 갱신 → 덱이 "본 이후 변화"를 다시 계산한다.
    """
    if req.entity_type not in _ENTITY_TYPES:
        return CapabilityResponse(
            status="error", error_code="invalid_input",
            message=f"entity_type must be one of {_ENTITY_TYPES}",
        )
    email = _caller_email(request)
    if not email:
        return CapabilityResponse(status="error", error_code="unauthorized", message="사용자 인증이 필요합니다.")
    now = datetime.now(timezone.utc).isoformat()
    data = _load()
    entry = dict(data.get(email) or {})
    entry[_key(req.entity_type, req.entity_id)] = now
    data[email] = entry
    _save(data)
    return CapabilityResponse(status="ok", data={
        "entity_type": req.entity_type,
        "entity_id": req.entity_id,
        "last_viewed_at": now,
    })
