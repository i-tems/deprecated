"""MCP facade — 자주 쓰는 capability를 레지스트리 기반 전용 함수 툴로 동적 노출.

배경: 모든 capability 호출은 generic 메타툴 ``capability_invoke(name, params)``
단일 경로를 거치며, 처음 쓰는 capability 는 ``capability_describe`` 선행이
강제된다. 자주 쓰는 ticket/issue 계열도 매번 이 인다이렉션(describe 왕복 +
메타툴 dispatch)을 거쳐 토큰·지연·발견성 비용이 누적된다.

설계 원칙(정본과의 정합):
- hive 정본은 "capability 스키마 정본은 live(``capability.describe``),
  정적 md 없음 — 항상 live". 따라서 전용 함수 스키마를 손으로 박지 않는다.
  ``capability.describe`` 와 **동일한 코드 경로**(introspection 의
  ``_extract_request_schema`` / ``_resolve_ref``)로 hub OpenAPI 에서
  tools/list 시점에 동적 생성한다 → 정적 작성 0, 드리프트 0.
- generic ``capability_invoke`` 는 long-tail 용으로 그대로 유지. 전용 함수는
  그 위의 facade 일 뿐 — 동일 dispatch(``_invoke_internal``)·동일 응답
  봉투·동일 cell/auth 헤더 전파 경로를 보장한다(하위호환 무변경).

선정 근거: docs/mcp-facade-capability-selection.md (실측 호출 빈도).
선정 집합은 ``MCP_FACADE_CAPABILITIES`` 환경변수(콤마구분)로 재정의 가능 —
*집합*만 설정이고 *스키마*는 항상 레지스트리에서 동적 생성된다.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import ConfigDict
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata

log = logging.getLogger("hub.mcp_facade")

# 실측(2026-05-17 hive_capability_total) 기반 기본 선정 집합. ticket/issue 워크플로
# 중심 + MCP 호출자(worker·cli)에서 describe→invoke 인다이렉션 비용이 실제로
# 누적되는 capability. 근거·표는 docs/mcp-facade-capability-selection.md.
_DEFAULT_FACADE_CAPABILITIES = (
    "issue.create",
    "issue.get",
    "issue.update",
    "issue.list",
    "project.get",
    "project.list",
    "event.list",
    "event.add",
)


def selected_capabilities() -> list[str]:
    """전용 함수로 노출할 capability id 목록.

    ``MCP_FACADE_CAPABILITIES`` (콤마구분) 로 재정의 가능. 빈 값/미설정 시 기본
    선정 집합. 공백 제거·빈 항목 제거·중복 제거(순서 보존).
    """
    raw = os.environ.get("MCP_FACADE_CAPABILITIES", "").strip()
    items = (
        [c.strip() for c in raw.split(",") if c.strip()]
        if raw
        else list(_DEFAULT_FACADE_CAPABILITIES)
    )
    seen: set[str] = set()
    out: list[str] = []
    for c in items:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


class _PassthroughArgs(ArgModelBase):
    """모든 인자를 검증 없이 그대로 통과시키는 arg model.

    advertised inputSchema(``Tool.parameters``)는 레지스트리에서 동적 생성한
    capability 의 실제 스키마다. 인자 검증/강제는 capability handler(pydantic
    request model)가 단일 정본으로 수행하므로, facade 단에서는 평면 인자를
    그대로 모아 dispatch 한다 — 스키마를 두 곳에서 검증하지 않는다(드리프트 0).
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self.__pydantic_extra__ or {})


def _dynamic_schema(hub_app, cap_id: str) -> tuple[dict[str, Any] | None, str]:
    """capability.describe 와 동일 경로로 hub OpenAPI 에서 (schema, description).

    introspection 모듈의 추출/해석 함수를 그대로 재사용해 ``capability.describe``
    와 1:1 인 capability handler schema 를 얻고, 그 위에 transport-level
    ``cell`` 인자를 합성한다 (cell-agnostic MCP 의 라우팅 인자). capability 가
    OpenAPI 에 없으면 (None, "").
    """
    from .entities.introspection import _extract_request_schema

    spec = hub_app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    paths = spec.get("paths", {})
    path = f"/{cap_id}"
    if path not in paths:
        return None, ""
    post = paths[path].get("post", {})
    description = post.get("description", post.get("summary", "")) or ""
    schema = _extract_request_schema(paths[path], schemas)
    if schema is None:
        return None, ""
    properties = {
        **schema.get("properties", {}),
        "cell": {
            "type": "string",
            "title": "Cell",
            "description": "대상 cell id (예: 'infra', 'items'). 매 호출에 명시.",
        },
    }
    required = ["cell", *(r for r in schema.get("required", []) if r != "cell")]
    return {**schema, "properties": properties, "required": required}, description


def _make_facade(invoke_internal, cap_id: str):
    """cap_id 에 바인딩된 passthrough facade 코루틴.

    generic capability_invoke 와 동일 dispatch(``_invoke_internal``)·동일 응답
    봉투·동일 헤더 전파. ``cell`` 은 transport-level 인자로 분리해 invoke_internal
    의 keyword 로 전달하고, 나머지 평면 인자를 그대로 capability params 로 전달.
    """

    async def _facade(ctx, **params: Any) -> dict[str, Any]:
        cell = params.pop("cell", None)
        if not cell:
            return {
                "status": "error",
                "error_code": "cell_required",
                "message": (
                    f"`cell` argument is required for MCP invoke "
                    f"(facade={cap_id})"
                ),
                "data": None,
            }
        return await invoke_internal(ctx, cap_id, params, cell=cell)

    _facade.__name__ = f"facade__{cap_id.replace('.', '_')}"
    return _facade


def build_facade_tools(hub_app, invoke_internal) -> list[Tool]:
    """선정 capability 별 전용 Tool 을 동적 생성해 반환.

    OpenAPI 에 없는(미등록·이름오타) capability 는 경고 후 skip — generic
    capability_invoke 로 여전히 호출 가능하므로 기능 손실 없음.
    """
    tools: list[Tool] = []
    for cap_id in selected_capabilities():
        schema, description = _dynamic_schema(hub_app, cap_id)
        if schema is None:
            log.warning(
                "[mcp-facade] capability %r 가 OpenAPI 에 없음 — facade skip "
                "(generic capability_invoke 로는 여전히 호출 가능)",
                cap_id,
            )
            continue
        doc = (
            f"{description}\n\n"
            f"`{cap_id}` capability 전용 함수(facade). 동작·인자·응답 봉투는 "
            f"`capability_invoke(name=\"{cap_id}\", params=...)` 와 동일하며 "
            f"`capability_describe` 선행이 불필요하다. 인자 스키마는 hive "
            f"capability 레지스트리에서 동적 생성된다(정본=live)."
        ).strip()
        tools.append(
            Tool(
                fn=_make_facade(invoke_internal, cap_id),
                name=cap_id,
                title=None,
                description=doc,
                parameters=schema,
                fn_metadata=FuncMetadata(arg_model=_PassthroughArgs),
                is_async=True,
                context_kwarg="ctx",
                annotations=None,
            )
        )
    return tools


def register_facade_tools(mcp, hub_app, invoke_internal) -> list[str]:
    """생성한 facade Tool 을 FastMCP tool manager 에 등록.

    generic 메타툴(capability_list/describe/invoke)은 건드리지 않는다 —
    long-tail 경로 무변경. 등록한 capability id 목록 반환.
    """
    registered: list[str] = []
    for tool in build_facade_tools(hub_app, invoke_internal):
        mcp._tool_manager._tools[tool.name] = tool
        registered.append(tool.name)
    log.info(
        "[mcp-facade] 전용 함수 %d개 동적 등록 (레지스트리 기반, 정적 0): %s",
        len(registered),
        ", ".join(registered),
    )
    return registered
