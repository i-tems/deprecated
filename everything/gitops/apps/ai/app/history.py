"""Conversation history — per-user JSON file storage (multi-turn).

A conversation is a list of alternating turns:
  {id, title, turns: [{role, content, cost_usd?, duration_ms?}], created_at, updated_at}

Legacy single-shot entries ({prompt, response}) are normalized to a 2-turn
conversation on read, so old history keeps rendering.
"""
import json
import re
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

HISTORY_ROOT = Path("/data/history")
_lock = threading.Lock()

_CID_RE = re.compile(r"^[0-9a-f]{1,32}$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def is_valid_id(cid: str) -> bool:
    return bool(cid) and bool(_CID_RE.match(cid))


def _user_dir(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    d = HISTORY_ROOT / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize(data: dict) -> dict:
    """Return a conversation dict that always has a `turns` list."""
    if isinstance(data.get("turns"), list):
        return data
    # Legacy {prompt, response} shape → 2 turns.
    turns = []
    if data.get("prompt"):
        turns.append({"role": "user", "content": data.get("prompt", "")})
    if data.get("response"):
        turns.append({
            "role": "assistant",
            "content": data.get("response", ""),
            "cost_usd": data.get("cost_usd"),
            "duration_ms": data.get("duration_ms"),
        })
    data["turns"] = turns
    data.setdefault("updated_at", data.get("created_at", ""))
    return data


def append(
    email: str,
    cid: Optional[str],
    user_text: str,
    assistant_text: str,
    cost_usd: Optional[float] = None,
    duration_ms: Optional[int] = None,
    session_id: Optional[str] = None,
) -> str:
    """Append a (user, assistant) turn pair to conversation `cid`.

    Creates the conversation if `cid` is falsy/invalid or the file is missing.
    `session_id` is the claude session UUID for this conversation; it is
    persisted (and refreshed each turn) so later turns can `--resume` it.
    Returns the conversation id actually written.
    """
    if not is_valid_id(cid or ""):
        cid = new_id()
    path = _user_dir(email) / f"{cid}.json"
    with _lock:
        conv = None
        if path.exists():
            try:
                conv = _normalize(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                conv = None
        if conv is None:
            conv = {
                "id": cid,
                "title": user_text.strip().split("\n")[0][:80] or "(제목 없음)",
                "turns": [],
                "created_at": _now(),
                "updated_at": _now(),
            }
        conv["turns"].append({"role": "user", "content": user_text})
        conv["turns"].append({
            "role": "assistant",
            "content": assistant_text,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
        })
        if session_id:
            conv["session_id"] = session_id
        conv["updated_at"] = _now()
        if not conv.get("title"):
            conv["title"] = user_text.strip().split("\n")[0][:80] or "(제목 없음)"
        path.write_text(
            json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return cid


def list_all(email: str) -> list[dict]:
    """Return conversation list (id, title, updated_at), newest first."""
    d = _user_dir(email)
    items = []
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ts = data.get("updated_at") or data.get("created_at", "")
            items.append({
                "id": data["id"],
                "title": data.get("title", ""),
                "updated_at": ts,
                "created_at": data.get("created_at", ts),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return items


def get(email: str, cid: str) -> Optional[dict]:
    """Return full normalized conversation by ID."""
    if not is_valid_id(cid):
        return None
    path = _user_dir(email) / f"{cid}.json"
    if not path.exists():
        return None
    try:
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def delete(email: str, cid: str) -> bool:
    """Delete a conversation. Returns True if found."""
    if not is_valid_id(cid):
        return False
    path = _user_dir(email) / f"{cid}.json"
    if path.exists():
        path.unlink()
        return True
    return False
