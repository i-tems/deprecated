"""sse.subscribe — 브라우저 EventSource 용 push 스트림 (wake_bus 위).

UI 가 interval polling 대신 이 SSE 에 붙어, 구독한 cell/entity 의 변경이
wake_bus 에 박히면 `event: change` 를 받아 그때만 데이터를 refetch 한다.
변경 없으면 주기적 keepalive 주석만 흘려 연결을 유지한다.

EventSource 제약 (커스텀 헤더 불가) 대응:
- 인증: 콘솔 JWT 는 쿠키(AUTH_COOKIE_NAME)로도 이동하므로 same-origin
  EventSource 가 자동 전송 → `request_auth_payload` 로 in-handler 검증.
- cell: `X-Cell-Id` 헤더 대신 query param `cell_id`. cell 접근 권한은
  CellMiddleware 의 console 분기와 동일 규칙으로 in-handler 검증 (아래
  `_authorize` — CellMiddleware 가 source of truth, 동일 로직 유지).
- 따라서 이 경로는 Auth/Cell 미들웨어에서 exempt 하고, ActionLog/Metrics
  미들웨어에서도 skip (ActionLog 는 body_iterator 를 완전 드레인하므로 무한
  스트림이 hang 됨 — `/worker.heartbeat` 와 동일하게 SKIP_PATHS 처리).

구독 key 는 클라이언트가 raw 로 못 넣는다 (활동 추론 방지) — 서버가 검증된
cell_id 로 `cell:<cell_id>` 를, entity 지정 시 그 entity_id 를 구성한다
(wake_bus key 규약과 동일).
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from .. import wake_bus
from ..auth import is_admin_email, request_auth_payload
from ..storage import cells_repo

log = logging.getLogger("hub.sse")
router = APIRouter()

# 변경이 없을 때 keepalive 주석을 흘리는 주기(초). nginx proxy_read_timeout
# (3600s) 보다 충분히 짧아 연결 유지. wake_bus.wait_for_change 의 hold 시간으로도
# 쓰인다 (poller tick=1s 라 wake 지연과는 무관).
_HEARTBEAT_S = 25.0

# 허용 scope → wake_bus key prefix. key = f"{prefix}{cell_id}". 클라이언트가
# raw key 를 못 넣게 서버가 검증된 cell_id 로만 구성한다 (활동 추론 방지).
# cell: issue/project/event 변경. signals: signal.emit. inbox: emit_inbox.
_SCOPE_KEY_PREFIX = {
    "cell": "cell:",
    "signals": "signals:",
    "inbox": "inbox:",
}


def _authorize(request: Request, cell_id: str) -> None:
    """콘솔 사용자의 cell 접근 검증. CellMiddleware 의 console 분기와 동일 규칙.

    NOTE: 이 검사의 source of truth 는 cell_middleware.CellMiddleware 다.
    EventSource 가 X-Cell-Id/X-Source 헤더를 못 보내 미들웨어를 우회하므로
    동일 규칙을 여기서 재현한다. CellMiddleware 변경 시 함께 갱신할 것.
    """
    payload = request_auth_payload(request)
    if payload is None:
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    cell = cells_repo.get(cell_id)
    if not cell:
        raise HTTPException(status_code=404, detail=f"Cell '{cell_id}' not found")
    if cell.get("status") == "archived":
        raise HTTPException(status_code=403, detail=f"Cell '{cell_id}' archived")
    user_email = str(payload.get("sub", "")).strip().lower()
    allowed_emails = {
        str(email).strip().lower()
        for email in (cell.get("allowed_emails") or [])
        if str(email).strip()
    }
    if not is_admin_email(user_email) and allowed_emails and user_email not in allowed_emails:
        raise HTTPException(status_code=403, detail=f"Cell '{cell_id}' access denied")


async def _wait_any(keys: list[str], timeout: float) -> bool:
    """keys 중 하나라도 변경되면 True, timeout 이면 False.

    진 issue 는 취소 후 await 해 wake_bus refcount finally 정리를 보장한다.
    """
    issues = [asyncio.create_task(wake_bus.wait_for_change(k, timeout)) for k in keys]
    try:
        done, pending = await asyncio.wait(
            issues, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for t in issues:
            if not t.done():
                t.cancel()
        await asyncio.gather(*issues, return_exceptions=True)
    return any(t.result() for t in done if not t.cancelled() and t.exception() is None)


@router.get("/sse.subscribe")
async def sse_subscribe(request: Request) -> StreamingResponse:
    """cell(+선택 entity) 변경 push 스트림.

    query:
      - cell_id (필수)
      - entity_id (선택, 더 좁은 entity 단위 구독)
      - scopes (선택, csv) — cell(기본) | signals | inbox. 클라이언트가 raw
        key 를 못 넣게 검증된 cell_id 로 서버가 key 를 구성한다.
    SSE events: `change` (data={"keys":[...]}) / 주기적 `: keepalive` 주석.
    """
    cell_id = (request.query_params.get("cell_id") or "").strip()
    if not cell_id:
        raise HTTPException(status_code=400, detail="cell_id required")
    _authorize(request, cell_id)

    raw_scopes = (request.query_params.get("scopes") or "cell").strip()
    scopes = {s.strip() for s in raw_scopes.split(",") if s.strip()}
    unknown = scopes - _SCOPE_KEY_PREFIX.keys()
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown scopes: {sorted(unknown)}")
    keys = [f"{_SCOPE_KEY_PREFIX[s]}{cell_id}" for s in sorted(scopes)] or [f"cell:{cell_id}"]
    entity_id = (request.query_params.get("entity_id") or "").strip()
    if entity_id:
        # bare entity_id: 실제 entity 변경(comment/status/field, events.py).
        # act:<id>: 워커 AI activity 스트림(worker._act_wake_key) — 워커 idle
        # long-poll 과 분리된 전용 키. 둘 다 들어야 detail 페이지가 본문 변경과
        # transcript 를 모두 near-real-time 으로 refetch 한다.
        keys.append(entity_id)
        keys.append(f"act:{entity_id}")

    async def _stream():
        # 최초 주석으로 스트림을 즉시 연다 (브라우저 onopen 트리거).
        yield ": connected\n\n"
        # 단절 감지는 request.is_disconnected() 폴링에 의존하지 않는다 —
        # BaseHTTPMiddleware 가 여러 겹 쌓인 경로에서는 receive 채널이 래핑돼
        # 이 값이 신뢰할 수 없다 (Starlette #1438/#1922; spurious True 면
        # connected 직후 스트림이 닫혀 브라우저가 onopen→onerror 만 반복 →
        # UI 가 SSE 를 못 붙고 폴링으로 영구 degrade). 대신 클라이언트가 사라지면
        # 다음 yield(send) 가 실패해 제너레이터가 닫히는 것에 의존한다.
        # _HEARTBEAT_S(25s) 주기 keepalive 가 있으므로 단절은 최대 그 시간 내에
        # 감지되고, _wait_any/wake_bus 의 finally 가 watch refcount 를 정리한다.
        while True:
            try:
                woken = await _wait_any(keys, _HEARTBEAT_S)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - 스트림은 끊지 않고 keepalive
                log.warning(f"[sse] wait_any 오류 (keepalive 지속): {exc}")
                yield ": keepalive\n\n"
                continue
            if woken:
                yield f"event: change\ndata: {json.dumps({'keys': keys})}\n\n"
            else:
                yield ": keepalive\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx proxy_buffering off 가 이미 설정돼 있지만 이중 안전장치.
            "X-Accel-Buffering": "no",
        },
    )
