"""Cell 통합 설정 reader.

cell repo 의 `cell.json` (정본) 이 워커 부팅 시 PVC `/data/cells/<cell>/cell.json` 으로
미러링된다. capability config + key + 기타 cell 설정이 한 파일에 모두 들어 있다:

    {
      "slack":    {"inbox_channel": "...", "bot_token": "..."},
      "google":   {"calendar_id": "primary", "credentials": {...}},
      "langfuse": {"host": "...", "public_key": "...", "secret_key": "...", "project_id": "..."},
      "repo_policies": {...}
    }
"""

from __future__ import annotations

import json
import logging

from .config import DATA_DIR

log = logging.getLogger("hub.cell_config")


def read(cell_id: str) -> dict:
    path = DATA_DIR / "cells" / cell_id / "cell.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        log.warning(f"cell.json parse 실패: {path}")
        return {}


def get(cell_id: str, key: str) -> dict:
    """top-level key 의 sub-dict (없으면 빈 dict)."""
    value = read(cell_id).get(key)
    return value if isinstance(value, dict) else {}
