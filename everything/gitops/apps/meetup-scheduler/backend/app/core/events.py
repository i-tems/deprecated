"""
NDJSON event log writer for meetup-scheduler.

Design spec: data/cells/items/projects/ITEMS-PROJECT-14/measurement_design.md
- Domain file: {DATA_DIR}/events/yyyy-mm-dd.ndjson
- Request file: {DATA_DIR}/events/yyyy-mm-dd.requests.ndjson
- All writes are O_APPEND + asyncio.Lock (single-node safe).
- emit() and emit_request() are fully isolated — failure never affects callers.
- EVENT_HASH_SALT env missing → warn once, all emits become no-ops.
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("meetup.events")

_lock = asyncio.Lock()
_salt: str | None = None
_salt_warned = False
_enabled = True


def _get_salt() -> str | None:
    global _salt, _salt_warned, _enabled
    if _salt is not None:
        return _salt
    raw = os.environ.get("EVENT_HASH_SALT", "")
    if not raw:
        if not _salt_warned:
            logger.warning("EVENT_HASH_SALT not set — event logging disabled")
            _salt_warned = True
        _enabled = False
        return None
    _salt = raw
    _enabled = True
    return _salt


def hash_id(value: str | None) -> str | None:
    if value is None:
        return None
    salt = _get_salt()
    if salt is None:
        return None
    return hashlib.sha256((salt + value).encode()).hexdigest()[:16]


def hash_user_id(uid: str | None) -> str | None:
    return hash_id(uid)


def hash_session_id(sid: str | None) -> str | None:
    return hash_id(sid)


def hash_group_id(gid: str | None) -> str | None:
    return hash_id(gid)


def _envelope(event: str, props: dict, user_id: str | None = None, session_id: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "event": event,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
        "user_id_hash": hash_user_id(user_id),
        "session_id_hash": hash_session_id(session_id),
        "props": props,
    }


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write_line(path_str: str, line: str) -> None:
    import fcntl
    with open(path_str, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def emit(
    event: str,
    props: dict,
    user_id: str | None = None,
    session_id: str | None = None,
) -> None:
    try:
        if not _get_salt():
            return
        from app.core.storage import DATA_DIR
        events_dir = DATA_DIR / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        path = events_dir / f"{_today_utc()}.ndjson"
        envelope = _envelope(event, props, user_id, session_id)
        _write_line(str(path), json.dumps(envelope, ensure_ascii=False))
    except Exception:
        logger.exception("event emit failed (isolated): event=%s", event)


def emit_request(
    event: str,
    props: dict,
) -> None:
    try:
        if not _get_salt():
            return
        from app.core.storage import DATA_DIR
        events_dir = DATA_DIR / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        path = events_dir / f"{_today_utc()}.requests.ndjson"
        envelope = {
            "schema_version": 1,
            "event": event,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
            "props": props,
        }
        _write_line(str(path), json.dumps(envelope, ensure_ascii=False))
    except Exception:
        logger.exception("request emit failed (isolated): event=%s", event)
