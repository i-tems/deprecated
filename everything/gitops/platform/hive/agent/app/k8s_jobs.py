"""K8s Job spawner — agent-loop이 cell별 worker Job을 생성·watch·reap한다."""

from __future__ import annotations

import json
import os
import re
import time

from kubernetes import client as k8s
from kubernetes.client.exceptions import ApiException

from .config import SESSION_TIMEOUT

NAMESPACE = os.environ.get("AGENT_NAMESPACE", "hive")
WORKER_IMAGE = os.environ.get("WORKER_IMAGE", "registry.lab.i-tems.com/hive-agent:main")
WORKER_SERVICE_ACCOUNT = os.environ.get("WORKER_SERVICE_ACCOUNT", "hive-agent-worker")
WORKER_TTL_SECONDS = int(os.environ.get("WORKER_TTL_SECONDS", "600"))
# k8s Job activeDeadlineSeconds — persistent worker 는 entity 의 active 수명 동안 살아
# 있어야 한다. waiting 상태로 사람 응답을 분~시간 단위로 기다리므로 넉넉히 7일.
# 단일 claude 실행은 runtime watchdog (SESSION_TIMEOUT) 가 처리.
WORKER_TIMEOUT_SECONDS = int(os.environ.get("WORKER_TIMEOUT_SECONDS", str(7 * 24 * 3600)))
WORKER_HUB_URL = os.environ.get("HUB_URL", "http://hive-hub.hive.svc.cluster.local:8000")
WORKER_PVC_NAME = os.environ.get("DATA_PVC_NAME", "hive-data")

_SLUG_RE = re.compile(r"[^a-z0-9-]")


def slug(text: str, *, max_len: int = 30) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len].strip("-") or "x"


def job_name(cell_id: str, action_type: str, entity_id: str) -> str:
    # entity_id 는 `<CELL>-<TYPE>-<SEQ>` (예: ITEMS-ISSUE-302) — 그 자체로
    # 엔티티당 유일. slug 로 소문자/DNS-safe 화 (RFC1123 Job 이름 규칙).
    suffix = slug(entity_id, max_len=30)
    return f"w-{slug(cell_id, max_len=20)}-{slug(action_type, max_len=10)}-{suffix}"


def build_worker_job(*, cell_id: str, action: dict, name: str, repo_url: str | None = None, caller_token: str | None = None, traceparent: str | None = None) -> k8s.V1Job:
    """Worker Job 스펙. action(직렬화된 Action)을 env로 전달.

    repo_url이 주어진 cell은 워커가 부팅 시 NFS PVC 의 entity-별 워크스페이스
    (/data/workspaces/<cell>/<entity>/cell)에 bare repo 위 worktree 를 add 하고
    EXEC_CWD를 거기로 설정. repo_url 없으면 legacy NFS 경로 그대로.

    caller_token: agent-loop이 hub `/auth.caller_token`으로 발급받은 worker JWT.
    워커는 이 토큰으로 hub에 Bearer 인증한다 (HUB_CALLER_TOKEN env). caller_token이
    None이면 워커는 hub 호출에서 RuntimeError로 즉시 실패 (Phase 4부터 X-Internal-
    Token fallback 제거).
    """
    action_env = json.dumps(action, ensure_ascii=False)
    use_workspace = bool(repo_url)
    entity_id = (action.get("entity") or {}).get("issue_id") or (action.get("entity") or {}).get("project_id") or "unknown"
    # workspace 는 NFS 의 entity-별 디렉토리. cell 의 bare repo cache (/data/cells/<cell>/repos)
    # 와 worktree (/data/workspaces/<cell>/<entity>) 를 worker 가 git worktree 로 연결.
    # cell_id 는 hub 가 _to_kebab 으로 filesystem-safe 강제. entity_id 는
    # `<CELL>-<TYPE>-<SEQ>` canonical id — 영숫자·하이픈뿐이라 path-safe, 추가
    # transform 불필요 (hub workspace_cleanup 이 같은 entity_id 문자열로 동일
    # path 를 계산하므로 양쪽 transform 부재가 일치성을 자동 보장).
    #
    # workspace 는 subPath 마운트가 **아니라** 전체 PVC 마운트(/data) 하위 절대경로로
    # 노출한다. subPath 는 pod 마운트 시점에 NFS 서버 inode 로 1회 해석되고 kubelet
    # 이 재해석하지 않으므로, 워크스페이스 디렉토리가 out-of-band 로 삭제·재생성
    # (bootstrap self-heal rmtree, stuck 복구 worktree force-remove)되면 그 pod 의
    # subPath 핸들이 영구 stale → `/work/cell` 의 모든 I/O 가 ESTALE, pod 재생성
    # 전까지 복구 불가. 전체 /data 마운트는 접근마다 경로를 재탐색하므로 삭제·
    # 재생성을 투명하게 따라가 ESTALE 클래스 자체가 사라진다 (NESS-ISSUE-3 회귀).
    workspace_subpath = f"workspaces/{cell_id}/{entity_id}"
    workspace_nfs_path = f"/data/{workspace_subpath}"
    if use_workspace:
        exec_cwd = f"{workspace_nfs_path}/cell"
        project_dir = f"{workspace_nfs_path}/cell"
    else:
        exec_cwd = f"/data/cells/{cell_id}"
        project_dir = f"/data/cells/{cell_id}"

    env = [
        k8s.V1EnvVar(name="HUB_URL", value=WORKER_HUB_URL),
        k8s.V1EnvVar(name="CELL_ID", value=cell_id),
        k8s.V1EnvVar(name="ACTION", value=action_env),
        k8s.V1EnvVar(name="HOME", value="/data/shared"),
        # worker 모델 백엔드 — agent-loop 의 AGENT_BACKEND 를 그대로 전파. 기본 "sdk"
        # (ClaudeSDKClient). "codex" 로 플립하면 codex 백엔드(구독 OAuth, ~/.codex).
        k8s.V1EnvVar(name="AGENT_BACKEND", value=os.environ.get("AGENT_BACKEND", "sdk")),
        k8s.V1EnvVar(name="HIVE_ROOT", value="/data"),
        k8s.V1EnvVar(name="SHARED_DIR", value="/data/shared"),
        k8s.V1EnvVar(name="PROJECT_DIR", value=project_dir),
        k8s.V1EnvVar(name="EXEC_CWD", value=exec_cwd),
        # cell repo working tree 진입점. 정본·skill 이 $CELL_REPO 상대로 파일
        # 위치를 표기 — 사용자 셸($HOME/cell-<id>)과 동일 변수명.
        k8s.V1EnvVar(name="CELL_REPO", value=exec_cwd),
        k8s.V1EnvVar(name="SPECS_ROOT", value="/data/shared/specs"),
        # bare repo cache + worktree 등록에 worker / issue-clone 둘 다 사용.
        k8s.V1EnvVar(name="WORKSPACE_NFS_PATH", value=workspace_nfs_path),
        # cell의 GitHub PAT. cell repo·product code repo clone/push에 사용.
        # cell이 아직 토큰 등록 안 됐다면 missing 허용 (optional=True) — clone 시점에 에러로 드러남.
        k8s.V1EnvVar(
            name="GITHUB_TOKEN",
            value_from=k8s.V1EnvVarSource(
                secret_key_ref=k8s.V1SecretKeySelector(
                    name="hive-cell-tokens", key=cell_id, optional=True,
                )
            ),
        ),
    ]
    if repo_url:
        env.append(k8s.V1EnvVar(name="CELL_REPO_URL", value=repo_url))
    if caller_token:
        env.append(k8s.V1EnvVar(name="HUB_CALLER_TOKEN", value=caller_token))
    if traceparent:
        env.append(k8s.V1EnvVar(name="HUB_TRACEPARENT", value=traceparent))

    volume_mounts = [
        k8s.V1VolumeMount(name="data", mount_path="/data"),
    ]
    volumes = [
        k8s.V1Volume(
            name="data",
            persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name=WORKER_PVC_NAME),
        ),
    ]
    # workspace 는 별도 subPath 마운트를 만들지 않는다. 전체 /data 마운트 하위
    # 절대경로(/data/workspaces/<cell>/<entity>)로 접근 — pod 죽어도 worktree·
    # partial 파일이 NFS 에 보존되어 다음 worker 가 그대로 이어가는 성질은 동일
    # 하게 유지되고, subPath inode 고정으로 인한 ESTALE 영구 stuck 은 제거된다.

    container = k8s.V1Container(
        name="worker",
        image=WORKER_IMAGE,
        image_pull_policy="Always",
        command=["python3", "-m", "app.worker"],
        env=env,
        volume_mounts=volume_mounts,
        resources=k8s.V1ResourceRequirements(
            requests={"cpu": "100m", "memory": "256Mi"},
            limits={"cpu": "2", "memory": "2Gi"},
        ),
    )
    pod_spec_kwargs: dict = dict(
        restart_policy="Never",
        service_account_name=WORKER_SERVICE_ACCOUNT,
        containers=[container],
        volumes=volumes,
    )

    pod = k8s.V1PodTemplateSpec(
        metadata=k8s.V1ObjectMeta(
            labels={
                "app": "hive-agent-worker",
                "cell-id": slug(cell_id),
            }
        ),
        spec=k8s.V1PodSpec(**pod_spec_kwargs),
    )
    return k8s.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=k8s.V1ObjectMeta(
            name=name,
            namespace=NAMESPACE,
            labels={
                "app": "hive-agent-worker",
                "cell-id": slug(cell_id),
                "managed-by": "hive-agent-loop",
            },
            annotations={
                "hive.io/cell-id": cell_id,
            },
        ),
        spec=k8s.V1JobSpec(
            # persistent worker — pod crash 시 backoffLimit 만큼 재시도. 새 pod 은
            # hub 의 entity.session_id + last_prompt_at 로 --resume 해서 같은 대화 이어감.
            backoff_limit=3,
            ttl_seconds_after_finished=WORKER_TTL_SECONDS,
            active_deadline_seconds=WORKER_TIMEOUT_SECONDS,
            template=pod,
        ),
    )


def create_job(batch_api: k8s.BatchV1Api, job: k8s.V1Job) -> bool:
    try:
        batch_api.create_namespaced_job(namespace=NAMESPACE, body=job)
        return True
    except ApiException as e:
        if e.status == 409:
            return False
        raise


def list_active_jobs(batch_api: k8s.BatchV1Api) -> list[k8s.V1Job]:
    """완료되지 않은 worker Job들."""
    resp = batch_api.list_namespaced_job(
        namespace=NAMESPACE,
        label_selector="app=hive-agent-worker",
    )
    active = []
    for j in resp.items:
        st = j.status or k8s.V1JobStatus()
        if (st.succeeded or 0) == 0 and (st.failed or 0) == 0:
            active.append(j)
    return active


def reap_finished(batch_api: k8s.BatchV1Api) -> int:
    """완료된 Job 중 ttl이 안 끝난 것들 즉시 삭제(propagation=Background). count 반환."""
    resp = batch_api.list_namespaced_job(
        namespace=NAMESPACE,
        label_selector="app=hive-agent-worker",
    )
    n = 0
    for j in resp.items:
        st = j.status or k8s.V1JobStatus()
        if (st.succeeded or 0) >= 1 or (st.failed or 0) >= 1:
            try:
                batch_api.delete_namespaced_job(
                    name=j.metadata.name,
                    namespace=NAMESPACE,
                    propagation_policy="Background",
                )
                n += 1
            except ApiException as e:
                if e.status != 404:
                    raise
    return n
