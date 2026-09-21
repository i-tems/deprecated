"""셀별 Langfuse SDK 클라이언트 로딩.

worker 가 시작할 때 셀의 `cell.json` 의 langfuse 섹션을 읽어 Langfuse 클라이언트를
만들고 runtime.run_agent 종료 시점에 generation 을 기록한다. 설정이 없거나 SDK 초기화
실패 시 None 반환 (관측 비활성).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("HIVE_ROOT", "/data"))


def _load_langfuse_config(cell_id: str) -> dict | None:
    path = DATA_DIR / "cells" / cell_id / "cell.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    section = data.get("langfuse") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else None


def get_langfuse_client(cell_id: str, logger: logging.Logger) -> Any | None:
    """셀의 Langfuse 설정 → SDK 클라이언트. 미설정/실패 시 None."""
    config = _load_langfuse_config(cell_id)
    if not config:
        return None
    public_key = str(config.get("public_key") or "").strip()
    secret_key = str(config.get("secret_key") or "").strip()
    host = str(config.get("host") or "").strip().rstrip("/")
    if not (public_key and secret_key and host):
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning("langfuse SDK 미설치 — pyproject.toml 확인")
        return None
    try:
        client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        logger.info(f"Langfuse SDK 활성화: cell={cell_id} host={host}")
        return client
    except Exception as exc:
        logger.warning(f"Langfuse 클라이언트 초기화 실패: {exc}")
        return None
