"""Cell 등록 + push webhook 릴레이.

cell 배포(빌드·매니페스트·promote)는 **신형 meta 플랫폼**(`gitops/platform/meta`,
`apiVersion: meta.i-tems.com/v1`)이 전담한다. cell repo 의 Gitea Actions
(`.gitea/workflows/meta-sync.yml`)가 `meta.lab.i-tems.com/sync/git` 를 호출 →
meta 가 매니페스트를 렌더해 `meta-apps` 레포에 commit → ArgoCD 배포.

이 모듈에 남는 책임은 신형 경로를 받쳐주는 것뿐:
- `deployment.cell_register`: ArgoCD AppProject(cell sandbox) 등록 + Gitea
  mirror 에 push webhook 멱등 설정.
- `cell.github_push`: GitHub canonical push → in-cluster Gitea mirror-sync 즉시
  트리거 (그래야 미러 위 Gitea Actions 가 곧바로 meta-sync 실행).
- `deployment.notify_push` / `git.github_push`: push webhook → git_push_router
  디스패치 (i-tems/hive 하네스 sync 등 등록된 라우트용 범용 front door).

레거시 `api_name: meta`/`kind: app` → hub kaniko 빌드·generated repo 매니페스트
경로(apply_cell·publish_meta_tag·promote chain·deploy_watcher·meta_reader·
meta_kinds·cell-build action)는 meta 플랫폼으로 일원화하며 제거됨.
"""

import os
import re

from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse

from .. import argocd_client, git_push_router
from ..storage import cells_repo


router = APIRouter()


def _safe_name(s: str) -> bool:
    """K8s name·DNS-1123 라벨 안전성 — cell prefix 등 hub가 박는 값 검증."""
    return bool(re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", s))


def re_safe_tag(tag: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9._-]{1,64}$", tag))


GENERATED_REPO_URL = os.environ.get(
    "GENERATED_REPO_URL", "https://github.com/i-tems/everything.git",
)


class CellRegisterRequest(BaseModel):
    cell_id: str


@router.post("/deployment.cell_register")
async def deployment_cell_register(req: CellRegisterRequest, request: Request) -> CapabilityResponse:
    """ArgoCD AppProject 를 cell sandbox로 등록 (idempotent). cell 의 Gitea
    mirror 에 push→/deployment.notify_push webhook 도 멱등 보장 — GitHub push →
    cell.github_push → mirror-sync → 미러 위 Gitea Actions 가 meta-sync 실행.
    """
    cell = cells_repo.get(req.cell_id)
    if not cell:
        return CapabilityResponse(
            status="error", error_code="cell_not_found",
            message=f"cell '{req.cell_id}' 가 등록되어 있지 않습니다",
        )
    try:
        result = argocd_client.upsert_appproject(
            cell_id=req.cell_id, repo_url=GENERATED_REPO_URL,
        )
    except Exception as exc:
        return CapabilityResponse(
            status="error", error_code="appproject_apply_failed", message=str(exc),
        )

    from .. import gitea_mirror
    webhook_result: dict = {"ensured": False, "action": "skipped",
                            "reason": "non-github repo"}
    repo_url = (cell.get("repo_url") or "").strip()
    if repo_url and gitea_mirror.is_github_url(repo_url):
        try:
            webhook_result = gitea_mirror.ensure_notify_webhook(repo_url)
        except Exception as exc:  # 절대 cell_register 를 깨지 않는다
            webhook_result = {"ensured": False, "action": "error",
                              "reason": str(exc)}
    return CapabilityResponse(
        status="ok", data={**result, "notify_webhook": webhook_result},
    )


# ── Gitea webhook: push → git_push_router 디스패치 ──


@router.post("/deployment.notify_push")
async def deployment_notify_push(request: Request) -> CapabilityResponse:
    """Gitea push webhook handler. HMAC-SHA256 공유 secret 검증 후 (repo,branch)
    를 git_push_router 로 디스패치 (i-tems/hive 하네스 sync 등 등록된 라우트).

    cell repo 의 빌드/배포는 meta 플랫폼(Gitea Actions → meta-sync)이 담당하므로
    여기서 cell 라우트는 더 이상 없다 — cell repo push 가 들어오면 매칭 라우트
    없음(no_route)으로 무해하게 종료된다. auth_middleware SKIP_PATHS 등록 —
    핸들러 자체에서 HMAC 검증.
    """
    body = await request.body()

    # 1) HMAC 검증
    import hmac as _hmac
    secret = os.environ.get("HUB_CELL_WEBHOOK_SECRET", "").strip()
    if not secret:
        return CapabilityResponse(status="error", error_code="auth_unconfigured",
                                  message="HUB_CELL_WEBHOOK_SECRET 미설정")
    presented = request.headers.get("x-gitea-signature", "")
    expected = _hmac.new(secret.encode(), body, "sha256").hexdigest()
    if not _hmac.compare_digest(presented, expected):
        return CapabilityResponse(status="error", error_code="auth_invalid",
                                  message="bad signature")

    # 2) Gitea event 종류
    event = request.headers.get("x-gitea-event", "")
    if event != "push":
        return CapabilityResponse(status="ok", data={"skipped": f"event={event!r}"})

    # 3) payload 파싱
    import json
    try:
        payload = json.loads(body)
    except Exception as exc:
        return CapabilityResponse(status="error", error_code="invalid_payload",
                                  message=str(exc))

    ref = payload.get("ref", "")
    if not ref.startswith("refs/heads/"):
        return CapabilityResponse(status="ok", data={"skipped": f"ref={ref!r}"})
    branch = ref[len("refs/heads/"):]

    repo_url = (payload.get("repository") or {}).get("html_url", "").strip()
    head_sha = (payload.get("after") or "").strip()
    if not repo_url or not head_sha:
        return CapabilityResponse(status="error", error_code="invalid_payload",
                                  message="repository.html_url 또는 after 누락")
    if not re_safe_tag(head_sha):
        return CapabilityResponse(status="error", error_code="invalid_payload",
                                  message="after sha 형식 이상")

    # 4) (repo, branch) → 라우트 디스패치 (i-tems/hive sync 등).
    route = git_push_router.resolve(repo_url, branch)
    if route is None:
        return CapabilityResponse(status="ok", data={
            "skipped": "no_route", "repo": repo_url, "branch": branch})

    # 5) 처리는 백그라운드 issue — Gitea webhook deliver timeout 의존 제거.
    import asyncio, logging
    log = logging.getLogger("hub.notify_push")

    async def _bg_process():
        try:
            await route.handle(repo_url, branch, head_sha)
        except Exception as exc:
            log.warning("[notify_push] route=%s 처리 실패: repo=%s sha=%s err=%s",
                        route.name, repo_url, head_sha[:7], exc, exc_info=True)

    asyncio.create_task(_bg_process())

    return CapabilityResponse(status="ok", data={
        "route": route.name,
        "repo": repo_url,
        "branch": branch,
        "sha": head_sha[:7],
        "queued": True,
    })


# ── GitHub → Gitea mirror-sync relay (push 즉시 sync, 폴링 lag 제거) ──


@router.post("/cell.github_push")
async def cell_github_push(request: Request, owner: str, repo: str) -> CapabilityResponse:
    """GitHub canonical repo 의 push webhook 이 외부 ingress(hub-webhook.i-tems.com)
    로 도달. HMAC-SHA256 검증 후 in-cluster Gitea API 의 mirror-sync 를 즉시 트리거.

    Gitea mirror 의 폴링 interval(1m) 대기를 우회 — push → 수초 내 mirror 갱신 →
    미러 위 Gitea Actions(.gitea/workflows/meta-sync.yml)가 곧바로 meta-sync 실행.

    cell.json 의 `subscriptions` 동기화는 본 핸들러가 직접 하지 않는다 — mirror
    갱신 후 Gitea 가 발사하는 push webhook 이 `deployment.notify_push` 로 도달하면
    `cell_repo_route` 가 처리한다(mirror 가 새 commit 반영된 시점이라 polling
    불필요, private repo 도 Gitea admin 토큰으로 읽힘).

    Query params: owner, repo  — Gitea repo 좌표 (예 ?owner=i-tems&repo=cell-pen).
                  cell admin 이 GitHub webhook URL 에 박아둠 — multi-cell 시 cell repo
                  마다 다른 owner/repo 사용.

    Auth: GitHub webhook secret 은 hub Secret 의 HUB_CELL_WEBHOOK_SECRET 와 동일하게
    설정. X-Hub-Signature-256 헤더 검증.
    """
    if not _safe_name(owner) or not _safe_name(repo):
        return CapabilityResponse(status="error", error_code="invalid_request",
                                  message="owner/repo 는 K8s DNS-1123 label 컨벤션")

    body = await request.body()

    # 1) GitHub HMAC 검증
    import hmac as _hmac
    secret = os.environ.get("HUB_CELL_WEBHOOK_SECRET", "").strip()
    if not secret:
        return CapabilityResponse(status="error", error_code="auth_unconfigured",
                                  message="HUB_CELL_WEBHOOK_SECRET 미설정")
    presented = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + _hmac.new(secret.encode(), body, "sha256").hexdigest()
    if not _hmac.compare_digest(presented, expected):
        return CapabilityResponse(status="error", error_code="auth_invalid",
                                  message="bad signature")

    # 2) Gitea mirror-sync 호출 (in-cluster Service)
    gitea_token = os.environ.get("HUB_GITEA_ADMIN_TOKEN", "").strip()
    if not gitea_token:
        return CapabilityResponse(status="error", error_code="gitea_token_missing",
                                  message="HUB_GITEA_ADMIN_TOKEN 미설정")
    gitea_url = os.environ.get(
        "HUB_GITEA_INTERNAL_URL", "http://gitea-http.gitea.svc:3000",
    ).rstrip("/")
    sync_url = f"{gitea_url}/api/v1/repos/{owner}/{repo}/mirror-sync"

    import urllib.request
    req = urllib.request.Request(
        sync_url, method="POST",
        headers={"Authorization": f"token {gitea_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.status
    except urllib.request.HTTPError as exc:
        return CapabilityResponse(status="error", error_code="sync_failed",
                                  message=f"Gitea {exc.code}: {exc.reason}")
    except Exception as exc:
        return CapabilityResponse(status="error", error_code="sync_failed", message=str(exc))

    if not (200 <= status_code < 300):
        return CapabilityResponse(status="error", error_code="sync_failed",
                                  message=f"Gitea status {status_code}")

    # cell.json subscriptions sync 는 `cell_repo_route` 가 처리 — Gitea 가 mirror
    # 갱신 후 발사하는 push webhook 이 `deployment.notify_push` 로 도달하면 그
    # 시점(mirror 새 commit 반영 후)에 polling 없이 즉시 fetch.
    return CapabilityResponse(status="ok", data={
        "owner": owner,
        "repo": repo,
        "synced": True,
    })


@router.post("/git.github_push")
async def git_github_push(request: Request) -> CapabilityResponse:
    """GitHub canonical repo 의 push webhook → git_push_router 디스패치.

    Gitea 미러가 없는 repo(예: 하네스 i-tems/hive)용 push front door.
    cell.github_push 는 Gitea mirror-sync 전용이라 미러 없는 repo 엔 무용 — 이
    엔드포인트는 GitHub 서명만 검증하고 (repo, branch) 를 그대로 git_push_router
    로 넘긴다. cell repo 는 기존 mirror-sync 체인(/cell.github_push)을 계속 쓴다.

    외부 ingress(hub-webhook.i-tems.com) 노출. auth_middleware SKIP_PATHS 등록 —
    핸들러가 X-Hub-Signature-256(HMAC-SHA256, HUB_CELL_WEBHOOK_SECRET) 자체 검증.
    """
    body = await request.body()

    # 1) GitHub HMAC 검증 (cell.github_push 와 동일 규약)
    import hmac as _hmac
    secret = os.environ.get("HUB_CELL_WEBHOOK_SECRET", "").strip()
    if not secret:
        return CapabilityResponse(status="error", error_code="auth_unconfigured",
                                  message="HUB_CELL_WEBHOOK_SECRET 미설정")
    presented = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + _hmac.new(secret.encode(), body, "sha256").hexdigest()
    if not _hmac.compare_digest(presented, expected):
        return CapabilityResponse(status="error", error_code="auth_invalid",
                                  message="bad signature")

    # 2) GitHub event 종류
    event = request.headers.get("x-github-event", "")
    if event != "push":
        return CapabilityResponse(status="ok", data={"skipped": f"event={event!r}"})

    # 3) payload 파싱 (GitHub push 스키마)
    import json
    try:
        payload = json.loads(body)
    except Exception as exc:
        return CapabilityResponse(status="error", error_code="invalid_payload",
                                  message=str(exc))
    ref = payload.get("ref", "")
    if not ref.startswith("refs/heads/"):
        return CapabilityResponse(status="ok", data={"skipped": f"ref={ref!r}"})
    branch = ref[len("refs/heads/"):]
    repo = payload.get("repository") or {}
    repo_url = (repo.get("html_url") or repo.get("clone_url") or "").strip()
    head_sha = (payload.get("after") or "").strip()
    if not repo_url or not head_sha:
        return CapabilityResponse(status="error", error_code="invalid_payload",
                                  message="repository.html_url 또는 after 누락")
    if not re_safe_tag(head_sha):
        return CapabilityResponse(status="error", error_code="invalid_payload",
                                  message="after sha 형식 이상")

    # 4) 라우트 디스패치 (notify_push 와 동일 — 백그라운드, 즉시 200)
    route = git_push_router.resolve(repo_url, branch)
    if route is None:
        return CapabilityResponse(status="ok", data={
            "skipped": "no_route", "repo": repo_url, "branch": branch})

    import asyncio, logging
    log = logging.getLogger("hub.git_github_push")

    async def _bg_process():
        try:
            await route.handle(repo_url, branch, head_sha)
        except Exception as exc:
            log.warning("[git_github_push] route=%s 처리 실패: repo=%s sha=%s err=%s",
                        route.name, repo_url, head_sha[:7], exc, exc_info=True)

    asyncio.create_task(_bg_process())
    return CapabilityResponse(status="ok", data={
        "route": route.name, "repo": repo_url,
        "branch": branch, "sha": head_sha[:7], "queued": True,
    })
