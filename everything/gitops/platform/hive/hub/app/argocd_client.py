"""ArgoCD AppProject / webhook 헬퍼.

Application 자체는 ApplicationSet(meta-apps=cell 배포, cells-issue-preview=
issue 미리보기)가 git 트리를 보고 자동 생성하므로 hub 가 만들지 않는다.
hub 의 책임:
  - upsert_appproject : 셀 sandbox AppProject 등록 (cells-issue-preview 가
                        spec.project=cell-<id> 로 참조; 한 셀당 1회)
  - notify_webhook    : push 후 ArgoCD reconcile 즉시 트리거

cross-namespace 작업 (hub→argocd ns)이라 hub SA에 argocd-rbac Role 필요.
"""

from __future__ import annotations

import os
from typing import Any

from kubernetes import client as k8s, config as k8s_config
from kubernetes.client.exceptions import ApiException

from .slug import slug


ARGOCD_NAMESPACE = os.environ.get("ARGOCD_NAMESPACE", "argocd")
APP_API_GROUP = "argoproj.io"
APP_API_VERSION = "v1alpha1"


def _load_config():
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()


def _custom_api() -> k8s.CustomObjectsApi:
    _load_config()
    return k8s.CustomObjectsApi()


def upsert_appproject(*, cell_id: str, repo_url: str) -> dict:
    """argocd ns 에 AppProject CR upsert. cell sandbox 정의:
      - sourceRepos: 지정한 repo 만
      - destinations.namespace: cell-<cell> 만 (셀당 ns 1개, cell- prefix)
      - clusterResourceWhitelist: Namespace 만 (CreateNamespace=true 위해)

    namespace 내부 리소스 종류는 제한하지 않는다 (whitelist 사용 안 함) — 화이트리스트는
    UI 트리에서 child(Pod/ReplicaSet) cascade 도 함께 가려버려 운영 가시성을 떨어뜨림.

    cells-issue-preview ApplicationSet template 의 spec.project 가 'cell-<cell-id>'
    로 참조하므로 이름 컨벤션 고정.
    """
    name = f"cell-{slug(cell_id, max_len=50)}"
    body: dict[str, Any] = {
        "apiVersion": f"{APP_API_GROUP}/{APP_API_VERSION}",
        "kind": "AppProject",
        "metadata": {"name": name, "namespace": ARGOCD_NAMESPACE},
        "spec": {
            "description": f"Sandbox for cell '{cell_id}'. Auto-created by hive-hub.",
            "sourceRepos": [repo_url],
            "destinations": [{
                "server": "https://kubernetes.default.svc",
                "namespace": f"cell-{cell_id}",
            }],
            "clusterResourceWhitelist": [
                {"group": "", "kind": "Namespace"},
            ],
        },
    }
    api = _custom_api()
    try:
        api.create_namespaced_custom_object(
            group=APP_API_GROUP, version=APP_API_VERSION,
            namespace=ARGOCD_NAMESPACE, plural="appprojects", body=body,
        )
        return {"name": name, "created": True}
    except ApiException as exc:
        if exc.status == 409:
            # replace 시맨틱: body 에 없는 키는 라이브 객체에서 제거됨. merge patch 로
            # 처리하면 빠진 필드가 그대로 남아 spec drift 발생.
            existing = api.get_namespaced_custom_object(
                group=APP_API_GROUP, version=APP_API_VERSION,
                namespace=ARGOCD_NAMESPACE, plural="appprojects", name=name,
            )
            body["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
            api.replace_namespaced_custom_object(
                group=APP_API_GROUP, version=APP_API_VERSION,
                namespace=ARGOCD_NAMESPACE, plural="appprojects", name=name,
                body=body,
            )
            return {"name": name, "created": False, "patched": True}
        raise


def notify_webhook(repo_url: str, *, branch: str = "main", timeout: int = 5) -> bool:
    """ArgoCD 의 git webhook 엔드포인트를 호출해 즉시 reconcile 트리거.

    deploy 후 ArgoCD 의 기본 polling(~3분) 대기 시간을 제거하기 위함. best-effort —
    실패해도 raise 안 함 (호출자는 결과를 무시하면 됨). 실패 시 ArgoCD 의 자체 polling
    이 다음 사이클에 받아주므로 lag 만 발생.

    repo_url 의 .git 접미는 제거 (ArgoCD 가 동일하게 normalize 하므로).
    """
    import json
    import urllib.request
    url = os.environ.get(
        "ARGOCD_WEBHOOK_URL",
        f"http://argocd-server.{ARGOCD_NAMESPACE}.svc/api/webhook",
    )
    payload = json.dumps({
        "ref": f"refs/heads/{branch}",
        "repository": {"html_url": repo_url.removesuffix(".git")},
    }).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"X-GitHub-Event": "push", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
