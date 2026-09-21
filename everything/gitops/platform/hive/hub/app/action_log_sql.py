"""Hub용 ActionLog 미들웨어 — storage.append_jsonl 호출로 audit_actions 테이블에 기록.

storage 레이어의 path dispatch 가 동일 path 를 SQL 로 라우팅하므로 호출자는
date-rotated path 만 넘기면 된다 (디스크에는 쓰지 않음).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import anyio

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .storage.idgen import new_entity_id

log = logging.getLogger("hub.audit")


class SqlActionLogMiddleware(BaseHTTPMiddleware):
    """모든 capability 호출(.list/.get 등 SKIP 대상 제외) 을 audit_actions 에 INSERT."""

    # /sse.subscribe 는 무한 스트림 — body_iterator 를 드레인하면 hang 되므로
    # 반드시 skip (heartbeat 와 동일 사유). 게다가 long-poll 성격이라 action log
    # 대상도 아니다.
    # /worker.activity_push 는 AI activity 고빈도 relay — heartbeat 와 같은
    # 사유로 action log 대상 아님 (noise·DB 비대 방지).
    SKIP_PATHS = {"/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/worker.heartbeat", "/worker.clear", "/worker.activity_push", "/sse.subscribe"}
    SKIP_SUFFIXES = {".list", ".get"}

    def __init__(self, app, *, log_dir: Path):
        super().__init__(app)
        self.log_dir = log_dir

    def _today_log_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.log_dir / f"{today}.jsonl"

    def _persist_audit(self, cell_id, meta: dict) -> None:
        """blocking 구간(action_id DB 카운터 + audit SQL INSERT). threadpool 에서 실행.

        action_id 발급 실패 시 fallback id 로 degrade, append 실패는 ERROR 로그
        (silent drop 은 컴플라이언스 위험) — 둘 다 best-effort, 본 요청 응답은 막지 않는다.
        """
        try:
            action_id, _seq = new_entity_id(cell_id, "action")
        except Exception as exc:
            import uuid as _uuid
            scope = (cell_id or "GLOBAL").upper()
            action_id = f"{scope}-ACTION-ERR-{_uuid.uuid4().hex[:12]}"
            log.error("[audit] action_id 발급 실패 — fallback %s: %s", action_id, exc)
        entry = {"action_id": action_id, **meta}
        from .storage import append_jsonl
        try:
            append_jsonl(self._today_log_path(), entry)
        except Exception as exc:
            log.error(
                "[audit] append failed action_id=%s capability=%s principal=%s: %s",
                entry["action_id"], entry["capability_id"],
                entry.get("principal_id"), exc,
                exc_info=True,
            )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)
        if any(request.url.path.endswith(s) for s in self.SKIP_SUFFIXES):
            return await call_next(request)

        start = time.time()

        body = await request.body()
        try:
            input_data = json.loads(body) if body else None
        except json.JSONDecodeError:
            input_data = None

        response = await call_next(request)

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        try:
            output_data = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            output_data = None

        duration_ms = int((time.time() - start) * 1000)

        source = request.headers.get("X-Source", "internal")

        output_ref = None
        if output_data and isinstance(output_data, dict):
            result_status = output_data.get("status")
            data = output_data.get("data")
            if isinstance(data, dict):
                ref_id = next(
                    (data[k] for k in data if k.endswith("_id") and isinstance(data[k], str)),
                    None,
                )
                output_ref = {"status": result_status, "entity_id": ref_id}
            else:
                output_ref = {"status": result_status}
            if output_data.get("error_code"):
                output_ref["error_code"] = output_data["error_code"]
                output_ref["message"] = output_data.get("message")

        cell_id = getattr(request.state, "cell_id", None)
        principal = getattr(request.state, "principal", None)
        session_id = getattr(request.state, "session_id", None) or request.headers.get("X-Session-Id")
        # issue_id는 principal claim에서만 가져옴 (X-Issue-Id 헤더 의존 제거).
        issue_id = principal.issue_id if principal else None

        # action_id 발급(DB 카운터)과 audit append(SQL INSERT)는 blocking IO 다.
        # 단일 이벤트루프에서 직접 실행하면 동시 요청 버스트 때 /health 까지 굶어
        # readiness flap·hang 을 유발한다 (INFRA-ISSUE-276). action_id 미포함 메타만
        # 루프에서 싸게 모으고, blocking 구간은 threadpool 로 오프로드한다.
        meta = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "capability_id": request.url.path.lstrip("/"),
            "cell_id": cell_id,
            "issue_id": issue_id,
            "source": source,
            "user": getattr(request.state, "user_email", None),
            "principal_id": principal.id if principal else None,
            "principal_type": principal.type if principal else None,
            "session_id": session_id,
            "session_type": principal.session_type if principal else None,
            "trace_id": getattr(request.state, "trace_id", None),
            "span_id": getattr(request.state, "span_id", None),
            "parent_span_id": getattr(request.state, "parent_span_id", None),
            "input": input_data,
            "output_ref": output_ref,
            "status": "ok" if response.status_code < 400 else "error",
            "duration_ms": duration_ms,
            "approval_ref": request.headers.get("X-Approval-Ref"),
        }
        await anyio.to_thread.run_sync(self._persist_audit, cell_id, meta)

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
