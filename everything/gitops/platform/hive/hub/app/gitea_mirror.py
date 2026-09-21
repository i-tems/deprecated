"""GitHub → Gitea mirror 라우팅 헬퍼.

GitHub 이 정본이지만 cell repo 는 Gitea 에 mirror 로도 존재한다 (cell-pen 등
mirror=true). hub 의 read-only 작업 (clone, polling) 은 Gitea mirror 를 거쳐
GitHub API rate limit / git protocol 부담을 줄인다. write 작업 (push, PR 생성) 은
mirror 가 받지 못하므로 항상 원본 GitHub URL 을 사용해야 한다.

Gitea 정본 cell (URL 자체가 gitea.lab.i-tems.com) 은 매핑 자체를 거치지 않는다 —
들어온 URL 을 그대로 통과.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request


log = logging.getLogger("hub.gitea_mirror")


GITEA_INTERNAL_URL = os.environ.get(
    "HUB_GITEA_INTERNAL_URL", "http://gitea-http.gitea.svc.cluster.local:3000",
).rstrip("/")


def is_github_url(repo_url: str) -> bool:
    return "github.com/" in (repo_url or "")


def is_gitea_url(repo_url: str) -> bool:
    s = repo_url or ""
    return "gitea.lab.i-tems.com/" in s or "gitea-http.gitea.svc" in s


def parse_github_owner_repo(repo_url: str) -> tuple[str, str] | None:
    """https://github.com/{owner}/{repo}[.git] → (owner, repo). 형식 안 맞으면 None."""
    s = (repo_url or "").rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    if "github.com/" not in s:
        return None
    tail = s.split("github.com/", 1)[1]
    parts = tail.split("/")
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _parse_gitea_owner_repo(repo_url: str) -> tuple[str, str] | None:
    """https://gitea.lab.i-tems.com/{owner}/{repo}[.git] → (owner, repo)."""
    s = (repo_url or "").rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    for marker in ("gitea.lab.i-tems.com/", "gitea-http.gitea.svc.cluster.local:3000/",
                    "gitea-http.gitea.svc:3000/"):
        if marker in s:
            tail = s.split(marker, 1)[1]
            parts = tail.split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
    return None


def _gitea_api_owner_repo(repo_url: str) -> str | None:
    """모든 종류의 cell repo URL → 'owner/repo' (Gitea API path 용).

    GitHub·Gitea owner 동일(둘 다 i-tems) — owner 매핑 불필요.
    - GitHub URL / Gitea URL: owner/repo 그대로
    - 기타: None
    """
    p = parse_github_owner_repo(repo_url)
    if p:
        return f"{p[0]}/{p[1]}"
    p = _parse_gitea_owner_repo(repo_url)
    if p:
        return f"{p[0]}/{p[1]}"
    return None


def to_gitea_clone_url(repo_url: str) -> str | None:
    """repo URL → Gitea in-cluster mirror clone URL.

    GitHub URL 은 owner 매핑 후 Gitea 경로로 변환. Gitea URL 은 외부 도메인을
    in-cluster service URL 로 정규화. 매핑 실패 시 None.
    """
    or_path = _gitea_api_owner_repo(repo_url)
    if not or_path:
        return None
    return f"{GITEA_INTERNAL_URL}/{or_path}.git"


def _gitea_token() -> str:
    token = os.environ.get("HUB_GITEA_ADMIN_TOKEN", "").strip()
    if not token:
        raise LookupError("HUB_GITEA_ADMIN_TOKEN 미설정 — Gitea API 호출 불가")
    return token


def _api_get(path: str) -> dict | list:
    """Gitea API GET. path 는 '/api/v1/...' 절대 path."""
    url = f"{GITEA_INTERNAL_URL}{path}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"token {_gitea_token()}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def branch_head_sha(github_url: str, branch: str = "main") -> str | None:
    """Gitea mirror 의 branch HEAD sha. 매핑 실패·404 시 None."""
    or_path = _gitea_api_owner_repo(github_url)
    if not or_path:
        return None
    try:
        data = _api_get(f"/api/v1/repos/{or_path}/branches/{branch}")
        return ((data.get("commit") or {}).get("id")) if isinstance(data, dict) else None
    except urllib.error.HTTPError as exc:
        log.warning("[gitea_mirror] branch head 조회 실패 %s/%s: HTTP %s",
                    or_path, branch, exc.code)
        return None
    except Exception as exc:
        log.warning("[gitea_mirror] branch head 조회 예외 %s: %s", or_path, exc)
        return None


def changed_paths_since(github_url: str, base_sha: str, head_sha: str,
                         max_commits: int = 50) -> list[str]:
    """base..head 사이 변경 파일 목록.

    Gitea 1.23 에 /compare API 미지원 → /commits?sha={head}&limit=N 으로 페이징하며
    base 를 만날 때까지 거꾸로 수집. 일반 cell push 의 commit 수는 1~5 라 한 번
    호출로 충분하지만 안전장치로 page 처리.
    """
    or_path = _gitea_api_owner_repo(github_url)
    if not or_path or not base_sha or not head_sha:
        return []
    if base_sha == head_sha:
        return []

    seen: set[str] = set()
    found_base = False
    page = 1
    page_size = 20
    while not found_base and page <= (max_commits // page_size + 1):
        try:
            data = _api_get(
                f"/api/v1/repos/{or_path}/commits?sha={head_sha}"
                f"&limit={page_size}&page={page}&stat=true"
            )
        except urllib.error.HTTPError as exc:
            log.warning("[gitea_mirror] commits 조회 실패 %s sha=%s: HTTP %s",
                        or_path, head_sha[:7], exc.code)
            return []
        except Exception as exc:
            log.warning("[gitea_mirror] commits 조회 예외 %s: %s", or_path, exc)
            return []
        if not isinstance(data, list) or not data:
            break
        for commit in data:
            sha = commit.get("sha") or ""
            if sha == base_sha or sha.startswith(base_sha) or base_sha.startswith(sha):
                found_base = True
                break
            for f in commit.get("files") or []:
                fn = f.get("filename")
                if fn:
                    seen.add(fn)
        if len(data) < page_size:
            break
        page += 1
    return sorted(seen)


def force_mirror_sync(github_url: str) -> bool:
    """Gitea mirror sync 강제 호출. 호출 후 즉시 read 안전. 실패시 False.

    push webhook 이 정상 흐름에서 이미 호출하지만, polling 진입 시점에도 한 번
    호출하면 race window 줄어듦.
    """
    or_path = _gitea_api_owner_repo(github_url)
    if not or_path:
        return False
    try:
        url = f"{GITEA_INTERNAL_URL}/api/v1/repos/{or_path}/mirror-sync"
        req = urllib.request.Request(
            url, method="POST",
            headers={"Authorization": f"token {_gitea_token()}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception as exc:
        log.warning("[gitea_mirror] sync 실패 %s: %s", or_path, exc)
        return False


# Gitea mirror 가 sync(API-트리거·30m 스케줄 pull 모두 동일 SyncPullMirror 경로)로
# 새 커밋을 받으면 이 webhook 을 발화 → hub 가 build/apply. 실측 검증됨(issue 88).
# Gitea webhook.ALLOWED_HOST_LIST 에 이 host 가 포함돼야 전달됨(현 설정 *.svc 포함).
HUB_NOTIFY_URL = os.environ.get(
    "HUB_INTERNAL_NOTIFY_URL", "http://hive-hub.hive.svc:8000/deployment.notify_push",
)


def ensure_notify_webhook(github_url: str) -> dict:
    """cell 의 Gitea mirror 에 push→/deployment.notify_push webhook 을 멱등 보장.

    동일 url 의 hook 이 이미 있으면 no-op. Gitea 'gitea' 타입은
    X-Gitea-Signature(HMAC-SHA256, secret) + X-Gitea-Event 를 보내
    notify_push 핸들러의 검증과 1:1 일치. 비-GitHub(매핑 불가) repo 는 skip.

    반환: {"ensured": bool, "action": "exists"|"created"|"skipped"|"error", ...}
    """
    or_path = _gitea_api_owner_repo(github_url)
    if not or_path:
        return {"ensured": False, "action": "skipped",
                "reason": "gitea owner/repo 매핑 불가", "url": github_url}
    secret = os.environ.get("HUB_CELL_WEBHOOK_SECRET", "").strip()
    if not secret:
        return {"ensured": False, "action": "skipped",
                "reason": "HUB_CELL_WEBHOOK_SECRET 미설정"}
    try:
        hooks = _api_get(f"/api/v1/repos/{or_path}/hooks")
    except Exception as exc:
        log.warning("[gitea_mirror] hooks 조회 실패 %s: %s", or_path, exc)
        return {"ensured": False, "action": "error",
                "reason": f"hooks 조회 실패: {exc}", "repo": or_path}
    for h in hooks if isinstance(hooks, list) else []:
        if (h.get("config") or {}).get("url") == HUB_NOTIFY_URL:
            return {"ensured": True, "action": "exists",
                    "hook_id": h.get("id"), "repo": or_path}
    payload = json.dumps({
        "type": "gitea",
        "active": True,
        "events": ["push"],
        "config": {"url": HUB_NOTIFY_URL, "content_type": "json", "secret": secret},
    }).encode()
    try:
        req = urllib.request.Request(
            f"{GITEA_INTERNAL_URL}/api/v1/repos/{or_path}/hooks",
            data=payload, method="POST",
            headers={"Authorization": f"token {_gitea_token()}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            created = json.loads(r.read())
        log.info("[gitea_mirror] notify webhook 생성 %s -> %s", or_path, HUB_NOTIFY_URL)
        return {"ensured": True, "action": "created",
                "hook_id": created.get("id"), "repo": or_path}
    except Exception as exc:
        log.warning("[gitea_mirror] notify webhook 생성 실패 %s: %s", or_path, exc)
        return {"ensured": False, "action": "error",
                "reason": str(exc), "repo": or_path}
