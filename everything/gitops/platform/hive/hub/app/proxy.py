"""리모트 capability 서비스 프록시.

registry에 등록된 prefix에 매칭되는 요청을 리모트 서비스로 전달한다.
"""

import asyncio
import os

import httpx
from fastapi import FastAPI, Request, Response

from .auth import _request_token
from .config import ensure_cell_access
from .registry import REGISTRY

# query.sql(=prefix "query") 은 Kyuubi/Spark 로 100s+ 걸릴 수 있다. 단일 worker hub 에서
# 무제한 동시 실행하면 이벤트 루프가 /health(readiness timeout 8s)를 제때 못 돌려
# readiness 실패 → endpoint 제거 → 전 소비자 502 (INFRA-ISSUE-266/273). 동시 실행 수를
# 제한해 초과분은 cheap 하게 대기시키고 /health 응답성을 지킨다. 0 이하면 무제한.
_QUERY_CONCURRENCY = int(os.environ.get("HUB_QUERY_CONCURRENCY", "3"))
_query_sem: asyncio.Semaphore | None = None


def _query_guard() -> asyncio.Semaphore | None:
    """실행 중 event loop 에 바인딩되도록 첫 호출 시 lazy 생성."""
    global _query_sem
    if _QUERY_CONCURRENCY <= 0:
        return None
    if _query_sem is None:
        _query_sem = asyncio.Semaphore(_QUERY_CONCURRENCY)
    return _query_sem


async def _proxy_handler(request: Request) -> Response:
    """catch-all 프록시 핸들러. 매칭되는 리모트 서비스로 요청 전달."""
    ensure_cell_access(request)

    # /calendar.fetch → "calendar.fetch"
    path = request.url.path.lstrip("/")
    prefix = path.split(".")[0] if "." in path else None

    svc = None
    if prefix:
        for s in REGISTRY.values():
            if prefix in s.prefixes:
                svc = s
                break

    if not svc:
        return Response(
            content='{"status":"error","error_code":"not_found","message":"no service for this endpoint"}',
            status_code=404,
            media_type="application/json",
        )

    body = await request.body()
    headers = {"Content-Type": "application/json"}
    source = request.headers.get("X-Source")
    if source:
        headers["X-Source"] = source
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    else:
        token = getattr(request.state, "auth_token", None) or _request_token(request)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    cell_id = request.headers.get("X-Cell-Id")
    if cell_id:
        headers["X-Cell-Id"] = cell_id
    issue_id = request.headers.get("X-Issue-Id")
    if issue_id:
        headers["X-Issue-Id"] = issue_id
    session_id = request.headers.get("X-Session-Id")
    if session_id:
        headers["X-Session-Id"] = session_id

    guard = _query_guard() if prefix == "query" else None
    if guard is not None:
        await guard.acquire()
    try:
        async with httpx.AsyncClient(timeout=svc.timeout) as client:
            resp = await client.post(f"{svc.base_url}/{path}", content=body, headers=headers)
    finally:
        if guard is not None:
            guard.release()

    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


def setup_proxy_routes(app: FastAPI):
    """registry의 모든 prefix에 대해 catch-all route 등록."""
    registered = set()
    for svc in REGISTRY.values():
        for prefix in svc.prefixes:
            if prefix in registered:
                continue
            # /{prefix}.{action} 패턴 — FastAPI path parameter로 캡처
            app.add_api_route(
                f"/{prefix}.{{action}}",
                _proxy_handler,
                methods=["POST"],
                name=f"proxy_{prefix}",
                include_in_schema=False,
            )
            registered.add(prefix)
