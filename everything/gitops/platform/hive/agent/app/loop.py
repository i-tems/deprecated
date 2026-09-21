"""Agent Loop — 전 hive 단일. 모든 cell을 라운드로빈 폴링하고 worker Job을 spawn.

Worker는 별도 Pod에서 claude 1회 실행 후 종료. session resume은 hub의 entity.session_id로.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from functools import partial

from fastapi import FastAPI
from kubernetes import client as k8s_client
from kubernetes import config as kube_config
from kubernetes import watch as k8s_watch

from .config import (
    HUB_URL, POLL_INTERVAL,
    SPECS_DIR, RUNTIME_SPECS_DIR, EXEC_TIER_DEFAULT, log, resolve_model,
)
from .hub_client import HubClient
from .hub_client_bootstrap import mint_caller_token
from .k8s_jobs import (
    NAMESPACE, build_worker_job, create_job, job_name,
    list_active_jobs, reap_finished,
)
from .metrics import (
    hive_agent_active_jobs, hive_agent_cycle_duration_seconds,
    hive_agent_cycle_total, hive_agent_reap_total, hive_agent_spawn_total,
    start_metrics_server,
)
from .models import Action, LoopContext, action_entity_id, entity_type_of, id_field_for, session_type_of
from .prompt_builders import PromptFactory
from .runtime import log_usage
from .session_store import SessionStore
from .work_finder import find_all_work


# FastAPI app — uvicorn 이 별도 프로세스로 띄움 (start-agent.sh 에서 `uvicorn app.loop:app`).
# wake push 는 hub wake_bus long-poll(_watch_cell_wake) 로만 전달된다.
app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent-api"}


_cell_watchers: dict[str, threading.Thread] = {}


def _watch_cell_wake(cell_id: str, wake_event: threading.Event, stop_event: threading.Event) -> None:
    """cell 단위 hub long-poll. 새 issue/project 생성·status_change 등 push notify 즉시 응답
    → main wake_event.set → 다음 사이클 즉시 실행 (POLL_INTERVAL 대기 우회).

    hub 가 issue.create/project.create/status_change 시점에 `cell:<cell_id>` key 로
    `wake_bus.notify` 호출. timeout 응답은 그냥 다음 iter (자동 재호출).
    """
    while not stop_event.is_set():
        client = _make_client(cell_id)
        try:
            resp = client.api(
                "wake.wait_for_change",
                {"entity_type": "cell", "entity_id": cell_id, "timeout": 60.0},
                timeout=70,
            )
        except Exception as e:
            log.debug(f"[loop.wake.cell] {cell_id} long-poll 실패, 2s 뒤 재시도: {e}")
            time.sleep(2)
            continue
        reason = ((resp or {}).get("data") or {}).get("wake_reason")
        if reason in ("notified", "pending"):
            wake_event.set()
        # timeout → 같은 cell 로 자동 재호출.


def _ensure_cell_watchers(
    cells: list[dict], wake_event: threading.Event, stop_event: threading.Event,
) -> None:
    """cell list 의 새 cell 마다 watcher thread 1개 spawn. cell 삭제는 stop_event
    가 set 될 때 까지 thread 유지 (재시작 시 자연 정리)."""
    for c in cells:
        cid = c.get("cell_id")
        if not cid or cid in _cell_watchers:
            continue
        t = threading.Thread(
            target=_watch_cell_wake, args=(cid, wake_event, stop_event),
            name=f"loop-wake-cell-{cid}", daemon=True,
        )
        t.start()
        _cell_watchers[cid] = t
        log.info(f"[loop] cell watcher 시작: {cid}")


def _watch_jobs_for_wake(wake_event: threading.Event, stop_event: threading.Event) -> None:
    """worker Job이 완료(succeeded/failed)되면 wake_event를 set.

    _watch_cell_wake(wake_bus long-poll)가 trigger되지 않는 경로(예: 워커가
    status 전환 없이 조용히 끝나는 경우)에도 다음 사이클을 즉시 돌려 멀티-phase
    issue 지연을 없앤다.
    """
    api = k8s_client.BatchV1Api()
    while not stop_event.is_set():
        try:
            w = k8s_watch.Watch()
            for ev in w.stream(
                api.list_namespaced_job,
                namespace=NAMESPACE,
                label_selector="app=hive-agent-worker",
                timeout_seconds=60,
            ):
                if stop_event.is_set():
                    w.stop()
                    break
                obj = ev.get("object")
                if not obj:
                    continue
                st = getattr(obj, "status", None) or k8s_client.V1JobStatus()
                if (st.succeeded or 0) >= 1 or (st.failed or 0) >= 1:
                    wake_event.set()
        except Exception as e:
            log.warning(f"[loop.wake] k8s job watch 재시작: {e}")
            time.sleep(2)


# agent-loop system 토큰은 startup 에서 1회만 발급되고 메인 루프에 재발급 경로가
# 없다 (HubClient 도 401 재발급 없음). 짧은 TTL 이면 그 시점에 토큰이 만료돼 모든
# hub 호출이 401 → _list_active_cells 가 예외를 삼키고 [] 반환 → 파드는 1/1
# Running 인 채 전 cell 워커 spawn 이 멈춘다 (침묵의 hive-wide 정지; 24h TTL 일
# 때 정확히 24h 마다 재발, NESS-ISSUE-5 정지 원인). loop 파드는 재시작마다 새로
# 발급하므로 실질 수명은 파드 수명뿐 — 사실상 무만료로 둔다. hub /auth.caller_token
# 은 expiry 를 clamp 하지 않으므로(app/auth.py) 이 값을 그대로 honor 한다. 진짜
# no-exp(exp 미발급)는 hub 인증 계약·보안 변경이라 범위 밖.
_AGENT_LOOP_TOKEN_TTL_SECONDS = 100 * 365 * 24 * 3600  # ~100y = 사실상 무만료


def _bootstrap_agent_loop_token() -> str:
    """agent-loop의 system principal 토큰을 hub bootstrap path에서 발급받는다.

    실패 시 RuntimeError → pod 재시작 (fail-fast). 토큰 없이는 HubClient
    인스턴스 생성 자체가 불가능하므로 agent-loop이 일을 못 한다.
    """
    host = os.environ.get("HOSTNAME") or "unknown"
    token = mint_caller_token(
        hub_url=HUB_URL,
        principal_type="system",
        principal_id=f"system:agent-loop:{host}",
        expiry_seconds=_AGENT_LOOP_TOKEN_TTL_SECONDS,
        logger=log,
    )
    if not token:
        raise RuntimeError("agent-loop bootstrap caller_token 발급 실패 — HUB_INTERNAL_TOKEN 또는 hub 가용성 확인")
    log.info(f"[loop] agent-loop principal token 발급 완료 (host={host})")
    return token


_AGENT_LOOP_TOKEN: str | None = None


def _make_client(cell_id: str) -> HubClient:
    return HubClient(hub_url=HUB_URL, cell_id=cell_id, logger=log, caller_token=_AGENT_LOOP_TOKEN)


def _list_active_cells() -> list[dict]:
    """hub의 cell.list로 active + repo_url 있는 cell만 가져온다."""
    # cell.list 는 cell-exempt 경로(`/cell.*`, CellMiddleware) — X-Cell-Id 헤더가
    # 검증되지 않는다. caller cell sentinel "_meta" 로 의도 명시 (묵시 "default" 폐기).
    client = _make_client("_meta")
    try:
        resp = client.api("cell.list", {"status": "active"})
    except Exception as e:
        log.warning(f"[loop] cell.list 실패: {e}")
        return []
    cells = resp.get("data", {}).get("cells", []) or []
    out: list[dict] = []
    skipped: list[str] = []
    for cell in cells:
        if cell.get("deleted"):
            continue
        if not (cell.get("repo_url") or "").strip():
            skipped.append(cell.get("cell_id", "?"))
            continue
        out.append(cell)
    if skipped:
        log.warning(f"[loop] repo_url 미설정 cell 스킵: {skipped}")
    return out


def _make_ctx(client: HubClient) -> LoopContext:
    """find_all_work만을 위한 가벼운 LoopContext. claude 실행 의존성은 안 들어감."""
    return LoopContext(
        client=client,
        session_store=SessionStore(max_uses=1_000_000),  # 사용 안 함
        prompt_factory=PromptFactory(hub_url=HUB_URL, specs_dir=SPECS_DIR, runtime_specs_dir=RUNTIME_SPECS_DIR),
        resolve_model=resolve_model,
        log=log,
        exec_tier_default=EXEC_TIER_DEFAULT,
        log_usage=partial(log_usage, logger=log),
    )


def _mint_caller_token(client: HubClient, *, name: str, cell_id: str, action: Action, traceparent: str) -> str | None:
    eid = action_entity_id(action) or ""
    et = entity_type_of(action.entity)
    session_type = session_type_of(action.entity) if action.type == "progress" else action.type
    claims = {
        "principal_type": "worker",
        "principal_id": f"worker:{name}",
        "cell_id": cell_id,
        "session_type": session_type,
    }
    if et == "issue":
        claims["issue_id"] = eid
    try:
        resp = client.api("auth.caller_token", claims, traceparent=traceparent)
    except Exception as e:
        log.warning(f"[loop] caller_token 발급 실패 cell={cell_id} job={name}: {e}")
        return None
    if (resp or {}).get("status") != "ok":
        log.warning(f"[loop] caller_token 응답 비정상 cell={cell_id} job={name}: {resp}")
        return None
    return (resp.get("data") or {}).get("token")


# Issue(8-status 워커 모델) + 컨테이너(Project/Initiative, 통합 5-status) status 의
# entity-agnostic union — _still_actionable 이 entity type 무관하게 spawn 직전 fresh
# status 가 이 집합에 드는지만 본다 (안 들면 race 로 보고 spawn skip). status 명이
# 겹치는 waiting 은 양쪽 동의어라 안전. work_finder 가 실제 enqueue 하는 status 와 일치:
#   Issue:  todo/running/waiting/cleanup. terminal(done/cancelled)·error 는 미픽업이라
#           제외 — fresh 가 그리 되면 race(종결됨)이므로 skip 이 옳다.
#   컨테이너: active(self-action) + waiting(pending 댓글 reply). terminal(done/archive)·
#           backlog 는 미픽업이라 제외 (race 로 그리 되면 skip).
# terminal 제외는 INFRA-ISSUE-263 (terminal reply 자동 픽업 제거)과 일관.
_VALID_STATUS_FOR_ACTION: dict[str, set[str]] = {
    "progress": {"todo", "running", "waiting", "cleanup", "active"},
}


def _still_actionable(hub_client: HubClient | None, action: Action) -> bool:
    """spawn 직전 entity status·hold 재확인. find_all_work snapshot 과 spawn 사이의
    race (예: 사람이 waiting 으로 돌리거나 hold 를 검) 로 인한 worker bootstrap 낭비를
    차단."""
    if hub_client is None:
        return True
    valid = _VALID_STATUS_FOR_ACTION.get(action.type)
    if not valid:
        return True
    entity_type = entity_type_of(action.entity)
    eid = action_entity_id(action)
    if not entity_type or not eid:
        return True
    try:
        resp = hub_client.api(f"{entity_type}.get", {id_field_for(entity_type): eid})
    except Exception as e:
        log.debug(f"[loop] pre-spawn fetch 실패 action={action.type} entity={eid}: {e}")
        return True  # 보수적: API 실패 시 그냥 spawn 진행
    data = (resp or {}).get("data") or {}
    cur = data.get("status")
    if cur not in valid:
        log.info(f"[loop] pre-spawn skip action={action.type} entity={eid} status={cur}")
        return False
    # hold race: work_finder snapshot 은 held 를 제외하지만, snapshot 이후 사람이 hold 를
    # 걸면 그 사이 spawn 이 진행될 수 있다. fresh hold 를 재검사해 held 면 spawn skip —
    # 개인 세션 수동작업 보호 (work_finder spawn 게이트·worker cycle 게이트와 동일 계약,
    # INFRA-ISSUE-187).
    if data.get("hold"):
        log.info(f"[loop] pre-spawn skip action={action.type} entity={eid} hold=true")
        return False
    return True


def _spawn_for(
    batch_api: k8s_client.BatchV1Api,
    cell_id: str,
    action: Action,
    active_names: set[str],
    *,
    repo_url: str | None = None,
    hub_client: HubClient | None = None,
) -> bool:
    eid = action_entity_id(action)
    if not eid:
        return False
    name = job_name(cell_id, action.type, eid)
    if name in active_names:
        return False
    if not _still_actionable(hub_client, action):
        return False
    # 한 번의 spawn = 한 trace. mint 호출과 worker job 모두 이 trace_id를 공유해
    # "spawn → 워커의 모든 hub 호출"이 같은 trace로 묶인다.
    trace_id = secrets.token_hex(16)
    spawn_span_id = secrets.token_hex(8)
    traceparent = f"00-{trace_id}-{spawn_span_id}-01"
    caller_token = None
    if hub_client is not None:
        caller_token = _mint_caller_token(hub_client, name=name, cell_id=cell_id, action=action, traceparent=traceparent)
    job = build_worker_job(
        cell_id=cell_id,
        action={"type": action.type, "entity": action.entity, "priority": action.priority},
        name=name,
        repo_url=repo_url,
        caller_token=caller_token,
        traceparent=traceparent,
    )
    if create_job(batch_api, job):
        active_names.add(name)
        hive_agent_spawn_total.labels(action_type=action.type).inc()
        log.info(f"[loop] spawn cell={cell_id} action={action.type} entity={eid} job={name} trace={trace_id[:12]} token={'yes' if caller_token else 'no'}")
        return True
    return False


def _process_cell(batch_api: k8s_client.BatchV1Api, cell: dict, active_names: set[str]) -> int:
    cell_id = cell["cell_id"]
    repo_url = cell.get("repo_url")
    client = _make_client(cell_id)
    ctx = _make_ctx(client)

    class _NoFlag:
        def unlink(self, missing_ok=True):
            pass

    try:
        actions = find_all_work(ctx, exclude_ids=set(), message_flag=_NoFlag())
    except Exception as e:
        log.error(f"[loop] find_all_work({cell_id}) 실패: {e}", exc_info=True)
        return 0

    # priority 오름차순: issue cleanup(0) → issue progress(1) → project progress(2).
    # K8s Job 생성 순서가 priority 를 반영해 cleanup 이 가장 먼저 spawn → workspace 빠르게 해제.
    actions.sort(key=lambda a: a.priority)

    n = 0
    for action in actions:
        if _spawn_for(batch_api, cell_id, action, active_names, repo_url=repo_url, hub_client=client):
            n += 1
    return n


def main() -> None:
    global _AGENT_LOOP_TOKEN
    kube_config.load_incluster_config()
    batch_api = k8s_client.BatchV1Api()
    log.info(f"[loop] 시작 ns={NAMESPACE} hub={HUB_URL} poll={POLL_INTERVAL}s")
    _AGENT_LOOP_TOKEN = _bootstrap_agent_loop_token()
    start_metrics_server()  # :8002/metrics — PodMonitor 가 scrape

    wake_event = threading.Event()
    stop_event = threading.Event()
    threading.Thread(
        target=_watch_jobs_for_wake, args=(wake_event, stop_event),
        name="loop-job-watch", daemon=True,
    ).start()

    while True:
        cycle_start = time.monotonic()
        result = "ok"
        try:
            cells = _list_active_cells()
            # 새 cell 마다 long-poll watcher 등록 — push wake 활성. polling 은 fallback.
            _ensure_cell_watchers(cells, wake_event, stop_event)
            active_jobs = list_active_jobs(batch_api)
            active_names = {j.metadata.name for j in active_jobs}
            hive_agent_active_jobs.set(len(active_jobs))

            spawned = 0
            for cell in cells:
                spawned += _process_cell(batch_api, cell, active_names)

            reaped = reap_finished(batch_api)
            if reaped:
                hive_agent_reap_total.inc(reaped)

            if spawned == 0 and not active_jobs and reaped == 0:
                log.info("[loop] idle")
            elif spawned or reaped:
                log.info(f"[loop] spawn={spawned} active={len(active_jobs)} reap={reaped} dur={int((time.monotonic()-cycle_start)*1000)}ms")
        except Exception as e:
            result = "error"
            log.error(f"[loop] cycle 예외: {e}", exc_info=True)
        finally:
            hive_agent_cycle_duration_seconds.observe(time.monotonic() - cycle_start)
            hive_agent_cycle_total.labels(result=result).inc()

        # wake로 깨어났으면 다음 사이클 즉시 시작. 아니면 POLL_INTERVAL 대기.
        woke = wake_event.wait(POLL_INTERVAL)
        if woke:
            wake_event.clear()
            log.info("[loop] woken — 다음 사이클 즉시 실행")


if __name__ == "__main__":
    main()
