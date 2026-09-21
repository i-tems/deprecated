"""Cell app 배포 URL 도출 via meta API.

project.apps[] 에 선언된 앱(상시 dev/prd) 또는 issue 브랜치(`issue/<id>`)에
해당하는 meta App 변형의 live 배포 URL 을 반환한다. `issue.get` / `project.get`
응답의 derived `deployments` 필드 소스 — artifacts 처럼 매번 도출(저장 없음)이라
배포가 사라지면 응답에서도 자동으로 빠진다.

reachable host: prd=`spec.host`(공개 도메인), 비운영=`spec.tunnelHost`(직원 게이트).
lab host 는 사람이 못 여니 노출하지 않는다 (communication_rule §사람이 닿는 호스트).
tunnel 호스트가 없는 비운영 변형은 외부 도달 경로가 없어 skip.

resources(사람이 직접 등록) 와 분리된 derived 채널. 실패(meta 미응답 등)는
빈 리스트로 graceful 반환 — project.get / issue.get 를 깨지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from .storage import cells_repo

log = logging.getLogger("hub.meta_deployments")

META_INTERNAL_URL = os.environ.get(
    "HUB_META_INTERNAL_URL", "http://meta.meta.svc.cluster.local:8000",
)
_APP_LIST_PATH = "/apis/meta.i-tems.com/v1/App"
_TIMEOUT_SECONDS = 5

_LBL_APP = "meta.i-tems.com/app"
_LBL_ENV = "meta.i-tems.com/env"
_LBL_REPO = "meta.i-tems.com/source-repo"
_LBL_BRANCH = "meta.i-tems.com/source-branch"


def _cell_repo_slug(repo_url: str) -> str | None:
    """``https://github.com/i-tems/cell-items[.git]`` → ``i-tems/cell-items``.

    meta App 의 ``source-repo`` 라벨(예: ``i-tems/cell-items``)과 맞추기 위한 정규화.
    """
    s = (repo_url or "").strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    parts = [p for p in s.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return None


def _reachable_url(spec: dict, env: str) -> str | None:
    """사람이 여는 URL — prd 는 공개 도메인(host), 비운영은 tunnel host. 없으면 None."""
    host = spec.get("host") if env == "prd" else spec.get("tunnelHost")
    return f"https://{host}" if host else None


def _fetch_apps_checked() -> tuple[bool, list[dict]]:
    """meta App 목록을 (조회성공?, 리스트) 로 반환. 실패와 '앱 0개' 를 구분한다.

    scan_deployments(derived 필드)는 실패=빈리스트로 충분하지만,
    preview_readiness 게이트는 'meta 미응답'(판정불가→fail-open)과
    '매칭 App 없음'(빌드 실패 가능→reject)을 반드시 구분해야 한다.
    """
    url = f"{META_INTERNAL_URL}{_APP_LIST_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("[meta_deployments] App 목록 조회 실패: %s", exc)
        return (False, [])
    return (True, data if isinstance(data, list) else [])


def _fetch_apps() -> list[dict]:
    """meta App 목록. 실패 시 빈 리스트 (graceful)."""
    return _fetch_apps_checked()[1]


def scan_deployments(
    cell_id: str,
    *,
    app_names: list[str] | None = None,
    issue_branch: str | None = None,
) -> list[dict]:
    """선언 앱(app_names) 또는 issue 브랜치에 매칭되는 live 배포 → dict 리스트.

    매칭: meta App 의 ``source-repo`` 가 이 cell repo 이고, ``app`` 라벨이
    app_names 에 있거나 ``source-branch`` 가 issue_branch 와 같을 때.
    반환 항목: ``{app, env, url, phase}`` (reachable url 있는 것만), app/env 정렬.
    """
    names = set(app_names or [])
    if not names and not issue_branch:
        return []
    cell = cells_repo.get(cell_id)
    if not cell:
        return []
    repo_slug = _cell_repo_slug(cell.get("repo_url") or "")
    if not repo_slug:
        return []

    out: list[dict] = []
    for app in _fetch_apps():
        labels = (app.get("metadata") or {}).get("labels") or {}
        if labels.get(_LBL_REPO) != repo_slug:
            continue
        app_name = labels.get(_LBL_APP) or ""
        branch = labels.get(_LBL_BRANCH) or ""
        if not (app_name in names or (issue_branch and branch == issue_branch)):
            continue
        env = labels.get(_LBL_ENV) or ""
        url = _reachable_url(app.get("spec") or {}, env)
        if not url:
            continue
        out.append({
            "app": app_name,
            "env": env,
            "url": url,
            "phase": (app.get("status") or {}).get("phase") or "",
        })
    out.sort(key=lambda d: (d["app"], d["env"]))
    return out


def preview_readiness(cell_id: str, issue_branch: str) -> tuple[str, list[dict]]:
    """issue 브랜치 미리보기 배포의 준비 상태. preview_review 핸드오프 게이트용.

    반환 ``(state, matched)``:
      - ``"ready"``            매칭된 meta App 이 1개 이상이고 전부 ``phase==Ready``.
      - ``"not_ready"``        매칭 App 은 있으나 일부가 Ready 아님 (배포 중·crash 등).
      - ``"absent"``           매칭 App 없음 — 빌드 미완/실패로 아직 생성 안 됨.
      - ``"meta_unreachable"`` meta 조회 실패 — 판정 불가 (호출측 fail-open).

    ``matched``: 진단용 ``[{app, env, phase, host}]`` (reachable 여부 무관 —
    배포 중이라 tunnelHost 가 아직 없는 변형도 phase 판정에 포함해야 하므로
    scan_deployments 의 url 필터를 쓰지 않는다).
    """
    cell = cells_repo.get(cell_id)
    if not cell:
        return ("absent", [])
    repo_slug = _cell_repo_slug(cell.get("repo_url") or "")
    if not repo_slug:
        return ("absent", [])
    ok, apps = _fetch_apps_checked()
    if not ok:
        return ("meta_unreachable", [])
    matched: list[dict] = []
    for app in apps:
        labels = (app.get("metadata") or {}).get("labels") or {}
        if labels.get(_LBL_REPO) != repo_slug:
            continue
        if labels.get(_LBL_BRANCH) != issue_branch:
            continue
        spec = app.get("spec") or {}
        matched.append({
            "app": labels.get(_LBL_APP) or "",
            "env": labels.get(_LBL_ENV) or "",
            "phase": (app.get("status") or {}).get("phase") or "",
            "host": spec.get("tunnelHost") or spec.get("host") or "",
        })
    if not matched:
        return ("absent", [])
    if all(d["phase"] == "Ready" for d in matched):
        return ("ready", matched)
    return ("not_ready", matched)
