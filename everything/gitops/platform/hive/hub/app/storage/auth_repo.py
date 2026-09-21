"""auth_login_log 리포지토리."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from uuid_utils import uuid7

from ..db import get_engine

log = logging.getLogger("hub.auth_repo")


def record_login(*, email: str, name: str, ip: str, user_agent: str, success: bool, reason: str | None, ts: str) -> None:
    record = {
        "ts": ts,
        "email": email,
        "name": name,
        "ip": ip,
        "user_agent": user_agent,
        "success": success,
    }
    if reason:
        record["reason"] = reason
    payload = json.dumps(record, ensure_ascii=False)
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text("INSERT INTO auth_login_log (login_id, data) VALUES (:lid, :data)"),
            {"lid": str(uuid7()), "data": payload},
        )


def list_recent(limit: int = 100) -> list[dict]:
    """최신순으로 최대 limit건."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT data FROM auth_login_log ORDER BY ts DESC LIMIT :lim"),
            {"lim": limit},
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict:
    raw = row[0] if row else None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        return json.loads(raw)
    return {}
