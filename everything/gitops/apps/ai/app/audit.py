"""Append-only JSON-Lines audit log of every /api/ask request."""
import json
import threading
from datetime import datetime
from pathlib import Path

AUDIT_FILE = Path("/data/_audit.jsonl")
_lock = threading.Lock()


def record(entry: dict) -> None:
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    full = {"ts": datetime.now().isoformat(timespec="seconds"), **entry}
    line = json.dumps(full, ensure_ascii=False) + "\n"
    with _lock:
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
