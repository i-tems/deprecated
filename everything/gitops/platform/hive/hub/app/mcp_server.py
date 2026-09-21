"""MCP server — Tier 1 메타툴 3종 (capability_list/describe/invoke).

Streamable HTTP transport. hub FastAPI 앱에 ``/mcp``로 마운트된다.
도구 실행은 core ASGI를 통해 in-process로 dispatch하며, ``Authorization`` ·
``X-Source`` 헤더는 그대로 전파해 미들웨어 체인(auth → cell → enforcement)을
정상 통과시킨다. ``X-Source`` 누락 시 console JWT(``principal_type`` 없음)는
auth_middleware 의 console 분기를 못 타 401 — UI 터미널 sandbox(.mcp.json,
X-Source: console) 경로가 끊긴다.

Cell-agnostic: 매 invoke 마다 ``cell`` 인자로 대상 cell 명시. 인자가
in-process dispatch 시 ``X-Cell-Id`` 헤더로 변환된다 — 인입 ``X-Cell-Id``
헤더는 무시 (cut-over). 누락 시 generic 메타툴은 FastMCP signature 검증으로
422, facade 는 ``cell_required`` error envelope.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings


# DNS rebinding 보호 — 운영 호스트와 in-cluster 호스트 모두 허용.
# 워커·agent-loop 이 `http://hive-hub.hive.svc.cluster.local:8000` 로 호출하므로
# 클러스터 DNS 변형 전부 등록해야 421 Invalid Host 차단을 통과한다.
_TRANSPORT_SECURITY = TransportSecuritySettings(
    allowed_hosts=[
        "hive-hub.lab.i-tems.com",
        "hive-hub.hive.svc.cluster.local",
        "hive-hub.hive.svc.cluster.local:8000",
        "hive-hub.hive",
        "hive-hub.hive:8000",
        "hive-hub",
        "hive-hub:8000",
        "localhost",
        "127.0.0.1",
    ],
)

mcp = FastMCP(
    "hive",
    streamable_http_path="/",
    transport_security=_TRANSPORT_SECURITY,
    # stateful 모드면 hub pod 재시작 시 in-memory session manager 가 비워져
    # 클라이언트가 들고 있던 Mcp-Session-Id 가 404 "Session not found" 로 떨어진다.
    # claude MCP 클라이언트는 자동 재핸드셰이크하지 않아 사용자가 /mcp reconnect
    # 하기 전까지 hive MCP 전체가 끊긴다. 매 요청 독립 처리로 전환.
    stateless_http=True,
)

# hub FastAPI app 참조 — __init__.py에서 set_hub_app으로 주입.
_hub_app = None


def set_hub_app(app) -> None:
    global _hub_app
    _hub_app = app


def register_facade_tools() -> list[str]:
    """선정 capability 를 레지스트리 기반 전용 함수 툴로 동적 등록.

    generic 메타툴 3종(capability_list/describe/invoke)은 무변경 — long-tail
    경로 그대로. 전용 함수는 그 위의 facade 로 동일 dispatch(_invoke_internal)·
    동일 응답 봉투·동일 헤더 전파를 보장한다. ``set_hub_app`` 이후 호출.
    """
    from .mcp_facade import register_facade_tools as _register

    return _register(mcp, _hub_app, _invoke_internal)


def _propagated_headers(ctx: Context, *, cell: str) -> dict[str, str]:
    request = ctx.request_context.request
    # cell 은 invoke 인자 정본 — 인입 X-Cell-Id 헤더는 무시 (cut-over).
    headers = {
        "Content-Type": "application/json",
        "X-Hive-Channel": "mcp",
        "X-Cell-Id": cell,
    }
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    # console JWT(principal_type 없음)는 auth_middleware 가 X-Source==console
    # 일 때만 user 로 인증한다. 누락 시 내부 dispatch 가 caller-token 분기에서
    # 떨어져 401 — UI 터미널 sandbox(.mcp.json: X-Source: console) 가 끊긴다.
    source = request.headers.get("X-Source")
    if source:
        headers["X-Source"] = source
    return headers


async def _invoke_internal(
    ctx: Context, endpoint: str, payload: dict[str, Any], *, cell: str
) -> dict[str, Any]:
    """core ASGI 내부 dispatch. 미들웨어 체인 그대로 통과."""
    if _hub_app is None:
        return {
            "status": "error",
            "error_code": "not_initialized",
            "message": "core app reference not set",
        }
    transport = httpx.ASGITransport(app=_hub_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://core.local"
    ) as client:
        resp = await client.post(
            f"/{endpoint.lstrip('/')}",
            headers=_propagated_headers(ctx, cell=cell),
            json=payload,
        )
    if resp.status_code >= 400:
        return {
            "status": "error",
            "error_code": "internal_http_error",
            "message": f"{resp.status_code} {resp.reason_phrase}",
            "body": resp.text,
        }
    return resp.json()


@mcp.tool()
async def capability_list(cell: str, ctx: Context) -> dict[str, Any]:
    """Hive에 등록된 모든 capability 이름과 1줄 설명을 반환.

    각 capability는 ``domain.action`` 형식 (예: project.list, issue.get, signal.emit).
    실행은 capability_invoke, 파라미터 스키마는 capability_describe.

    Args:
        cell: 대상 cell id (예: "infra", "items"). MCP transport 는 cell-agnostic —
            매 호출에 명시. 인입 ``X-Cell-Id`` 헤더는 무시된다 (cut-over).
    """
    return await _invoke_internal(ctx, "capability.list", {}, cell=cell)


@mcp.tool()
async def capability_describe(
    cell: str, names: list[str], ctx: Context
) -> dict[str, Any]:
    """주어진 capability들의 파라미터 스키마를 반환.

    Args:
        cell: 대상 cell id. 매 호출에 명시.
        names: capability 이름 리스트 (예: ["project.list", "issue.get"]).
    """
    return await _invoke_internal(
        ctx, "capability.describe", {"ids": names}, cell=cell
    )


@mcp.tool()
async def capability_invoke(
    cell: str,
    name: str,
    params: dict[str, Any] | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Hive capability를 실행한다.

    Args:
        cell: 대상 cell id. 매 호출에 명시.
        name: capability 이름 (예: "project.list"). 점 표기 그대로.
        params: capability 파라미터. 정확한 스키마는 capability_describe로 확인.

    Returns:
        Core capability 응답 봉투 ({status, data, error_code, message}).
    """
    return await _invoke_internal(ctx, name, params or {}, cell=cell)


def get_asgi_app():
    """streamable HTTP MCP ASGI 앱. core가 ``/mcp``로 mount한다."""
    return mcp.streamable_http_app()


# session_manager는 issue group을 필요로 하므로 startup에서 명시 진입한다.
# (mount만으로는 sub-app lifespan이 propagate되지 않아 RuntimeError 발생).
_session_ctx = None


async def start_session_manager() -> None:
    global _session_ctx
    _session_ctx = mcp.session_manager.run()
    await _session_ctx.__aenter__()


async def stop_session_manager() -> None:
    global _session_ctx
    if _session_ctx is not None:
        await _session_ctx.__aexit__(None, None, None)
        _session_ctx = None
