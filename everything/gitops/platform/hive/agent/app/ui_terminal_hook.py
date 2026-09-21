"""Claude Code `Stop` 훅 (hive-ui sandbox 터미널) → Langfuse.

사람이 hive-ui sandbox 터미널에서 직접 모는 claude 세션의 토큰·주의력을 자율 워커와
**같은 Langfuse** 로 적재한다 — LLM 사용량 단일 소스(워커/UI 가 두 곳으로 갈리지 않게).
워커가 SDK 래퍼(`runtime._LangfuseStream`)로 쓰는 trace 스키마를 그대로 맞춰
(`metadata.entity_id`/`entity_type`, `model:*` tag) 기존 ai_usage collector 가
무수정으로 흡수하고, `channel="ui_terminal"` 로 워커 trace 와 구분한다.

왜 turn 단위(Stop)인가: 세션 종료(SessionEnd) 1회 적재는 사람이 터미널을 안 닫으면
영영 안 뛰고, 열린 시간(open→close)을 주의력으로 쓰면 유휴가 부풀려진다. Stop 은 매
assistant turn 마다 발화하므로 turn 마다 delta 를 적재 → 안 닫아도·TTL 강제종료돼도
직전 turn 까지 남고, active_seconds 를 turn 간격(상한 적용)으로 계산해 유휴를 배제한다.

멱등: pod-로컬 cursor 파일에 마지막 적재 메시지 uuid 를 기록 → 같은 turn 재적재 방지.
turn 흐름을 절대 막지 않는다: stdin 을 먼저 읽고 fork 로 detach(부모 즉시 종료),
실패는 전부 삼키고 항상 exit 0.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

CHANNEL = "ui_terminal"
# active_seconds = 연속 turn 사이 간격의 합, 단 이 상한으로 클램프(유휴 배제).
GAP_CAP_SEC = float(os.environ.get("HIVE_TERM_GAP_CAP_SEC", "300"))
# cursor 저장 위치 — /work 는 pod-로컬 emptyDir(세션 수명 동안 유지, PVC 무오염).
CURSOR_DIR = Path(os.environ.get("HIVE_TERM_CURSOR_DIR", "/work/.hive_term"))

log = logging.getLogger("ui_terminal_hook")


def _assistant_turns(transcript_path: str) -> list[dict]:
    """transcript JSONL 에서 usage 있는 assistant 메시지를 순서대로 추출."""
    turns: list[dict] = []
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message") or {}
            usage = msg.get("usage") or {}
            if not usage:
                continue
            turns.append({
                "uuid": obj.get("uuid"),
                "ts": obj.get("timestamp"),
                "model": msg.get("model"),
                "usage": usage,
            })
    return turns


def _parse_ts(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _active_seconds(prev_ts: float | None, turns: list[dict]) -> float:
    """delta turn 들의 누적 active 초 — 연속 turn 간격을 GAP_CAP_SEC 로 클램프해 합산.

    prev_ts = 직전에 적재한 마지막 turn 의 timestamp (delta 의 시작 경계).
    """
    total = 0.0
    last = prev_ts
    for t in turns:
        cur = _parse_ts(t.get("ts"))
        if cur is not None and last is not None and cur >= last:
            total += min(cur - last, GAP_CAP_SEC)
        if cur is not None:
            last = cur
    return round(total, 3)


def _emit(turns: list[dict], prev_ts: float | None) -> None:
    """delta turn 합산 → Langfuse generation 1건 push (워커 스키마 미러)."""
    cell_id = os.environ.get("CELL_ID") or ""
    if not cell_id:
        return
    from .telemetry import get_langfuse_client

    lf = get_langfuse_client(cell_id, log)
    if lf is None:
        return

    owner = os.environ.get("HIVE_TERM_OWNER") or None
    entity_type = os.environ.get("HIVE_TERM_ENTITY_TYPE") or None
    entity_id = os.environ.get("HIVE_TERM_ENTITY_ID") or None
    session_id = os.environ.get("_HIVE_TERM_SESSION_ID") or None

    agg = {"input": 0, "output": 0, "cache_read_input": 0, "cache_creation_input": 0}
    model = None
    for t in turns:
        u = t["usage"]
        agg["input"] += int(u.get("input_tokens") or 0)
        agg["output"] += int(u.get("output_tokens") or 0)
        agg["cache_read_input"] += int(u.get("cache_read_input_tokens") or 0)
        agg["cache_creation_input"] += int(u.get("cache_creation_input_tokens") or 0)
        if t.get("model"):
            model = t["model"]

    active_sec = _active_seconds(prev_ts, turns)
    trace_name = f"{CHANNEL}/{entity_type or 'shell'}"
    tags = [f"cell:{cell_id}", f"channel:{CHANNEL}"]
    if model:
        tags.append(f"model:{model}")
    if entity_type:
        tags.append(f"entity:{entity_type}")

    from langfuse import propagate_attributes

    with propagate_attributes(
        session_id=session_id,
        user_id=owner,
        trace_name=trace_name,
        tags=tags,
    ):
        gen = lf.start_observation(
            as_type="generation",
            name=trace_name,
            model=model,
            metadata={
                "cell_id": cell_id,
                "entity_id": entity_id,
                "entity_type": entity_type,
                "session_type": CHANNEL,
                "channel": CHANNEL,
                "active_seconds": active_sec,
                "turns": len(turns),
            },
        )
    # 비용은 model+usage 로 Langfuse 가 자체 가격책정(daily metrics 와 동일 경로) —
    # cost_details 를 명시하지 않는다. 토큰만 정확히 싣는다.
    gen.update(usage_details=agg)
    gen.end()
    lf.flush()


def _run(hook_input: dict) -> None:
    transcript_path = hook_input.get("transcript_path")
    session_id = hook_input.get("session_id") or "unknown"
    if not transcript_path or not Path(transcript_path).is_file():
        return
    os.environ["_HIVE_TERM_SESSION_ID"] = session_id

    turns = _assistant_turns(transcript_path)
    if not turns:
        return

    CURSOR_DIR.mkdir(parents=True, exist_ok=True)
    cursor_file = CURSOR_DIR / f"{session_id}.json"
    last_uuid = None
    prev_ts = None
    if cursor_file.is_file():
        try:
            c = json.loads(cursor_file.read_text(encoding="utf-8"))
            last_uuid = c.get("last_uuid")
            prev_ts = c.get("last_ts")
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    if last_uuid is not None:
        idx = next((i for i, t in enumerate(turns) if t["uuid"] == last_uuid), None)
        new = turns[idx + 1:] if idx is not None else turns
    else:
        new = turns
    if not new:
        return

    _emit(new, _parse_ts(prev_ts) if isinstance(prev_ts, str) else prev_ts)

    cursor_file.write_text(
        json.dumps({"last_uuid": new[-1]["uuid"], "last_ts": new[-1]["ts"]}),
        encoding="utf-8",
    )


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return 0
    # turn 흐름을 막지 않도록 stdin 을 읽은 직후 detach — 부모는 즉시 종료해
    # claude 가 다음 prompt 로 넘어가고, 자식이 Langfuse push(네트워크)를 떠안는다.
    try:
        if os.fork() > 0:
            return 0
        # 자식: claude 의 프로세스 그룹에서 분리 — 훅 종료 후 그룹 시그널에 안 죽고
        # Langfuse push(네트워크)를 끝까지 마친다.
        os.setsid()
    except OSError:
        pass  # fork 불가 환경이면 동기 실행으로 폴백.
    try:
        hook_input = json.loads(raw) if raw.strip() else {}
        _run(hook_input)
    except Exception as exc:  # noqa: BLE001 — 훅은 어떤 경우에도 조용히 죽는다.
        log.warning(f"ui_terminal_hook 실패: {exc}")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
