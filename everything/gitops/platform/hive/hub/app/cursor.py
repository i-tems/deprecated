"""Opaque cursor pagination — Linear MCP 패턴.

list 응답에 ``next_cursor`` 를 같이 내려주면 호출자가 그대로 다음 호출에 넣어 안정적인
페이지네이션 가능. 현재 hive 의 list 핸들러는 storage 백엔드(SQL) 가 반환한 결과를
메모리에 전부 로드 후 정렬·필터하므로 cursor 는 단순히 base64(JSON({"offset": int}))
로 충분. 향후 sort-key 기반 cursor 로 교체해도 외부 호출자는 opaque 토큰만 보고 있어
호환된다.

offset 기반 한계: 호출 사이 새 record 가 들어오면 페이지가 살짝 어긋날 수 있다. 이건
agent 의 backfill 호출 시나리오 (단발성 페이징 + 짧은 시간) 에선 받아들일 수 있는 트레이드오프.
strict 안정성이 필요해지면 cursor 모양은 그대로 두고 인코딩 내용만 (sort_key, last_id) 로 바꾼다.
"""

from __future__ import annotations

import base64
import json
from typing import Any


def encode_cursor(payload: dict[str, Any]) -> str:
    """opaque cursor 토큰 발급. base64url(JSON). padding 제거."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token: str | None) -> dict[str, Any]:
    """cursor 토큰 → payload. 손상된 토큰은 빈 dict 로 폴백 (호출자는 처음부터)."""
    if not token:
        return {}
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}


def offset_page(items: list, *, offset: int, limit: int) -> tuple[list, str | None]:
    """list 를 offset/limit 으로 자르고 next_cursor 산출. 마지막 페이지면 None.

    호출 패턴:
        page, next_cursor = offset_page(items, offset=req.offset, limit=req.limit)
    """
    start = max(0, offset)
    end = start + max(1, limit)
    page = items[start:end]
    next_cursor: str | None = None
    if end < len(items):
        next_cursor = encode_cursor({"offset": end})
    return page, next_cursor


def resolve_offset(cursor: str | None, fallback_offset: int) -> int:
    """cursor 가 주어지면 그 안의 offset 사용, 없으면 명시 offset."""
    if cursor:
        return int(decode_cursor(cursor).get("offset", fallback_offset) or 0)
    return fallback_offset
