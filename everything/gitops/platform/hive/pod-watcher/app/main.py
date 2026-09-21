"""hive-pod-watcher

클러스터 전역 Pod 를 watch 하다가 컨테이너가 0 이 아닌 exit code 로 종료되면
hive-hub `signal.emit` 으로 `infra.pod_failed` 신호를 발사한다.

- Job/CronJob 소속 Pod 는 의도적 실패가 흔하므로 제외 (controller chain 추적).
- (pod_uid, container) 단위 dedup — 한 Pod·container 에서 첫 비정상 종료만 emit.
  CrashLoopBackOff 로 재시작이 반복돼도 같은 pod_uid 면 침묵. controller 가
  Pod 를 새로 만들면 새 pod_uid → 다시 emit (의도된 동작).
- DELETED 이벤트에서 seen 항목 정리 → 메모리 누수 방지.
- 시작 시 list 로 기존 종료 상태를 캐시 시드(emit=False) → 재기동 후 과거 실패 재발사 방지.
- watch resourceVersion 만료(410) 시 재-list & 재-watch.
- Auth: HUB_INTERNAL_TOKEN 으로 부트스트랩 → caller_token 발급, 이후 Bearer 사용.
- Cell: WATCHER_CELL_ID env 로 송신 cell 지정 (기본 'pen').
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import httpx
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

LOG = logging.getLogger("pod-watcher")

HUB_URL = os.environ.get("HUB_URL", "http://hive-hub.hive.svc.cluster.local:8000")
EMITTER = os.environ.get("EMITTER", "hive-pod-watcher")
HUB_TIMEOUT = float(os.environ.get("HUB_TIMEOUT", "10"))
RETRY_SECONDS = float(os.environ.get("WATCH_RETRY_SECONDS", "5"))
CELL_ID = os.environ.get("WATCHER_CELL_ID", "pen").strip() or "pen"
TOKEN_TTL_SECONDS = int(os.environ.get("HUB_TOKEN_TTL_SECONDS", "86400"))

EXCLUDED_OWNER_KINDS = {"Job"}

# SIGTERM(128+15) 으로 종료된 컨테이너의 exit code. K8s 가 Pod 를 내릴 때
# (롤아웃·스케일다운·워커 작업 완료 후 삭제) 보내는 graceful termination 의 정상 흐름이라
# 장애가 아니다. restart_count==0 이면 crashloop 도 아니므로 pod_failed 에서 제외한다.
# rollout 중 grace period 를 넘긴 구 Deployment Pod 와 sandbox TTL/destroy teardown 은
# SIGKILL(137)+Error 로 남을 수 있다. OOMKilled 가 아니고 restart_count==0 인 정상 정리만 제외한다.
SIGTERM_EXIT_CODE = 143
SIGKILL_EXIT_CODE = 137
OOMKILLED_REASON = "OOMKilled"
DEPLOYMENT_OWNER_KIND = "Deployment"
SANDBOX_POD_PREFIX = "sandbox-"


def _load_kube() -> None:
    try:
        config.load_incluster_config()
        LOG.info("loaded in-cluster kube config")
    except config.ConfigException:
        config.load_kube_config()
        LOG.info("loaded local kube config (dev)")


def _mint_caller_token() -> str:
    """hub `/auth.caller_token` 을 X-Internal-Token 으로 호출해 caller_token 발급.

    실패 시 RuntimeError → pod 재시작 (fail-fast). 토큰 없이는 이 워처가 일을 못 한다.
    """
    internal_token = os.environ.get("HUB_INTERNAL_TOKEN", "").strip()
    if not internal_token:
        raise RuntimeError("HUB_INTERNAL_TOKEN env 가 비어 있어 caller_token 발급 불가")
    host = os.environ.get("HOSTNAME") or "unknown"
    body = json.dumps({
        "principal_type": "system",
        "principal_id": f"system:pod-watcher:{host}",
        "expiry_seconds": TOKEN_TTL_SECONDS,
    }).encode()
    req = urllib.request.Request(
        f"{HUB_URL}/auth.caller_token",
        data=body,
        headers={"Content-Type": "application/json", "X-Internal-Token": internal_token},
    )
    try:
        with urllib.request.urlopen(req, timeout=HUB_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"caller_token 발급 실패: {exc}") from exc
    if data.get("status") != "ok":
        raise RuntimeError(f"caller_token 응답 비정상: {data}")
    token = (data.get("data") or {}).get("token")
    if not token:
        raise RuntimeError(f"caller_token 응답에 token 누락: {data}")
    LOG.info("caller_token 발급 완료 (host=%s, ttl=%ss)", host, TOKEN_TTL_SECONDS)
    return token


def _resolve_owner(api: client.AppsV1Api, pod: Any) -> tuple[str | None, str | None]:
    """Pod 의 최상위 컨트롤러 (kind, name) 추출.
    ReplicaSet → Deployment 한 단계 승격. Job 은 그대로 반환 (호출측에서 필터).
    """
    owners = pod.metadata.owner_references or []
    if not owners:
        return None, None
    o = owners[0]
    kind, name, ns = o.kind, o.name, pod.metadata.namespace
    if kind == "ReplicaSet":
        try:
            rs = api.read_namespaced_replica_set(name=name, namespace=ns)
            rs_owners = rs.metadata.owner_references or []
            if rs_owners:
                return rs_owners[0].kind, rs_owners[0].name
        except ApiException as e:
            LOG.debug("ReplicaSet lookup failed (%s/%s): %s", ns, name, e.status)
    return kind, name


def _terminated_signature(pod: Any) -> list[tuple[str, int, dict]]:
    """Pod 의 모든 container 중 lastState/state 가 terminated 이고 exit_code != 0 인 항목을 반환.
    반환: [(container_name, restart_count, terminated_dict), ...]
    """
    out: list[tuple[str, int, dict]] = []
    for cs in (pod.status.container_statuses or []) + (pod.status.init_container_statuses or []):
        for state in (
            (cs.state.terminated if cs.state else None),
            (cs.last_state.terminated if cs.last_state else None),
        ):
            if state and state.exit_code is not None and state.exit_code != 0:
                out.append((
                    cs.name,
                    cs.restart_count or 0,
                    {
                        "exit_code": int(state.exit_code),
                        "reason": state.reason or "Error",
                        "started_at": state.started_at.isoformat() if state.started_at else None,
                        "finished_at": state.finished_at.isoformat() if state.finished_at else None,
                    },
                ))
                break  # state vs last_state 둘 다 잡히면 한 번만
    return out


class HubClient:
    """signal.emit 호출 전용 thin client. caller_token + X-Cell-Id 강제."""

    def __init__(self, cell_id: str) -> None:
        self.cell_id = cell_id
        self.token = _mint_caller_token()
        self.http = httpx.Client(timeout=HUB_TIMEOUT)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "X-Cell-Id": self.cell_id,
        }

    def emit(self, body: dict) -> None:
        try:
            r = self.http.post(f"{HUB_URL}/signal.emit", json=body, headers=self._headers())
        except httpx.HTTPError as e:
            LOG.warning("signal.emit transport error: %s", e)
            return
        if r.status_code == 401:
            # 토큰 만료 가능성 — 한 번 재발급 후 retry.
            LOG.info("signal.emit 401 — token 재발급 시도")
            try:
                self.token = _mint_caller_token()
            except RuntimeError as e:
                LOG.warning("token 재발급 실패: %s", e)
                return
            try:
                r = self.http.post(f"{HUB_URL}/signal.emit", json=body, headers=self._headers())
            except httpx.HTTPError as e:
                LOG.warning("signal.emit retry transport error: %s", e)
                return
        if r.status_code >= 400:
            LOG.warning("signal.emit failed (%s): %s", r.status_code, r.text[:300])
        else:
            target = (body.get("detail") or {}).get("raw", {}).get("target")
            LOG.info("emitted signal for %s", target)


def _build_signal_body(pod: Any, container: str, restart_count: int, term: dict,
                       owner_kind: str | None, owner_name: str | None) -> dict:
    ns = pod.metadata.namespace
    pod_name = pod.metadata.name
    target = f"{ns}/{pod_name}/{container}"
    title = (
        f"Pod {target} exited {term['exit_code']} ({term['reason']})"
        + (f" — restart #{restart_count}" if restart_count else "")
    )
    message = (
        f"Container '{container}' in pod {ns}/{pod_name} terminated with "
        f"exit code {term['exit_code']} (reason: {term['reason']}). "
        f"restart_count={restart_count}."
    )
    return {
        "type": "infra.pod_failed",
        "title": title,
        "severity": "error",
        "origin": {"emitter": EMITTER},
        "detail": {
            "message": message,
            "raw": {
                "target": target,
                "exit_code": term["exit_code"],
                "reason": term["reason"],
                "namespace": ns,
                "pod": pod_name,
                "container": container,
                "restart_count": restart_count,
                "owner_kind": owner_kind or "",
                "owner_name": owner_name or "",
                "node": pod.spec.node_name or "",
                "started_at": term.get("started_at"),
                "finished_at": term.get("finished_at"),
            },
        },
    }


def _is_sandbox_teardown_sigkill(
    pod: Any,
    restart_count: int,
    term: dict,
    owner_kind: str | None,
    owner_name: str | None,
) -> bool:
    return (
        term["exit_code"] == SIGKILL_EXIT_CODE
        and term["reason"] != OOMKILLED_REASON
        and restart_count == 0
        and owner_kind is None
        and owner_name is None
        and (pod.metadata.name or "").startswith(SANDBOX_POD_PREFIX)
    )


class Watcher:
    def __init__(self) -> None:
        _load_kube()
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self.hub = HubClient(CELL_ID)
        # dedup: (pod_uid, container) 가 한 번 신고되면 같은 pod 의 같은 컨테이너는 침묵.
        self.seen: set[tuple[str, str]] = set()
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def _is_excluded(self, pod: Any, owner_kind: str | None) -> bool:
        if owner_kind in EXCLUDED_OWNER_KINDS:
            return True
        for o in (pod.metadata.owner_references or []):
            if o.kind in EXCLUDED_OWNER_KINDS:
                return True
        return False

    def _seed_or_emit(self, pod: Any, *, emit: bool) -> None:
        uid = pod.metadata.uid
        if uid is None:
            return
        owner_kind, owner_name = _resolve_owner(self.apps, pod)
        if self._is_excluded(pod, owner_kind):
            return
        for container, restart, term in _terminated_signature(pod):
            # graceful SIGTERM(143) + restart_count==0 은 정상 종료 — pod_failed 에서 제외.
            if term["exit_code"] == SIGTERM_EXIT_CODE and restart == 0:
                continue
            # rollout SIGKILL(137) + restart_count==0 + Deployment 는 교체 잔재 — OOM 은 제외하지 않음.
            if (
                term["exit_code"] == SIGKILL_EXIT_CODE
                and term["reason"] != OOMKILLED_REASON
                and restart == 0
                and owner_kind == DEPLOYMENT_OWNER_KIND
            ):
                continue
            # sandbox TTL/destroy teardown: standalone sandbox Pod 가 grace 를 넘겨 SIGKILL 됨.
            if _is_sandbox_teardown_sigkill(pod, restart, term, owner_kind, owner_name):
                continue
            key = (uid, container)
            with self.lock:
                if key in self.seen:
                    continue
                self.seen.add(key)
            if emit:
                body = _build_signal_body(pod, container, restart, term, owner_kind, owner_name)
                self.hub.emit(body)

    def _drop_pod(self, pod: Any) -> None:
        uid = pod.metadata.uid
        if uid is None:
            return
        with self.lock:
            self.seen = {(u, c) for (u, c) in self.seen if u != uid}

    def seed_existing(self) -> str:
        """기존 Pod 들을 list 해서 캐시만 시드 (emit=False) 하고 resourceVersion 반환."""
        pods = self.core.list_pod_for_all_namespaces(watch=False)
        for pod in pods.items:
            self._seed_or_emit(pod, emit=False)
        rv = pods.metadata.resource_version
        LOG.info("seeded %d pods (resource_version=%s, cell=%s)", len(pods.items), rv, CELL_ID)
        return rv

    def watch_loop(self) -> None:
        rv = self.seed_existing()
        while not self.stopped.is_set():
            w = watch.Watch()
            try:
                for event in w.stream(
                    self.core.list_pod_for_all_namespaces,
                    resource_version=rv,
                    timeout_seconds=300,
                ):
                    if self.stopped.is_set():
                        w.stop()
                        return
                    pod = event["object"]
                    rv = pod.metadata.resource_version or rv
                    et = event["type"]
                    if et in ("ADDED", "MODIFIED"):
                        self._seed_or_emit(pod, emit=True)
                    elif et == "DELETED":
                        self._drop_pod(pod)
            except ApiException as e:
                if e.status == 410:
                    LOG.info("watch expired (410), re-listing")
                    rv = self.seed_existing()
                    continue
                LOG.warning("watch ApiException %s: retrying in %ss", e.status, RETRY_SECONDS)
                time.sleep(RETRY_SECONDS)
            except Exception as e:
                LOG.warning("watch error %r: retrying in %ss", e, RETRY_SECONDS)
                time.sleep(RETRY_SECONDS)
            finally:
                w.stop()

    def stop(self) -> None:
        self.stopped.set()


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    w = Watcher()

    def _shutdown(signum: int, _frame: Any) -> None:
        LOG.info("received signal %s, stopping", signum)
        w.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    w.watch_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
