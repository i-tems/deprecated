"""wake.wait_for_change — long-poll 진입점 (entity / cell 공용).

worker 는 entity 단위 변경 (event / status / field) 을 long-poll 하고,
agent-loop 는 cell 단위 변경 (새 issue/project 생성 등 새 actionable) 을 long-poll
한다. 두 경로 모두 같은 `wake_bus` (in-process version-feed pubsub) 위에서
동작 — key namespace 만 다르다 (entity_id 또는 `cell:<cell_id>`).

since (ISO timestamp) 가 있으면 entity 모드에서 race 방어용 pre-check (그 시각
이후 박힌 event 가 있으면 wait 없이 즉시 pending 응답). cell 모드에서는 since
미사용 — cell 자체는 state 가 없고 새 actionable 의 도착은 events 와 무관하므로
race 방어가 의미 없다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from capability_framework import CapabilityResponse

from .. import wake_bus
from ..db import get_engine

log = logging.getLogger("hub.wake")
router = APIRouter()

_ENTITY_TYPES = {"issue", "project", "initiative"}
_CELL_TYPE = "cell"


def _wake_key(entity_type: str, entity_id: str) -> str:
    """wake_bus 에 쓰는 key. cell 은 namespace prefix 로 entity uuid 와 충돌 회피."""
    if entity_type == _CELL_TYPE:
        return f"cell:{entity_id}"
    return entity_id


class WaitForChangeRequest(BaseModel):
    entity_type: str             # "issue" | "project" | "cell"
    entity_id: str               # entity uuid 또는 cell_id (entity_type=cell 시)
    since: str | None = None     # ISO timestamp. entity 모드 race 방어 pre-check 용.
    timeout: float = 60.0        # hold 시간 (초). caller 가 +10s 정도 timeout 으로 호출.


def _has_pending_events(entity_type: str, entity_id: str, since: str) -> bool:
    """since 이후 events 가 1건 이상 있는지. wait 진입 직전 race 방어 (entity 전용)."""
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM events "
                "WHERE entity_type=:t AND entity_id=:i AND ts > :since LIMIT 1"
            ),
            {"t": entity_type, "i": entity_id, "since": since},
        ).fetchone()
    return row is not None


@router.post("/wake.wait_for_change")
async def wake_wait_for_change(req: WaitForChangeRequest, request: Request) -> CapabilityResponse:
    """변경 long-poll. 변경/pending 시 즉시 응답, timeout 시 빈 응답.

    data.wake_reason: "pending" | "notified" | "timeout"
    """
    if (
        req.since
        and req.entity_type in _ENTITY_TYPES
        and _has_pending_events(req.entity_type, req.entity_id, req.since)
    ):
        return CapabilityResponse(status="ok", data={"wake_reason": "pending"})
    woken = await wake_bus.wait_for_change(
        _wake_key(req.entity_type, req.entity_id),
        max(0.0, float(req.timeout)),
    )
    return CapabilityResponse(
        status="ok",
        data={"wake_reason": "notified" if woken else "timeout"},
    )
