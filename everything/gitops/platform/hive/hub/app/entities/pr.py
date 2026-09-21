"""GitHub PR 상태 derive-on-read.

PR 의 merge 상태는 GitHub 이 정본. hub 저장소에 복제하면 stale 이 불가피하므로,
UI 가 PR 카드 렌더링 시점에 이 capability 를 호출해 현재 상태를 얻는다.

- 입력: PR URL (https://github.com/{owner}/{repo}/pull/{N})
- 출력: {state, mergeable, fetched_at}
  - state: 'merged' | 'open' | 'draft' | 'closed'
  - mergeable: bool | None (open 일 때 의미. GitHub 가 계산 중이면 None)
- 캐시: in-memory TTL 30s, 키 = "owner/repo/N". GitHub rate-limit (5000/h authenticated) 보호.

worker 가 저장하던 `pr_urls[].merge_state` 필드는 폐기됨 — 이 capability 가 대체.
"""

import asyncio
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse

from ..gitea_mirror import parse_github_owner_repo

router = APIRouter()

_CACHE_TTL = 30.0
_CACHE_MAX = 500
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = asyncio.Lock()


def _parse_pr_url(url: str) -> tuple[str, str, int] | None:
    """https://github.com/{owner}/{repo}/pull/{N} → (owner, repo, N). 형식 안 맞으면 None."""
    or_pair = parse_github_owner_repo(url)
    if not or_pair:
        return None
    owner, repo = or_pair
    s = (url or "").rstrip("/")
    if "/pull/" not in s:
        return None
    tail = s.split("/pull/", 1)[1]
    num_str = tail.split("/", 1)[0]
    try:
        return owner, repo, int(num_str)
    except ValueError:
        return None


def _derive_state(gh: dict) -> dict:
    if gh.get("merged"):
        return {"state": "merged", "mergeable": None}
    if gh.get("state") == "closed":
        return {"state": "closed", "mergeable": None}
    if gh.get("draft"):
        return {"state": "draft", "mergeable": gh.get("mergeable")}
    return {"state": "open", "mergeable": gh.get("mergeable")}


class PrStatusRequest(BaseModel):
    url: str


@router.post("/pr.status")
async def pr_status(req: PrStatusRequest, request: Request) -> CapabilityResponse:
    """GitHub PR URL 의 현재 상태를 derive-on-read (30s in-memory cache)."""
    parsed = _parse_pr_url(req.url)
    if not parsed:
        return CapabilityResponse(
            status="error", error_code="invalid_url",
            message=f"PR URL 형식이 아님 (https://github.com/owner/repo/pull/N 필요): {req.url}",
        )
    owner, repo, num = parsed
    key = f"{owner}/{repo}/{num}"

    now = time.time()
    async with _cache_lock:
        entry = _cache.get(key)
        if entry and (now - entry[0]) < _CACHE_TTL:
            return CapabilityResponse(status="ok", data=entry[1])

    # hub pod 의 정본 env 명은 `HIVE_REPO_TOKEN` (manifests/deployment.yaml 매핑).
    # `GITHUB_TOKEN` 은 다른 환경(로컬 테스트 등) fallback.
    token = os.environ.get("HIVE_REPO_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return CapabilityResponse(
            status="error", error_code="no_token",
            message="HIVE_REPO_TOKEN(또는 GITHUB_TOKEN) 미설정 — PR 상태 조회 불가",
        )

    api = f"https://api.github.com/repos/{owner}/{repo}/pulls/{num}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(api, headers=headers)
    except httpx.HTTPError as exc:
        return CapabilityResponse(
            status="error", error_code="upstream_failure",
            message=f"GitHub API 호출 실패: {exc}",
        )

    if r.status_code == 404:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"PR not found: {owner}/{repo}#{num}",
        )
    if r.status_code >= 400:
        return CapabilityResponse(
            status="error", error_code="upstream_failure",
            message=f"GitHub API HTTP {r.status_code}: {r.text[:200]}",
        )

    data = _derive_state(r.json())
    data["fetched_at"] = datetime.now(timezone.utc).isoformat()

    async with _cache_lock:
        _cache[key] = (now, data)
        if len(_cache) > _CACHE_MAX:
            oldest_key = min(_cache.items(), key=lambda kv: kv[1][0])[0]
            _cache.pop(oldest_key, None)

    return CapabilityResponse(status="ok", data=data)
