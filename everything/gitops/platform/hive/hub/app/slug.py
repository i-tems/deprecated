"""Cell·resource name 슬러그 헬퍼 — DNS-1123 안전.

소문자·숫자·하이픈만 남기고 잘라낸다. argocd_client 가 사용.
"""

from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^a-z0-9-]")


def slug(text: str, *, max_len: int = 30) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len].strip("-") or "x"
