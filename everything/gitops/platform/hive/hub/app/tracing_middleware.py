"""TracingMiddleware — 들어오는 traceparent 헤더를 파싱하거나 새 trace를 mint.

설정 후:
- request.state.trace_id, .span_id, .parent_span_id  (다른 미들웨어/핸들러가 사용)
- ContextVar 동기화  (emit_event 등 deeply nested 호출에서 인자 없이 참조)
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .tracing import (
    new_span_id, new_trace_id, parse_traceparent,
    set_trace_context, reset_trace_context,
)


# SSE 같은 무한 스트림은 trace context 를 set 한 뒤 곧장 finally 에서 reset
# 하는 이 미들웨어의 수명 모델과 맞지 않는다 (call_next 는 스트림 본문 전송
# 전에 반환 → reset 이 스트림 도중에 일어남). 게다가 BaseHTTPMiddleware 가
# 한 겹 더 쌓이면 핸들러의 request.is_disconnected() 신뢰성이 더 떨어진다.
# Auth/Cell/ActionLog/Metrics 형제 미들웨어와 동일하게 /sse.subscribe 를
# skip 한다 (sse.py docstring 의 exempt 목록은 이 미들웨어 도입 전 작성돼
# Tracing 이 누락돼 있었음 — 회귀).
SKIP_PATHS = {"/sse.subscribe"}


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        parsed = parse_traceparent(request.headers.get("traceparent"))
        if parsed is not None:
            trace_id, parent_span_id = parsed
        else:
            trace_id = new_trace_id()
            parent_span_id = None
        span_id = new_span_id()

        request.state.trace_id = trace_id
        request.state.span_id = span_id
        request.state.parent_span_id = parent_span_id
        tokens = set_trace_context(trace_id, span_id, parent_span_id)
        try:
            return await call_next(request)
        finally:
            reset_trace_context(tokens)
