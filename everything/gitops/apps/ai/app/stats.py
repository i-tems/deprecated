"""Per-user usage stats, persisted as JSON."""
import json
import threading
from datetime import date
from pathlib import Path
from typing import Optional

STATS_FILE = Path("/data/_stats.json")
_lock = threading.Lock()
_EMPTY = {
    "cost": 0.0,
    "input": 0,
    "output": 0,
    "cache_write": 0,
    "cache_read": 0,
    "requests": 0,
}


def _zero() -> dict:
    return dict(_EMPTY)


def _load() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(STATS_FILE)


def record_usage(email: str, result: dict) -> None:
    usage = result.get("usage") or {}
    cost = float(result.get("cost") or 0)
    today = date.today().isoformat()
    delta = {
        "cost": cost,
        "input": int(usage.get("input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
        "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
        "requests": 1,
    }
    with _lock:
        data = _load()
        user = data.setdefault(email, {"total": _zero(), "daily": {}})
        d = user["daily"].setdefault(today, _zero())
        for tgt in (user["total"], d):
            for k, v in delta.items():
                tgt[k] = tgt.get(k, 0) + v
        _save(data)


def get_stats(email: str) -> dict:
    today = date.today().isoformat()
    with _lock:
        data = _load()
        user = data.get(email) or {"total": _zero(), "daily": {}}
        return {
            "today": user.get("daily", {}).get(today, _zero()),
            "total": user.get("total", _zero()),
        }
