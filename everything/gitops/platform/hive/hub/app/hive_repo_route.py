"""i-tems/hive `.claude` → NFS HOME sync 의 push 라우트 (poller 없음).

NFS HOME `/data/shared/.claude` 는 가동 중 cell·worker 가 read 한다. 갱신 경로:
- cold start: `startup.bootstrap()` 이 `sync_hive_repo(force=True)` 1회.
- 이후 변경: i-tems/hive webhook → `deployment.notify_push` → git_push_router
  "hive-repo" 라우트(아래) → 즉시 `sync_hive_repo`.

폴링 backstop 은 제거됨 (push-only). webhook 유실 시 hub 재기동(bootstrap)
전까지 stale 할 수 있다 — webhook 이 정상 경로. `sync_hive_repo` 는 자체
ls-remote SHA 비교로 멱등이라 중복 발화해도 무해. sync 는 blocking
(subprocess·shutil) 이라 asyncio.to_thread 로 이벤트 루프 밖에서 실행한다.
"""

import asyncio
import logging

from . import git_push_router, startup

log = logging.getLogger("hub.hive_repo_route")

# ── git_push_router 라우트: i-tems/hive main push → 즉시 NFS sync ──
# basename 동치(repo_key) + 기본 브랜치만.
_HIVE_REPO_KEY = git_push_router.repo_key(startup.HIVE_REPO_URL)
_HIVE_DEFAULT_BRANCHES = {"main", "master"}


def _match_hive_repo(repo_url: str, branch: str) -> bool:
    return (
        git_push_router.repo_key(repo_url) == _HIVE_REPO_KEY
        and branch in _HIVE_DEFAULT_BRANCHES
    )


async def _handle_hive_push(repo_url: str, branch: str, sha: str) -> None:
    # sha 는 무시 — sync_hive_repo 가 직접 ls-remote 로 최신 HEAD 를 받아 swap.
    synced = await asyncio.to_thread(startup.sync_hive_repo, "webhook")
    log.info("[hive-repo] webhook sync 완료 (synced_sha=%s)",
             (synced or "?")[:7])


git_push_router.register("hive-repo", _match_hive_repo, _handle_hive_push)
