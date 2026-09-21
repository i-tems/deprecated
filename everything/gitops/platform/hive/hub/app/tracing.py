"""W3C traceparent 기반 인과 사슬 추적.

모든 hub 요청은 trace_id/span_id/parent_span_id를 갖는다. 이를 audit_actions와
events에 기록하면 한 흐름(예: signal A → comment B → issue transition C)을
trace_id로 묶어 한 번에 복원할 수 있다.

ContextVar로 보관해 emit_event 같은 핸들러 내 호출에서도 별도 인자 없이 자동
참조되게 한다 (asyncio issue 단위 격리).

W3C traceparent 형식: `<version>-<trace_id>-<span_id>-<flags>`
- version: 00
- trace_id: 32 hex chars (16 bytes)
- span_id: 16 hex chars (8 bytes)  ← incoming caller의 span. hub는 이를 parent로 본다.
- flags: 2 hex chars (보통 01 = sampled)
"""

from __future__ import annotations

import secrets
from contextvars import ContextVar


_TRACE_ID: ContextVar[str | None] = ContextVar("hive_trace_id", default=None)
_SPAN_ID: ContextVar[str | None] = ContextVar("hive_span_id", default=None)
_PARENT_SPAN_ID: ContextVar[str | None] = ContextVar("hive_parent_span_id", default=None)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """traceparent 헤더를 (trace_id, span_id)로 파싱. 잘못된 형식이면 None."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace_id, span_id, _flags = parts
    if version != "00" or len(trace_id) != 32 or len(span_id) != 16:
        return None
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    try:
        int(trace_id, 16)
        int(span_id, 16)
    except ValueError:
        return None
    return trace_id, span_id


def format_traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


def set_trace_context(trace_id: str, span_id: str, parent_span_id: str | None):
    """ContextVar 3개를 set하고 reset용 token 튜플을 반환한다.

    호출자(middleware)는 finally에서 reset_trace_context(tokens)를 부른다.
    Starlette BaseHTTPMiddleware가 issue를 재사용하는 엣지 케이스에서
    이전 요청의 trace 컨텍스트가 다음 요청에 새는 것을 방지한다.
    """
    return (
        _TRACE_ID.set(trace_id),
        _SPAN_ID.set(span_id),
        _PARENT_SPAN_ID.set(parent_span_id),
    )


def reset_trace_context(tokens) -> None:
    t_trace, t_span, t_parent = tokens
    _TRACE_ID.reset(t_trace)
    _SPAN_ID.reset(t_span)
    _PARENT_SPAN_ID.reset(t_parent)


def get_trace_context() -> tuple[str | None, str | None, str | None]:
    return _TRACE_ID.get(), _SPAN_ID.get(), _PARENT_SPAN_ID.get()
