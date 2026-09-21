"""web capability — 클러스터 egress 로 외부 웹 원본을 받아 NFS 에 저장.

Anthropic 경유 WebFetch 가 403 으로 막히는 사이트(예: namu.wiki)를 hive 클러스터
egress(차단 안 됨)로 받아 /data/shared/web-cache 에 원본 그대로 저장하고 경로를 반환한다.
파싱은 호출자(워커)가 같은 NFS(hive-data PVC, RWX)를 읽어 직접 한다 — 이 서비스는
transport + 저장만 책임진다.

엔드포인트:
- web.fetch(url, max_preview) — 원본 GET → 파일 저장 → {path, bytes, sha256, preview, ...}

SSRF 가드: 외부 웹은 전부 허용하되 내부망/사설/링크로컬 주소는 거부한다 (호스트명 suffix +
DNS 해석된 IP 검사). 리다이렉트는 수동으로 따라가며 매 hop 을 재검증한다.
"""

import asyncio
import hashlib
import ipaddress
import logging
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse, create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("web")

# ── Config ───────────────────────────────────────────────────────────────────

CACHE_DIR = Path(os.environ.get("WEB_CACHE_DIR", "/data/shared/web-cache"))
CACHE_TTL_DAYS = float(os.environ.get("WEB_CACHE_TTL_DAYS", "7"))
MAX_BYTES = int(os.environ.get("WEB_MAX_BYTES", str(16 * 1024 * 1024)))
HTTP_TIMEOUT_S = float(os.environ.get("HTTP_TIMEOUT_S", "25"))
MAX_REDIRECTS = int(os.environ.get("WEB_MAX_REDIRECTS", "5"))
USER_AGENT = os.environ.get(
    "WEB_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)
# 내부망 차단(SSRF). 사설/링크로컬/내부 도메인만 거부, 외부 웹은 전부 허용.
BLOCKED_HOST_SUFFIXES = (".svc", ".cluster.local", ".local", ".lab.i-tems.com")

app = create_app(
    service_id="web",
    version="0.1.0",
    description=(
        "클러스터 egress 로 외부 웹 원본을 받아 NFS(/data/shared)에 저장. 파싱은 호출자. "
        "WebFetch 가 막히는 사이트(namu.wiki 등)용."
    ),
)


# ── Models ───────────────────────────────────────────────────────────────────


class FetchRequest(BaseModel):
    url: str = Field(..., description="가져올 외부 URL (http/https).")
    max_preview: int = Field(
        default=4096,
        description="반환에 인라인으로 담을 앞부분 바이트 수(UTF-8 디코드). 0=미포함.",
    )


# ── SSRF guard ───────────────────────────────────────────────────────────────


def _assert_public_host(host: str) -> None:
    """host 가 내부망/사설/링크로컬이면 ValueError. DNS rebinding 대비 해석 IP 도 검사."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        raise ValueError("empty host")
    if h == "localhost" or h.endswith(BLOCKED_HOST_SUFFIXES):
        raise ValueError(f"internal host blocked: {h}")
    try:
        infos = socket.getaddrinfo(h, None)
    except socket.gaierror as e:
        raise ValueError(f"dns resolution failed: {h} ({e})")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"non-public address blocked: {h} -> {ip}")


# ── Fetch ────────────────────────────────────────────────────────────────────


async def _fetch_raw(url: str) -> httpx.Response:
    """리다이렉트를 수동으로 따라가며 매 hop 의 host 를 SSRF 검증 후 GET."""
    current = url
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_S,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https"):
                raise ValueError(f"unsupported scheme: {parsed.scheme}")
            await asyncio.to_thread(_assert_public_host, parsed.hostname or "")
            resp = await client.get(current)
            if resp.is_redirect and resp.next_request is not None:
                current = str(resp.next_request.url)
                continue
            resp.raise_for_status()
            return resp
        raise ValueError("too many redirects")


def _ext_for(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "html" in ct:
        return ".html"
    if "json" in ct:
        return ".json"
    if "xml" in ct:
        return ".xml"
    if "text/" in ct:
        return ".txt"
    return ".bin"


def _sweep_expired() -> None:
    """TTL 지난 캐시 파일 삭제 (best-effort)."""
    if CACHE_TTL_DAYS <= 0 or not CACHE_DIR.exists():
        return
    cutoff = time.time() - CACHE_TTL_DAYS * 86400
    for p in CACHE_DIR.rglob("*"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


# ── Endpoint ─────────────────────────────────────────────────────────────────


@app.post(
    "/web.fetch",
    summary="외부 웹 원본 fetch → NFS 저장",
    description=(
        "클러스터 egress 로 외부 URL 원본을 받아 /data/shared/web-cache 에 저장하고 "
        "경로·메타·preview 를 반환한다. 파싱은 호출자(워커)가 같은 NFS 를 읽어 직접 한다. "
        "내부망/사설 주소는 거부(SSRF 가드)."
    ),
    openapi_extra={"x-side-effects": "external", "x-requires-approval": False},
)
async def web_fetch(req: FetchRequest) -> CapabilityResponse:
    url = (req.url or "").strip()
    if not url:
        return CapabilityResponse(
            status="error", error_code="invalid_request", message="url is required.",
        )
    try:
        resp = await _fetch_raw(url)
    except ValueError as e:
        return CapabilityResponse(
            status="error", error_code="blocked_or_invalid", message=str(e),
        )
    except httpx.HTTPStatusError as e:
        return CapabilityResponse(
            status="error", error_code="http_error",
            message=f"{e.response.status_code} {e.request.url}",
        )
    except httpx.HTTPError as e:
        return CapabilityResponse(
            status="error", error_code="fetch_failed", message=str(e),
        )

    body = resp.content
    if len(body) > MAX_BYTES:
        return CapabilityResponse(
            status="error", error_code="too_large",
            message=f"{len(body)} bytes > limit {MAX_BYTES}",
        )

    sha = hashlib.sha256(body).hexdigest()
    ctype = resp.headers.get("content-type", "")
    host = (urlparse(str(resp.url)).hostname or "unknown").lower()
    dest = CACHE_DIR / host / f"{sha}{_ext_for(ctype)}"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    except OSError as e:
        return CapabilityResponse(
            status="error", error_code="store_failed", message=str(e),
        )

    _sweep_expired()

    preview = ""
    if req.max_preview > 0:
        preview = body[: req.max_preview].decode("utf-8", errors="replace")

    return CapabilityResponse(status="ok", data={
        "path": str(dest),
        "bytes": len(body),
        "sha256": sha,
        "content_type": ctype,
        "final_url": str(resp.url),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "preview": preview,
    })
