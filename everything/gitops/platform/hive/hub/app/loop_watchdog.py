"""이벤트루프 stall watchdog — 진단 전용 (INFRA-ISSUE-277).

데몬 스레드가 이벤트루프 heartbeat 를 감시하다 STALL_SECS 이상 무응답이면
faulthandler 로 전체 스레드 스택을 stderr 에 덤프한다 → hang 시 정확히 어느
프레임에서 루프가 멈췄는지 로그로 확보. 읽기 전용 — 런타임 동작 변경 없음.

heartbeat 는 이벤트루프 위 async task 가 1초마다 갱신한다. 루프가 sync 블로킹/
데드락으로 멈추면 heartbeat 가 갱신되지 못해 watchdog 이 stall 을 감지한다.
"""
from __future__ import annotations

import asyncio
import faulthandler
import os
import sys
import threading
import time

STALL_SECS = float(os.environ.get("HUB_LOOP_STALL_DUMP_SECS", "10"))
_DUMP_COOLDOWN = float(os.environ.get("HUB_LOOP_STALL_DUMP_COOLDOWN", "60"))

_last_beat = time.monotonic()


async def heartbeat() -> None:
    """이벤트루프 위에서 1초마다 _last_beat 갱신 (lifespan 에서 create_task)."""
    global _last_beat
    while True:
        _last_beat = time.monotonic()
        await asyncio.sleep(1)


def _watch() -> None:
    dumped_at = 0.0
    while True:
        time.sleep(2)
        stalled = time.monotonic() - _last_beat
        now = time.monotonic()
        if stalled >= STALL_SECS and (now - dumped_at) > _DUMP_COOLDOWN:
            sys.stderr.write(
                f"\n===== [loop-watchdog] EVENT LOOP STALLED ~{stalled:.0f}s "
                f"(INFRA-ISSUE-277) — all-thread tracebacks =====\n"
            )
            sys.stderr.flush()
            faulthandler.dump_traceback(all_threads=True)
            sys.stderr.flush()
            dumped_at = now


def start_watchdog() -> None:
    threading.Thread(target=_watch, name="loop-watchdog", daemon=True).start()
