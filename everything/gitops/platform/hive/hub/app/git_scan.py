"""Cell repo space artifact scan via Gitea API.

Project/Issue 의 cell repo 산출물 디렉토리 (`data/cells/{cell}/{type}s/{id}/`) 를
Gitea mirror 의 recursive tree API 로 스캔해 `Artifact` 리스트로 반환한다.
`issue.get` / `project.get` 응답의 derived `artifacts` 필드 소스.

resources(사람·worker 가 직접 등록하는 외부 리소스) 와 분리된 채널.
산출물은 git 정본 1곳 (`data/cells/{cell}/{type}s/{id}/`) 에 commit 되고 hub 가 매번
스캔해 노출하므로 PR 머지 후 link rot · cancelled issue stale URL ·
Project↔Issue 중복 등록 문제가 발생하지 않는다.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Literal

from .gitea_mirror import GITEA_INTERNAL_URL, _gitea_api_owner_repo, _gitea_token
from .storage import cells_repo

log = logging.getLogger("hub.git_scan")

DEFAULT_BRANCH = "main"
_TIMEOUT_SECONDS = 10
_MAX_PAGES = 100


def scan_artifacts(
    cell_id: str,
    entity_type: Literal["project", "issue"],
    entity_id: str,
    branch: str = DEFAULT_BRANCH,
) -> list[dict]:
    """cell repo `data/cells/{cell}/{type}s/{id}/` recursive tree → Artifact dict 리스트.

    실패(cell 없음·repo_url 없음·Gitea 응답 실패·디렉토리 없음)는 빈 리스트로
    graceful 반환. 호출자가 결과를 응답에 그대로 합쳐 노출하면 된다.
    """
    cell = cells_repo.get(cell_id)
    if not cell:
        return []
    repo_url = (cell.get("repo_url") or "").strip()
    or_path = _gitea_api_owner_repo(repo_url)
    if not or_path:
        return []
    prefix = f"data/cells/{cell_id}/{entity_type}s/{entity_id}/"
    items = _fetch_tree(or_path, branch)
    artifacts: list[dict] = []
    for item in items:
        if item.get("type") != "blob":
            continue
        path = item.get("path") or ""
        if not path.startswith(prefix):
            continue
        artifacts.append({
            "path": path,
            "blob_url": _blob_url(repo_url, branch, path),
            "size": int(item.get("size") or 0),
            "sha": item.get("sha") or "",
        })
    artifacts.sort(key=lambda a: a["path"])
    return artifacts


def _fetch_tree(or_path: str, branch: str) -> list[dict]:
    """Gitea recursive tree. truncated 시 page 진행. 실패 시 수집분 그대로 반환."""
    base = f"{GITEA_INTERNAL_URL}/api/v1/repos/{or_path}/git/trees/{branch}"
    qbase = "recursive=true&per_page=1000"
    items: list[dict] = []
    page = 1
    while page <= _MAX_PAGES:
        url = f"{base}?{qbase}&page={page}"
        try:
            data = _get_json(url)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                log.warning("[git_scan] tree HTTP %s %s page=%s", exc.code, or_path, page)
            return items
        except Exception as exc:
            log.warning("[git_scan] tree fetch failed %s page=%s: %s", or_path, page, exc)
            return items
        if not isinstance(data, dict):
            return items
        page_items = data.get("tree") or []
        items.extend(page_items)
        if not data.get("truncated"):
            break
        if not page_items:
            break
        page += 1
    return items


def _get_json(url: str) -> dict | list:
    req = urllib.request.Request(
        url, headers={"Authorization": f"token {_gitea_token()}"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as r:
        return json.loads(r.read())


def _blob_url(repo_url: str, branch: str, path: str) -> str:
    """GitHub 정본이면 github blob URL, 그 외엔 Gitea src URL.

    main branch 기준 (entity branch 가 아닌) — PR 머지 후에도 link rot 없음.
    """
    base = repo_url.rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]
    if "github.com/" in base:
        return f"{base}/blob/{branch}/{path}"
    return f"{base}/src/branch/{branch}/{path}"
