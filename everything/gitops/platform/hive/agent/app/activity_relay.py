"""Worker → hub AI activity relay (PR #146 stdout `[ai-activity]` 채널 대체).

`runtime.run_agent` 의 `relay` 콜백으로 text/tool_use/tool_result item 을 받아
in-memory buffer 에 모았다가 daemon thread 가 주기적으로 `worker.activity_push`
로 batch POST 한다. hub 가 세션별 ring buffer 에 적재 + `wake_bus.notify` →
UI 사이드바가 SSE 로 거의 실시간 표시 (Langfuse·kubectl 불요).

`HeartbeatThread` 와 같은 운영 계약: best-effort, 실패는 silent skip, worker
본 흐름을 절대 막지 않는다 (hub 일시 장애가 turn 을 죽이지 않게). relay 가 없는
경로(entity 식별 불가 등)는 아예 생성하지 않으면 `relay=None` 으로 no-op.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime, timezone

from .hub_client import HubClient

# flush 주기 (초). 너무 짧으면 hub POST 가 누적되고, 너무 길면 "실시간" 체감이
# 떨어진다. Langfuse partial flush(5s)보다 짧게 잡아 UI 가 더 잘게 차오르게 한다.
_FLUSH_INTERVAL_S = 1.0
# pending 이 이 수 이상이면 다음 tick 을 기다리지 않고 즉시 flush (긴 turn 대비).
_MAX_BATCH = 40
# 단일 item payload 절단 한계 (문자). hub ring buffer·SSE payload 비대 및
# 민감정보 과다 노출 방지. UI 는 요약 transcript 라 전체 본문이 필요 없다.
_TEXT_LIMIT = 4000
_TOOL_LIMIT = 2000


def _trunc(value, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        s = value
    else:
        try:
            s = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            s = str(value)
    if len(s) <= limit:
        return s
    return f"{s[:limit]}…(+{len(s) - limit} chars)"


class ActivityRelay:
    """text/tool_use/tool_result 를 buffer → hub batch push 하는 daemon relay."""

    def __init__(self, client: HubClient, *, entity_type: str, entity_id: str, logger):
        self._client = client
        self._entity_type = entity_type
        self._entity_id = entity_id
        self._log = logger
        self._buf: deque = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._seq = 0
        self._session_id: str | None = None
        self._consecutive_failures = 0
        self._thread = threading.Thread(
            target=self._run, name="hive-activity-relay", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def set_session_id(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._session_id = session_id

    def add(self, item: dict) -> None:
        """runtime.run_agent 의 relay 콜백. 절대 raise 하지 않는다 (turn 비차단)."""
        try:
            kind = item.get("kind")
            now = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._seq += 1
                rec = {"seq": self._seq, "ts": now, "kind": kind}
                if kind == "text":
                    rec["text"] = _trunc(item.get("text"), _TEXT_LIMIT)
                elif kind == "tool_use":
                    rec["tool"] = item.get("tool") or "?"
                    # tool_use_id — UI 가 tool_use↔tool_result 를 이름+추정이
                    # 아니라 정확히 페어링하는 키 (병렬·동일이름 호출 정합).
                    rec["tool_use_id"] = item.get("tool_use_id") or ""
                    rec["input"] = _trunc(item.get("input"), _TOOL_LIMIT)
                elif kind == "tool_result":
                    rec["tool"] = item.get("tool") or "?"
                    rec["tool_use_id"] = item.get("tool_use_id") or ""
                    rec["is_error"] = bool(item.get("is_error"))
                    rec["output"] = _trunc(item.get("output"), _TOOL_LIMIT)
                elif kind == "turn":
                    # 이 turn 의 트리거(주입 작업지시/델타). UI 가 압축
                    # 구분선으로 표시 + 펼치면 전문. 큰 엔티티 JSON 이라 절단.
                    rec["prompt"] = _trunc(item.get("prompt"), _TEXT_LIMIT)
                else:
                    return
                self._buf.append(rec)
                over = len(self._buf) >= _MAX_BATCH
            if over:
                self._wake.set()
        except Exception:
            pass

    def _drain(self) -> list[dict]:
        with self._lock:
            if not self._buf:
                return []
            items = list(self._buf)
            self._buf.clear()
            return items

    def _push(self, items: list[dict]) -> None:
        with self._lock:
            sid = self._session_id
        payload = {
            "entity_type": self._entity_type,
            "entity_id": self._entity_id,
            "session_id": sid,
            "events": items,
        }
        try:
            self._client.api("worker.activity_push", payload, timeout=5)
            if self._consecutive_failures:
                self._consecutive_failures = 0
        except Exception as e:
            self._consecutive_failures += 1
            # 운영 가시성: 연속 실패가 누적되면 한 번 warning (이후 같은 주기마다).
            n = self._consecutive_failures
            if n == 6 or (n > 6 and n % 6 == 0):
                self._log.warning(
                    f"[activity-relay] {n}회 연속 push 실패 — UI live 패널이 멈춰 보일 수 있음 (err={e})"
                )
            else:
                self._log.debug(f"[activity-relay] push 실패 (#{n}): {e}")

    def _run(self) -> None:
        while not self._stop.is_set():
            # _MAX_BATCH 도달 시 즉시, 아니면 _FLUSH_INTERVAL_S 마다.
            self._wake.wait(_FLUSH_INTERVAL_S)
            self._wake.clear()
            items = self._drain()
            if items:
                self._push(items)

    def stop(self) -> None:
        """남은 buffer 를 마지막으로 한 번 flush 하고 thread 종료."""
        self._stop.set()
        self._wake.set()
        try:
            items = self._drain()
            if items:
                self._push(items)
        except Exception:
            pass
