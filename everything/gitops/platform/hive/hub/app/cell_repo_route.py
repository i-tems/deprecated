"""cell repo (i-tems/cell-*) push → `cell.json` 의 `subscriptions` 동기화.

흐름 (현재 hub 의 이중-webhook 구조 활용):
  1. GitHub merge → `cell.github_push` → Gitea mirror-sync API 트리거 (큐 등록만).
  2. Gitea 가 mirror fetch 후 자기 push webhook 발사 → `deployment.notify_push`.
  3. 본 라우트 매치 → mirror 가 이미 새 commit 반영된 시점이므로 polling 없이
     Gitea contents API 로 `cell.json` 즉시 fetch → `cells_repo.upsert`.

  이전 구현은 `cell.github_push` 핸들러 내부에서 `raw.githubusercontent.com` 으로
  직접 fetch 했으나 cell repo 가 private 이라 항상 401→404 마스킹으로 silent skip
  됐다. Gitea admin 토큰은 hub 가 이미 보유(`HUB_GITEA_ADMIN_TOKEN`) — private
  도 읽힌다.

  본 라우트는 두 번째 webhook (`deployment.notify_push`) 도착 후 동작하므로
  mirror sync 지연(검증상 1~5초) 와 race 없음. mirror_interval 30m 가 polling
  안전망. `hive_repo_route` 와 같은 self-register 패턴.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import urllib.request

from . import git_push_router
from .storage import cells_repo

log = logging.getLogger("hub.cell_repo_route")

_DEFAULT_BRANCHES = {"main", "master"}


def _find_cell_by_repo(repo_url: str) -> dict | None:
    """notify_push payload 의 repo_url(Gitea mirror) ↔ cell.repo_url(GitHub)
    동치 매칭. `git_push_router.repo_key` (basename 정규화) 그대로 사용."""
    key = git_push_router.repo_key(repo_url)
    for cell in cells_repo.list_all():
        if git_push_router.repo_key(cell.get("repo_url") or "") == key:
            return cell
    return None


def _match_cell_repo(repo_url: str, branch: str) -> bool:
    if branch not in _DEFAULT_BRANCHES:
        return False
    return _find_cell_by_repo(repo_url) is not None


def _owner_repo(repo_url: str) -> tuple[str, str] | None:
    """`https://github.com/i-tems/cell-items.git` → `('i-tems', 'cell-items')`."""
    s = (repo_url or "").strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    parts = s.rsplit("/", 2)
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def _fetch_cell_json(owner: str, repo: str, ref: str) -> dict:
    """Gitea contents API 로 `cell.json` fetch (private repo 도 admin 토큰으로 읽힘).
    Gitea mirror 가 webhook 발사 시점에 이미 새 commit 반영 상태라 polling 불필요."""
    token = os.environ.get("HUB_GITEA_ADMIN_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HUB_GITEA_ADMIN_TOKEN 미설정")
    base = os.environ.get(
        "HUB_GITEA_INTERNAL_URL", "http://gitea-http.gitea.svc:3000",
    ).rstrip("/")
    api_url = f"{base}/api/v1/repos/{owner}/{repo}/contents/cell.json?ref={ref}"
    req = urllib.request.Request(api_url, headers={"Authorization": f"token {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content_b64 = body.get("content") or ""
    if not content_b64:
        raise RuntimeError("contents.content 비어 있음 (cell.json 부재?)")
    return json.loads(base64.b64decode(content_b64).decode("utf-8"))


async def _handle_cell_push(repo_url: str, branch: str, sha: str) -> None:
    cell = _find_cell_by_repo(repo_url)
    if cell is None:
        # match 직후 cell 삭제 race — 매우 드물지만 silent ignore.
        log.warning("[cell-repo] cell 미매칭 (match 직후 삭제 race?): repo=%s", repo_url)
        return
    parsed = _owner_repo(cell.get("repo_url") or repo_url)
    if parsed is None:
        log.warning("[cell-repo] owner/repo 파싱 실패: %s", repo_url)
        return
    owner, repo = parsed
    try:
        cell_json = await asyncio.to_thread(_fetch_cell_json, owner, repo, branch)
    except Exception as exc:  # noqa: BLE001
        log.warning("[cell-repo] cell.json fetch 실패 %s/%s: %s",
                    owner, repo, f"{type(exc).__name__}: {exc}")
        return
    subs_raw = cell_json.get("subscriptions") or []
    subs = [str(s) for s in subs_raw if isinstance(s, str)] if isinstance(subs_raw, list) else []
    config = cell.get("config") or {}
    config["subscriptions"] = subs
    cell["config"] = config
    cells_repo.upsert(cell)
    log.info("[cell-repo] %s/%s -> cell_id=%s subscriptions=%s",
             owner, repo, cell.get("cell_id"), subs)


git_push_router.register("cell-repo", _match_cell_repo, _handle_cell_push)
