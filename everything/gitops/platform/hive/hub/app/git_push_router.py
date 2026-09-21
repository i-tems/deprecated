"""Git push webhook 의 범용 (repo, ref) → handler 디스패치.

`deployment.notify_push` 가 HMAC 검증·payload 파싱까지만 하고, "이 repo 의 이
branch push 를 누가 처리할지"는 여기 등록된 라우트가 결정한다. 각 owner 모듈이
import 시점에 `register()` 로 자기 라우트를 등록한다 (i-tems/hive→
hive_repo_route). 첫 매치가 처리하며 handle 은 백그라운드 async.

cell 빌드/배포는 meta 플랫폼(Gitea Actions→meta-sync)이 전담하므로 cell
라우트는 없다. hive-repo 라우트는 push-only (cold start 은 bootstrap, 폴러
없음). detection(webhook)과 action(reconcile)을 분리하는 게 이 모듈의 목적이다.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, NamedTuple

log = logging.getLogger("hub.git_push_router")

# (repo_url, branch, sha) → 백그라운드 처리. 동기 reconcile 은 핸들러가
# asyncio.to_thread 로 offload 한다 (webhook deliver timeout 의존 제거).
Handler = Callable[[str, str, str], Awaitable[None]]
Matcher = Callable[[str, str], bool]  # (repo_url, branch) → 이 라우트가 처리?


class Route(NamedTuple):
    name: str
    match: Matcher
    handle: Handler


_ROUTES: list[Route] = []


def repo_key(url: str) -> str:
    """owner·host 무관 basename 정규화 — notify_push payload(Gitea mirror URL)와
    cell.repo_url(GitHub canonical)을 동치 비교하기 위한 기존 컨벤션
    (commit 4b984e3). 라우트 matcher 가 공용으로 쓴다."""
    s = (url or "").strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    return s.rsplit("/", 1)[-1].lower()


def register(name: str, match: Matcher, handle: Handler) -> None:
    """owner 모듈이 import 시점에 자기 라우트를 1개 등록. 동일 name 재등록은
    교체(핫리로드·테스트 재import 안전)."""
    global _ROUTES
    _ROUTES = [r for r in _ROUTES if r.name != name]
    _ROUTES.append(Route(name, match, handle))
    log.info("[git_push_router] route 등록: %s (총 %d)", name, len(_ROUTES))


def resolve(repo_url: str, branch: str) -> Route | None:
    """첫 매치 라우트 반환. matcher 예외는 삼키고 다음 라우트로 (한 라우트
    오류가 전체 webhook 을 죽이지 않게)."""
    for r in _ROUTES:
        try:
            if r.match(repo_url, branch):
                return r
        except Exception as exc:  # noqa: BLE001
            log.warning("[git_push_router] matcher %s 예외: %s", r.name, exc)
    return None
