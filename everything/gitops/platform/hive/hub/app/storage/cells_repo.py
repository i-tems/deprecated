"""cells 테이블 리포지토리 — entity-typed SQL API.

`cell.py` 가 이 모듈을 직접 import 한다 (path-shim 경유 안 함).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from ..db import get_engine

log = logging.getLogger("hub.cells")


def list_all() -> list[dict]:
    """삭제 안 된 모든 셀 (deleted=0)을 updated_at desc로."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT data FROM cells WHERE deleted=0 ORDER BY updated_at DESC"
        )).fetchall()
    return [_row_data(r) for r in rows]


def list_raw() -> list[dict]:
    """deleted 포함 모든 row. 마이그레이션·디버깅용."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT data FROM cells")).fetchall()
    return [_row_data(r) for r in rows]


def get(cell_id: str) -> dict | None:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT data FROM cells WHERE cell_id=:cid"),
            {"cid": cell_id},
        ).first()
    return _row_data(row) if row else None


def upsert(cell: dict) -> None:
    cid = cell.get("cell_id")
    if not cid:
        raise ValueError("cell_id required")
    payload = json.dumps(cell, ensure_ascii=False)
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO cells (cell_id, data) VALUES (:cid, :data) "
                "ON DUPLICATE KEY UPDATE data=VALUES(data)"
            ),
            {"cid": cid, "data": payload},
        )


def find(cell_id: str) -> tuple[list[dict], dict | None]:
    """기존 find_entity 호환 — (전체 list, 매칭 1건). cell.py 패턴 그대로."""
    all_cells = list_all()
    for c in all_cells:
        if c.get("cell_id") == cell_id:
            return all_cells, c
    return all_cells, None


def _row_data(row: Any) -> dict:
    raw = row[0] if row else None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        return json.loads(raw)
    return {}
