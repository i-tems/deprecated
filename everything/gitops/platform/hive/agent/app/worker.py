"""Worker entrypoint — agent-loop이 spawn한 K8s Job 안에서 실행되는 entity-수명 프로세스.

CELL_ID + ACTION 환경변수로 작업을 받아 Claude CLI 를 entity 의 active 수명 동안 연속
호출한다. session_id는 in-memory 로 들고 있어 claude --resume 으로 매 cycle 같은 대화
를 이어간다. pod crash 시 hub 의 entity.session_id + last_prompt_at 으로 복구.

cycle:
  1. entity 재조회 (status terminal 이면 종료)
  2. pre_dispatch → 프롬프트 빌드
  3. claude 실행 (--resume 사용)
  4. post_dispatch (state 검증만 — git push / PR / workspace 정리는 AI 가 직접 수행)
  5. 다음 외부 wake 이벤트 (사람 댓글 / 외부 status 변화) 까지 polling sleep
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from functools import partial

from .activity_relay import ActivityRelay
from .config import (
    EXEC_CWD, EXEC_TIER_DEFAULT,
    POLL_INTERVAL, RUNTIME_SPECS_DIR, SESSION_MAX_TURNS,
    SESSION_TIMEOUT, SPECS_DIR, log, resolve_model,
)
from .hub_client import HubClient
from .models import Action, LoopContext, WorkResult, action_entity_id, entity_type_of, id_field_for
from .phase_handlers import post_dispatch, post_turn_guard, pre_dispatch
from .prompt_builders import PromptFactory
from .runtime import log_usage, make_agent_session, run_agent
from .session_store import SessionStore
from .telemetry import get_langfuse_client


_HEARTBEAT_INTERVAL_S = 5
# hub TTL 30s (6회). 그 이상 연속 실패는 hub 측에서 워커가 사라진 것으로 처리되므로
# 운영자 가시성을 위해 warning 격상. 이후에도 같은 주기로 반복.
_HEARTBEAT_WARN_AFTER = 6
# 401 Unauthorized 가 N회 연속 발생하면 token 만료로 판단 — worker self-exit 후
# agent-loop 의 backoff 가 새 worker (새 token) 으로 재시도. 영구 worker 모델에서
# 24h 후 token expiry stuck 방지.
_HEARTBEAT_AUTH_FAIL_LIMIT = 6


class HeartbeatThread:
    """worker 가 hub 에 5초마다 살아있다고 통보. set_phase 호출 시 즉시 1회 발송.

    daemon thread 라 메인 흐름을 막지 않으며, 실패는 silent skip — hub 일시 장애가
    worker 자체를 죽이지 않게 한다. 단 연속 실패가 hub TTL 을 넘으면 warning 으로
    격상해 pod logs 에서 즉시 보이도록 한다 (UI 에서는 워커가 stale 로 보임).
    """

    def __init__(self, client: HubClient, logger):
        self._client = client
        self._log = logger
        self._stop = threading.Event()
        self._phase: str | None = None
        self._note: str | None = None
        self._session_id: str | None = None
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._consecutive_auth_failures = 0
        self._auth_fatal = False
        self._thread = threading.Thread(target=self._run, name="hive-heartbeat", daemon=True)

    def has_auth_fatal(self) -> bool:
        """token 만료로 판단된 상태. main loop 가 이 시점에 worker 종료해야 한다."""
        return self._auth_fatal

    def start(self) -> None:
        self._thread.start()

    def set_phase(self, phase: str | None, note: str | None = None) -> None:
        with self._lock:
            self._phase = phase
            self._note = note
        self._send_once()

    def set_session_id(self, session_id: str | None) -> None:
        """claude 가 session_id 발급한 직후 호출. UI 에서 Langfuse 트레이스 링크로 직결."""
        with self._lock:
            self._session_id = session_id
        self._send_once()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._client.api("worker.clear", {}, timeout=5)
        except Exception:
            pass

    def _send_once(self) -> None:
        with self._lock:
            payload = {"phase": self._phase, "note": self._note, "session_id": self._session_id}
        try:
            self._client.api("worker.heartbeat", payload, timeout=5)
        except Exception as e:
            self._consecutive_failures += 1
            is_auth = "401" in str(e) or "Unauthorized" in str(e)
            if is_auth:
                self._consecutive_auth_failures += 1
                if self._consecutive_auth_failures >= _HEARTBEAT_AUTH_FAIL_LIMIT and not self._auth_fatal:
                    self._auth_fatal = True
                    self._log.error(
                        f"[heartbeat] 401 Unauthorized {self._consecutive_auth_failures}회 — "
                        "token 만료 판단. worker 종료 후 agent-loop 재시도가 새 token 발급."
                    )
            n = self._consecutive_failures
            # WARN_AFTER 도달 시점 + 이후 같은 주기마다 warning.
            if n == _HEARTBEAT_WARN_AFTER or (n > _HEARTBEAT_WARN_AFTER and n % _HEARTBEAT_WARN_AFTER == 0):
                self._log.warning(f"[heartbeat] {n}회 연속 실패 — UI 에서 워커가 stale 로 보일 가능성 (err={e})")
            else:
                self._log.debug(f"[heartbeat] send failed (#{n}): {e}")
            return
        if self._consecutive_failures:
            self._log.info(f"[heartbeat] 회복 — 연속 실패 {self._consecutive_failures}회 후 정상")
            self._consecutive_failures = 0
            self._consecutive_auth_failures = 0

    def _run(self) -> None:
        while not self._stop.wait(_HEARTBEAT_INTERVAL_S):
            self._send_once()


def _branch_name(entity_type: str | None, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    return f"{entity_type or 'issue'}/{entity_id}"


def _setup_mcp_config(cell_id: str) -> str | None:
    """Hub MCP 서버를 Claude CLI에 노출시키는 mcp-config 파일 생성.

    HUB_CALLER_TOKEN(JWT)을 박아 streamable HTTP 로 hub의 ``/mcp/`` 에 연결한다.
    이 파일이 없으면 워커 LLM은 capability를 직접 호출할 도구가 없어 Bash + curl
    추측 호출로 폴백한다(엔드포인트 hallucination → 404 다발).

    cell-agnostic transport — 매 invoke 마다 워커 LLM 이 ``cell=<자기 cell_id>``
    인자를 명시한다 (워커 pod 의 ``CELL_ID`` env 가 prompt 컨텍스트로 주입됨).
    server entry 도 cell 별이 아닌 단일 ``hive`` 이름.

    파일은 entity-별 NFS workspace(/data/workspaces/<cell>/<entity>)에 0600으로
    쓴다 — JWT가 들어 있어 노출 차단. entity-별 디렉토리라 다른 entity 워커와
    격리되고, 전체 /data 마운트라 subPath stale 핸들(ESTALE)도 없다.
    """
    hub_url = os.environ.get("HUB_URL", "").strip()
    token = os.environ.get("HUB_CALLER_TOKEN", "").strip()
    if not hub_url or not token:
        log.warning("[worker] MCP config 생략 — HUB_URL/HUB_CALLER_TOKEN 미설정")
        return None
    server_name = "hive"
    config = {
        "mcpServers": {
            server_name: {
                "type": "http",
                "url": f"{hub_url.rstrip('/')}/mcp/",
                "headers": {
                    "Authorization": f"Bearer {token}",
                },
            }
        }
    }
    # subPath /work 마운트 제거됨 — entity workspace(전체 /data 마운트 하위)에 둔다.
    # WORKSPACE_NFS_PATH 는 k8s_jobs 가 항상 set (repo_url 유무 무관).
    ws = os.environ.get("WORKSPACE_NFS_PATH") or f"/data/cells/{cell_id}"
    path = os.path.join(ws, "mcp-config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f)
    os.chmod(path, 0o600)
    log.info(
        f"[worker] MCP config written: {path} ({server_name} → {hub_url}/mcp/, "
        f"cell-agnostic — cell_id={cell_id} 는 매 invoke 인자로 명시)"
    )
    return path


def _bootstrap_workspace(entity_type: str | None = None, entity_id: str | None = None) -> None:
    """CELL_REPO_URL이 있으면 bare repo cache 위에 worktree 를 add 하여 issue 브랜치 작업공간 마련.

    Layout (NFS):
      /data/cells/<cell>/repos/cell.git              # bare clone (cell 당 1개, 공유)
      /data/workspaces/<cell>/<entity>/cell          # worktree (issue/<id> 브랜치)

    pod 안에서 전체 /data 마운트 하위 절대경로로 접근한다 (subPath 마운트 아님 —
    subPath inode 고정 시 워크스페이스 out-of-band 삭제·재생성으로 ESTALE 영구
    stuck 이 발생했던 NESS-ISSUE-3 회귀 차단. 상세는 k8s_jobs._build_job_spec 주석).

    repo_url 미설정이면 NFS legacy 경로를 그대로 사용 (no-op).
    {workspace}/.gitconfig를 GIT_CONFIG_GLOBAL로 사용 — entity-별이라 /data/shared NFS의
    ~/.gitconfig pod 간 경합을 회피하고, 전체 /data 마운트라 stale 핸들도 없다.
    bare clone 은 --filter=blob:none 으로 commit/tree만 받고 blob은 lazy fetch.
    """
    repo_url = os.environ.get("CELL_REPO_URL")
    if not repo_url:
        return

    cell_id = os.environ["CELL_ID"]  # main() 진입 시 None 검증 통과한 후에만 호출됨 (worker.main:421)
    nfs_workspace = os.environ.get("WORKSPACE_NFS_PATH", "")
    work_dir = os.environ.get("EXEC_CWD") or (f"{nfs_workspace}/cell" if nfs_workspace else "")
    token = os.environ.get("GITHUB_TOKEN", "").strip()

    # gitconfig·credentials 는 entity workspace(전체 /data 마운트 하위)에 둔다.
    # nfs_workspace 는 k8s_jobs 가 repo_url 워커에 항상 set.
    os.makedirs(nfs_workspace, exist_ok=True)
    os.environ["GIT_CONFIG_GLOBAL"] = f"{nfs_workspace}/.gitconfig"

    if token:
        cred_file = f"{nfs_workspace}/.git-credentials"
        with open(cred_file, "w") as f:
            f.write(f"https://x-access-token:{token}@github.com\n")
        os.chmod(cred_file, 0o600)
        subprocess.run(
            ["git", "config", "--global", "credential.helper", f"store --file={cred_file}"],
            check=True,
        )
    else:
        log.warning("GITHUB_TOKEN 미설정 — public repo만 clone 가능")

    subprocess.run(["git", "config", "--global", "user.name", "hive-agent"], check=False)
    subprocess.run(["git", "config", "--global", "user.email", "agent@hive.local"], check=False)
    subprocess.run(["git", "config", "--global", "init.defaultBranch", "main"], check=False)
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", "*"], check=False)

    bare_dir = f"/data/cells/{cell_id}/repos/cell.git"
    branch = _branch_name(entity_type, entity_id)
    if branch:
        os.environ["TASK_BRANCH"] = branch  # issue-clone helper가 사용

    # bare repo (cell 당 1개) — 없으면 lazy clone.
    if not os.path.isdir(bare_dir):
        os.makedirs(os.path.dirname(bare_dir), exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--bare", "--filter=blob:none", "--no-tags", repo_url, bare_dir],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.error(f"bare clone 실패: {result.stderr.strip()}")
            raise RuntimeError(f"git clone --bare failed: {result.stderr.strip()}")
        log.info(f"cell bare repo cloned: {repo_url} → {bare_dir}")

    # bare clone 의 default fetch refspec 는 refs/heads/* 만 채우고 refs/remotes/origin/*
    # 는 만들지 않는다 → worktree add 의 `origin/main` 참조 실패. normal clone 처럼
    # remote-tracking refs 를 만들도록 refspec 재설정 (idempotent).
    subprocess.run(
        ["git", "-C", bare_dir, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
        capture_output=True,
    )
    # 최신 origin 받아오기 — 모든 worktree 가 즉시 본다.
    subprocess.run(
        ["git", "-C", bare_dir, "fetch", "--prune", "--no-tags", "origin"],
        capture_output=True,
    )

    # worktree — NFS 절대경로로 등록해 bare repo 메타데이터가 pod-agnostic.
    # worktree_target == EXEC_CWD (둘 다 /data/workspaces/<cell>/<entity>/cell,
    # 전체 /data 마운트 하위 동일 경로 — subPath 별칭 없음).
    worktree_target = f"{nfs_workspace}/cell" if nfs_workspace else work_dir

    # 비정상 종료(워커 crash·pod kill·SDK stale)한 이전 워커는 공유 PVC 의 bare
    # repo 에 worktree 등록을 남긴다. gitdir 포인터가 깨져 `prunable` 이 되면
    # 다음 워커의 `git worktree add -B <branch>` 가 "branch already used by
    # worktree" 로 영구 실패한다 (모든 재시도 동일 → entity stuck, cell 전
    # entity 가 같은 landmine). 진입 시 항상 prune 해 깨진 등록을 청소한다
    # (idempotent — 정상 worktree 엔 영향 없음).
    subprocess.run(["git", "-C", bare_dir, "worktree", "prune"], capture_output=True)

    if not os.path.exists(os.path.join(worktree_target, ".git")):
        os.makedirs(os.path.dirname(worktree_target), exist_ok=True)
        ls = subprocess.run(
            ["git", "-C", bare_dir, "ls-remote", "--heads", "origin", branch or ""],
            capture_output=True, text=True,
        )
        base_ref = f"origin/{branch}" if (branch and ls.returncode == 0 and ls.stdout.strip()) else "origin/main"

        def _worktree_add() -> subprocess.CompletedProcess:
            cmd = ["git", "-C", bare_dir, "worktree", "add"]
            if branch:
                cmd.extend(["-B", branch])
            cmd.extend([worktree_target, base_ref])
            return subprocess.run(cmd, capture_output=True, text=True)

        result = _worktree_add()
        if result.returncode != 0:
            # prune 후에도 실패 = 대상 경로/브랜치가 (prunable 아닌) 등록에
            # 잡혀 있거나 target 경로에 잔존 파일이 있는 dirty 케이스. 충돌
            # worktree 를 강제 제거하고 target 을 비운 뒤 1회 재시도해 self-heal.
            log.warning(f"worktree add 1차 실패 ({result.stderr.strip()}) — 강제 정리 후 재시도")
            subprocess.run(
                ["git", "-C", bare_dir, "worktree", "remove", "--force", worktree_target],
                capture_output=True,
            )
            shutil.rmtree(worktree_target, ignore_errors=True)
            subprocess.run(["git", "-C", bare_dir, "worktree", "prune"], capture_output=True)
            result = _worktree_add()
            if result.returncode != 0:
                log.error(f"worktree add 재시도도 실패: {result.stderr.strip()}")
                raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")
        log.info(f"worktree created: {worktree_target} (branch={branch}, base={base_ref})")
    elif branch:
        # 이전 pod 의 worktree 재사용. origin 에 진척이 있으면 safe ff-merge.
        ff = subprocess.run(
            ["git", "-C", work_dir, "merge", "--ff-only", f"origin/{branch}"],
            capture_output=True, text=True,
        )
        if ff.returncode == 0:
            log.info(f"worktree resumed + ff merged: {branch}")
        else:
            log.info(f"worktree resumed (local preserved): {branch}")


def _sync_cell_config(cell_id: str, work_dir: str) -> None:
    """cell repo 의 `cell.json` 을 PVC 로 미러링.

    cell repo 가 정본 (사람이 PR 로 관리), PVC `/data/cells/<cell>/cell.json` 은
    hub·capability service 가 읽기 전용 캐시로 사용. 동적 회전 자료 (OAuth
    refresh_token 등) 는 cell.json 에 들어 있지 않으므로 덮어쓰기 위험 없음.
    """
    src = os.path.join(work_dir, "cell.json")
    dst_root = f"/data/cells/{cell_id}"
    if os.path.isfile(src):
        os.makedirs(dst_root, exist_ok=True)
        shutil.copy2(src, os.path.join(dst_root, "cell.json"))
        log.info(f"[cfg-sync] {cell_id} ← cell.json")


def _bootstrap_session(client: HubClient, session_store: SessionStore, action: Action) -> tuple[str, str] | None:
    """action → (entity_type, entity_id) 결정 + hub의 entity.session_id / last_prompt_at 로드.

    hub 호출 실패는 fail-fast — exception을 다시 던져 worker.main이 non-zero exit으로
    종료하게 한다. warning 으로 흘려보내고 새 session_id 로 진행하면 "같은 issue 가
    매번 새 세션을 만든다" 는 묵음 손상이 발생. k8s Job은 backoffLimit 안에서
    재시도되므로 transient 실패는 자연 회복된다.

    last_prompt_at 까지 로드해야 재진입 워커가 풀 컨텍스트 대신 델타만 주입한다. 누락
    시 claude --resume 으로 이미 대화 이력을 가졌음에도 sibling/signals/old events 가
    재주입되어 토큰을 낭비한다.
    """
    entity_id = action_entity_id(action)
    entity_type = entity_type_of(action.entity)
    if not entity_id or not entity_type:
        return None

    resp = client.api(f"{entity_type}.get", {f"{entity_type}_id": entity_id})
    data = resp.get("data") or {}
    sid = data.get("session_id")
    last_prompt_at = data.get("last_prompt_at")
    if sid:
        sess = session_store.get_or_create(entity_id)
        with sess.lock:
            sess.session_id = sid
            if last_prompt_at:
                sess.last_prompt_at = last_prompt_at

    return entity_type, entity_id


def _persist_session(
    client: HubClient, *, entity_type: str, entity_id: str,
    session_id: str | None, last_prompt_at: str | None = None,
):
    """session_id + last_prompt_at 를 hub 에 영구화. 실패는 fail-fast — 다음 worker
    invocation 이 잘못된 session_id 를 이어 쓰면 클로드 대화 이력이 어긋난다.

    last_prompt_at 누락 시 다음 워커가 풀 컨텍스트를 재주입한다 (correctness 문제는
    없지만 토큰 낭비).
    """
    endpoint = f"{entity_type}.set_session"
    payload = {f"{entity_type}_id": entity_id, "session_id": session_id}
    if last_prompt_at is not None:
        payload["last_prompt_at"] = last_prompt_at
    client.api(endpoint, payload)


def _escalate_bootstrap_failure(
    client: HubClient,
    *,
    entity_type: str | None,
    entity_id: str | None,
    error_msg: str,
) -> None:
    """bootstrap 실패를 issue/project 의 error 상태 + capability.failed Signal 로 surface.

    이 호출이 없으면 worker 가 그냥 exit 2 하고, agent-loop 이 30 초마다 같은 todo
    issue 를 보고 새 worker 를 무한 spawn 한다 (실측: 6분 7회). status=error 로 전이
    하면 scheduler 의 blocked 분기에 잡혀 spawn 중단.
    """
    if not entity_type or not entity_id:
        return  # 식별 불가 — cascade 막을 길 없음
    tid = entity_id if entity_type == "issue" else None
    if entity_type == "initiative":
        # Initiative 엔 error status·force_update 가 없다 — hold=true 로 agent-loop 자동
        # re-spawn 루프를 끊는다 (사람이 원인 해소 후 hold 해제). 신호는 아래 공통 경로.
        client.api_safe(
            "initiative.update", {"initiative_id": entity_id, "hold": True},
            label="initiative -> hold (bootstrap)",
        )
    else:
        update_fields = {f"{entity_type}_id": entity_id, "status": "error"}
        if entity_type == "issue":
            update_fields["comment"] = f"workspace bootstrap 실패 — agent-loop 재시도 방지 위해 error 로 전이. 원인: {error_msg[:500]}"
        client.api_safe(
            f"{entity_type}.force_update", update_fields,
            issue_id=tid, label=f"{entity_type} -> error (bootstrap)",
        )

    subject = {f"{entity_type}_id": entity_id}
    client.api_safe(
        "signal.emit",
        {
            "type": "capability.failed",
            "severity": "error",
            "title": None,
            "origin": {"emitter": "agent-loop", "phase": "bootstrap"},
            "subject": subject,
            "detail": {
                "message": "agent-loop session execution failed (bootstrap_error)",
                "raw": {"failure_reason": "bootstrap_error", "error": error_msg},
            },
        },
        issue_id=tid,
        label="bootstrap escalation signal 실패",
    )


def main() -> int:
    cell_id = os.environ.get("CELL_ID")
    action_raw = os.environ.get("ACTION")
    if not cell_id or not action_raw:
        log.error("CELL_ID / ACTION env 누락")
        return 2

    action_data = json.loads(action_raw)
    action = Action(
        type=action_data["type"],
        entity=action_data.get("entity"),
        priority=action_data.get("priority", 99),
    )
    log.info(f"[worker] cell={cell_id} action={action.type} entity={action_entity_id(action)}")

    entity_id_for_branch = action_entity_id(action)
    entity_type_for_branch = entity_type_of(action.entity)

    # heartbeat은 workspace 부트스트랩 전에 시작 — clone이 길어져도 UI에 "alive" 보이게.
    client = HubClient(hub_url=os.environ["HUB_URL"], cell_id=cell_id, logger=log)
    heartbeat = HeartbeatThread(client, log)
    heartbeat.start()
    heartbeat.set_phase("bootstrap")

    # AI activity relay — runtime 이 캡처한 text/tool_use/tool_result 를 hub 로
    # push 해 UI 사이드바가 SSE 로 거의 실시간 표시 (PR #146 stdout 채널 대체).
    # entity 식별 불가하면 생성 안 함(relay=None → runtime no-op).
    activity_relay: ActivityRelay | None = None
    if entity_type_for_branch and entity_id_for_branch:
        activity_relay = ActivityRelay(
            client,
            entity_type=entity_type_for_branch,
            entity_id=entity_id_for_branch,
            logger=log,
        )
        activity_relay.start()

    try:
        _bootstrap_workspace(entity_type_for_branch, entity_id_for_branch)
    except Exception as e:
        log.error(f"[worker] workspace 부트스트랩 실패: {e}", exc_info=True)
        _escalate_bootstrap_failure(
            client,
            entity_type=entity_type_for_branch,
            entity_id=entity_id_for_branch,
            error_msg=str(e),
        )
        heartbeat.stop()
        return 2

    work_dir = os.environ.get("EXEC_CWD", "")
    if work_dir and os.path.isdir(work_dir):
        try:
            _sync_cell_config(cell_id, work_dir)
        except Exception as e:
            log.warning(f"[worker] cell config sync 실패 (계속 진행): {e}")

    mcp_config_path = _setup_mcp_config(cell_id)
    if mcp_config_path:
        os.environ["CLAUDE_MCP_CONFIG"] = mcp_config_path

    langfuse = get_langfuse_client(cell_id, log)

    session_store = SessionStore(max_uses=int(os.environ.get("SESSION_MAX_USES", "50")))
    prompt_factory = PromptFactory(
        hub_url=os.environ["HUB_URL"],
        specs_dir=SPECS_DIR,
        runtime_specs_dir=RUNTIME_SPECS_DIR,
    )

    bootstrap = _bootstrap_session(client, session_store, action)

    ctx = LoopContext(
        client=client,
        session_store=session_store,
        prompt_factory=prompt_factory,
        resolve_model=resolve_model,
        log=log,
        exec_tier_default=EXEC_TIER_DEFAULT,
        log_usage=partial(log_usage, logger=log),
    )

    try:
        last_is_error = asyncio.run(_run_cycles(
            ctx=ctx, action=action, log=log, hub_client=client, heartbeat=heartbeat,
            langfuse=langfuse, cell_id=cell_id, mcp_config_path=mcp_config_path,
            bootstrap=bootstrap,
            entity_type_for_branch=entity_type_for_branch,
            entity_id_for_branch=entity_id_for_branch,
            activity_relay=activity_relay,
        ))
    finally:
        if langfuse is not None:
            try:
                langfuse.flush()
            except Exception as e:
                log.warning(f"Langfuse flush 실패: {e}")
        if activity_relay is not None:
            activity_relay.stop()
        heartbeat.stop()

    return 1 if last_is_error else 0


async def _run_cycles(
    *,
    ctx: LoopContext,
    action: Action,
    log,
    hub_client: HubClient,
    heartbeat: HeartbeatThread,
    langfuse,
    cell_id: str,
    mcp_config_path: str | None,
    bootstrap: tuple[str, str] | None,
    entity_type_for_branch: str | None,
    entity_id_for_branch: str | None,
    activity_relay: ActivityRelay | None = None,
) -> bool:
    """entity 의 active 수명 동안 단일 AgentSession 을 유지하며 cycle 반복.

    AgentSession (현재 ClaudeSDKClient backend) 은 한 entity = 한 long-running claude
    session 을 의미한다. cycle 마다 prompt 1개만 query 하고 ResultMessage 까지 소비.
    같은 session 안에서 MCP 연결, conversation history, session_id 가 모두 이어진다
    (subprocess spawn 없음 — 1 entity = 1 claude binary spawn).

    session 의 model 은 첫 model resolve 로 박힌다 — 같은 entity 의 cycle 마다 model
    이 바뀌는 케이스는 rare 라 가정하고 첫 값 고정. work_item.model 은 Langfuse
    메타에만 기록.
    """
    # 첫 model 결정 — entity_type 에 따라 default 분기. project·initiative(오케스트레이션)는
    # high, issue 는 자기 model 필드 또는 기본 tier.
    initial_entity = action.entity or {}
    if entity_type_for_branch in ("project", "initiative"):
        initial_tier = "high"
    else:
        initial_tier = initial_entity.get("model") or ctx.exec_tier_default
    initial_model = ctx.resolve_model(initial_tier)

    # resume 용 session_id — bootstrap 시점에 hub 에서 로드됐다면 그 값.
    resume_sid: str | None = None
    if bootstrap and entity_id_for_branch:
        sess = ctx.session_store.get_or_create(entity_id_for_branch)
        resume_sid = sess.session_id

    # 지시·계약·절차는 claude CLI 가 자동 로드 (~/.claude/CLAUDE.md[룰 concatenate] + skills,
    # runtime.py 의 preset+setting_sources+skills). 여기선 런타임 사실만 append 로
    # 넘긴다 — entity 수명 동안 불변이라 prompt cache prefix 로 쓰인다. user prompt 는
    # entity slim + delta 등 동적 부분만 cycle 마다 전달.
    system_prompt = ctx.prompt_factory.build_runtime_append(entity_type_for_branch or "issue")
    last_is_error = False

    def _mk_session(resume: str | None):
        # deadline_epoch 은 (재)생성 시점 기준으로 새로 박는다 — agent 가 잔여
        # 시간을 정확히 인지하도록.
        return make_agent_session(
            model=initial_model,
            max_turns=SESSION_MAX_TURNS,
            mcp_config_path=mcp_config_path,
            cwd=EXEC_CWD,
            resume_session_id=resume,
            deadline_epoch=int(time.time()) + SESSION_TIMEOUT,
            timeout_sec=SESSION_TIMEOUT,
            system_prompt=system_prompt,
        )

    async def _open_session(resume: str | None):
        if resume is None:
            c = _mk_session(None)
            await c.__aenter__()
            return c
        # resume 요청: transcript 가 현재 project slug 아래 없으면 claude --resume
        # 가 ProcessError(exit 1, "No conversation found") 로 죽는다. 인프라 경로
        # 변경(예: worker cwd subPath /work/cell → 전체마운트 /data/workspaces/
        # <cell>/<entity>/cell)으로 기존 세션이 다른 slug 에 orphan 되면 영구
        # 크래시루프 — backoffLimit 재시도도 회복 불가 (NESS-ISSUE-5). resume 실패는
        # 재시도로 회복 안 되는 영구 실패이므로 새 세션으로 fallback 한다. 새
        # session_id 는 run_agent on_session_id → _persist_session 머신리가
        # 영속화하므로 다음 cycle 부터 정상 resume (1 cycle 후 self-heal). 잔여:
        # transient 사유로 resume open 이 실패해도 새 세션을 열지만, 워커가 풀
        # 컨텍스트를 재주입하므로 correctness 손상 없음 (대화 이력만 손실) — 영구
        # 크래시루프(진행 0)보다 항상 우월. fail-fast 는 fresh open 도 실패할 때만.
        c = _mk_session(resume)
        try:
            await c.__aenter__()
            return c
        except Exception as e:
            log.error(
                f"[worker] resume 세션 열기 실패 (session_id={resume!r}) — "
                f"새 세션으로 fallback: {e}"
            )
            try:
                await c.__aexit__(None, None, None)
            except Exception:
                pass
            fresh = _mk_session(None)
            await fresh.__aenter__()
            return fresh

    # k8s_jobs.py 는 "persistent worker 는 7일까지 살고 단일 claude 실행은
    # SESSION_TIMEOUT watchdog 가 처리" 를 약속하지만, deadline_epoch/timeout_sec
    # 은 runtime.py 에서 agent 에게 advisory env 로만 전달될 뿐 SDK 서브프로세스를
    # recycle 하지 않았다. 그 결과 waiting(HOTL 핸드오프 — 분~시간~일) 동안 idle
    # 로 들고 있던 세션에 wake 후 resume query 를 날리면 error_during_execution
    # 으로 깨졌다 (NESS-ISSUE-3: 69분 idle 후 댓글 wake → error). 여기서 그
    # watchdog 를 실제로 강제한다: 마지막 query 이후 idle 이 SESSION_TIMEOUT
    # 이상이면 다음 query 직전에 세션을 teardown 후 영속 session_id 로 resume
    # 재생성한다 (대화 연속성·prompt cache prefix 보존, _persist_session 머신리 재사용).
    sdk_client = await _open_session(resume_sid)
    last_query_monotonic = time.monotonic()
    # MCP transport-dead streak — turn 을 넘겨 누적(runtime.run_agent 가 in/out).
    # 매 turn mcp 호출 1회만으로도 임계에 도달해 영구 zombie 를 잡는다.
    mcp_dead_streak = 0
    try:
        while True:
            # heartbeat 가 token 만료 (401 N회) 를 감지하면 즉시 종료. agent-loop 의
            # backoff_limit 재시도가 새 worker (새 token) spawn — 영구 worker 모델의
            # 24h token expiry stuck 방지.
            if heartbeat.has_auth_fatal():
                log.error("[worker] heartbeat auth fatal — 종료, agent-loop 재시도 대기")
                return True
            heartbeat.set_phase("pre_dispatch")
            action = _refresh_action(hub_client, action)
            if action is None:
                log.error("[worker] entity 재조회 실패 — 종료")
                break
            status = (action.entity or {}).get("status")
            held = bool((action.entity or {}).get("hold"))
            # terminal·reply-terminal 집합은 entity type 별. 컨테이너(Project/Initiative)는
            # 통합 5-status 모델 — error/cleanup 가 없고 done/archive 만 terminal (done=완료,
            # archive=폐기; 둘 다 사람/워커 확정). waiting 은 NON-terminal (사람 대기 parked)
            # 이라 여기서 break 안 함 — pre_dispatch 가 valid status 로 받아 pending 댓글
            # reply 를 처리한다. reply-terminal 도 done/archive.
            _et = entity_type_of(action.entity)
            _is_container = _et in ("initiative", "project")
            terminal_states = {"done", "archive"} if _is_container else {"done", "cancelled", "error"}
            reply_terminal_states = {"done", "archive"} if _is_container else {"done", "cancelled"}
            if status in terminal_states:
                # terminal + pending user comment 면 reply 위해 진입 (INFRA-ISSUE-132).
                # entity record 의 pending_user_comment_event_ids 가 있으면 status 유지
                # 채로 §C-0 reply 처리. (issue/project) error 는 사람 명시 복구 필요라 그대로 종료.
                # 단 hold=true 면 reply 도 보류 — held entity 는 사람이 직접 모는 중이라
                # 워커가 끼어들면 안 된다 (INFRA-ISSUE-187, 아래 active hold 게이트와 같은 계약).
                pending = (action.entity or {}).get("pending_user_comment_event_ids") or []
                if status in reply_terminal_states and pending and not held:
                    log.info(f"[worker] entity {status} + pending user comment {len(pending)} — reply 진입")
                else:
                    log.info(f"[worker] entity terminal (status={status}) — 종료")
                    break

            # hold 게이트 (INFRA-ISSUE-187). hold 은 find_all_work 의 spawn 게이트에서만
            # 검사돼, hold 이전부터 살아있던 워커는 이를 무시하고 held entity 에 계속
            # claude turn 을 돌렸다 (새 comment → _wait_for_wake 가 깨움 → reply). 여기서
            # cycle 경계에 게이트를 둬 held 면 claude 실행을 건너뛰고 idle 로 대기한다.
            # hold 해제는 field_change 라 _wait_for_wake 가 깨우고, 다음 cycle 에 held=False
            # 로 정상 진입한다. cycle 경계 skip 이라 진행 중 turn 을 끊지 않는다 (비파괴적).
            if held:
                log.info("[worker] hold=true — claude turn skip, idle 대기 (hold 해제까지)")
                heartbeat.set_phase("idle", note="held")
                _wait_for_wake(
                    client=hub_client,
                    entity_type=entity_type_for_branch, entity_id=entity_id_for_branch,
                    snapshot=action.entity, last_prompt_at=None,
                    poll_interval=POLL_INTERVAL,
                )
                continue

            work_item = pre_dispatch(ctx, action)
            if work_item is None:
                # pre 가 TOCTOU / fetch 실패 등으로 None 반환한 케이스.
                time.sleep(POLL_INTERVAL)
                continue

            session_type = work_item.context.get("session_type", "unknown")
            entity_type = work_item.context.get("entity_type", "unknown")
            # 컨테이너 no_progress 가드용 pre-turn mutation 키 (updated_at, child_count).
            # turn 후 같은 키면 이번 turn 에 아무 mutation 도 없었던 것 → waiting parked.
            pre_mutation_key = None
            _pre_container_entity = (
                work_item.context.get("project")
                or work_item.context.get("initiative")
            )
            if entity_type in ("project", "initiative") and _pre_container_entity:
                pre_mutation_key = _container_mutation_key(hub_client, _pre_container_entity)
            # Langfuse 메타용 entity 정보 — work_item.context 의 issue/project dict 에서 추출.
            cur_entity = work_item.context.get("issue") or work_item.context.get("project") or {}
            entity_title = cur_entity.get("title")
            issue_owner = cur_entity.get("owner")
            capability = cur_entity.get("capability") or []
            is_first_turn = not work_item.session.last_prompt_at

            # watchdog: 마지막 query 이후 idle 이 SESSION_TIMEOUT 이상이면 묵은
            # SDK 세션을 폐기하고 영속 session_id 로 resume 재생성한다. back-to-back
            # 활성 cycle(gap < SESSION_TIMEOUT)은 그대로 재사용 → long-running
            # 세션·prompt cache 이점 보존.
            if time.monotonic() - last_query_monotonic >= SESSION_TIMEOUT:
                idle_s = int(time.monotonic() - last_query_monotonic)
                resume_for = work_item.session.session_id or resume_sid
                log.info(
                    f"[worker] SDK 세션 stale (idle={idle_s}s ≥ "
                    f"SESSION_TIMEOUT={SESSION_TIMEOUT}s) — resume={resume_for!r} 재생성"
                )
                heartbeat.set_phase("session_refresh")
                try:
                    await sdk_client.__aexit__(None, None, None)
                except Exception as e:
                    log.warning(f"[worker] stale 세션 teardown 실패 (계속): {e}")
                try:
                    sdk_client = await _open_session(resume_for)
                except Exception as e:
                    log.error(f"[worker] 세션 재생성 실패: {e}", exc_info=True)
                    wr = WorkResult(
                        work_item=work_item,
                        claude_result={"is_error": True,
                                       "result": f"stale 세션 재생성 실패: {e}"},
                    )
                    heartbeat.set_phase("post_dispatch")
                    try:
                        post_dispatch(ctx, wr)
                    except Exception as e2:
                        log.error(f"[worker] post_dispatch 실패: {e2}", exc_info=True)
                    last_is_error = True
                    time.sleep(POLL_INTERVAL)
                    continue
                # 재생성 성공 — idle 시계 리셋(아래 run_agent 후 다시 갱신).
                last_query_monotonic = time.monotonic()
                # 새 SDK client = 새 MCP 세션 → 옛 연결의 dead streak 은 무효, 리셋.
                mcp_dead_streak = 0

            heartbeat.set_phase("claude_run", note=f"{session_type}/{work_item.model or 'default'}")
            if work_item.session.session_id:
                heartbeat.set_session_id(work_item.session.session_id)
                if activity_relay is not None:
                    activity_relay.set_session_id(work_item.session.session_id)

            def _on_session_id(sid: str) -> None:
                heartbeat.set_session_id(sid)
                if activity_relay is not None:
                    activity_relay.set_session_id(sid)

            try:
                claude_result = await run_agent(
                    client=sdk_client, logger=log,
                    session=work_item.session, prompt=work_item.prompt,
                    model=work_item.model,
                    session_type=session_type, entity_type=entity_type,
                    langfuse=langfuse, cell_id=cell_id,
                    on_session_id=_on_session_id,
                    entity_title=entity_title,
                    issue_owner=issue_owner,
                    capability=capability if isinstance(capability, list) else [],
                    is_first=is_first_turn,
                    relay=activity_relay.add if activity_relay is not None else None,
                    mcp_dead_streak=mcp_dead_streak,
                )
            except Exception as e:
                log.error(f"[worker] claude 실행 실패: {e}", exc_info=True)
                claude_result = {"is_error": True, "result": str(e)}
            # query 종료 시각 기록 — 다음 cycle 의 stale 판정 기준점.
            last_query_monotonic = time.monotonic()
            # transport-dead streak 을 다음 turn 으로 운반 (run_agent in/out). 키 부재
            # (예외 경로 dict)면 현재값 보존 — 0 으로 떨어뜨려 누적을 깨지 않는다.
            mcp_dead_streak = claude_result.get("mcp_dead_streak", mcp_dead_streak)
            heartbeat.set_session_id(work_item.session.session_id)

            wr = WorkResult(work_item=work_item, claude_result=claude_result)

            # session 영구화 — pod crash 시 다음 워커가 resume 으로 복구할 수 있게.
            if bootstrap:
                ent_type, ent_id = bootstrap
                _persist_session(
                    hub_client, entity_type=ent_type, entity_id=ent_id,
                    session_id=work_item.session.session_id,
                    last_prompt_at=work_item.session.last_prompt_at,
                )

            # MCP 세션이 hub 롤아웃으로 영구 무효('Session not found'). 영구 MCP
            # 클라이언트는 in-process 재핸드셰이크 불가 — LLM 의 유일한 시스템
            # 반영 경로(capability 호출)가 죽었으므로 post_dispatch/wake 로 더
            # 진행해봐야 좀비 루프(heartbeat 만 돌며 pending 댓글 영구 미응답).
            # non-zero exit → K8s Job(restartPolicy=Never, backoffLimit=3)이
            # fresh pod 재기동, 위에서 영구화한 session_id 로 같은 claude 대화를
            # --resume 하되 새 MCP 세션으로 복구한다. pending 사용자 댓글은
            # 보존돼 fresh worker 가 이어 처리. (auth-fatal self-exit 와 동일 패턴)
            if claude_result.get("mcp_transport_dead"):
                log.error(
                    "[worker] MCP transport dead — hub 세션 무효('Session not found'). "
                    "in-process 복구 불가 → non-zero exit, K8s Job 이 fresh pod "
                    "재기동(새 MCP 세션)으로 복구. pending 댓글은 보존."
                )
                return True

            heartbeat.set_phase("post_dispatch")
            rate_limit_backoff = 0
            try:
                rate_limit_backoff = post_dispatch(ctx, wr)
            except Exception as e:
                log.error(f"[worker] post_dispatch 실패: {e}", exc_info=True)

            last_is_error = bool(claude_result.get("is_error"))
            if last_is_error:
                # claude 자체 에러 — 다음 cycle 에서 terminal 감지. 단 rate_limit 은
                # 계정 전역 조건이라 POLL_INTERVAL busy-retry 가 reset 전까지 같은
                # 한도에 막혀 halt event 만 피드에 쌓는다 → reset 시각까지 한 번에
                # backoff (heartbeat 는 독립 thread 라 긴 sleep 에도 워커 alive).
                if rate_limit_backoff:
                    log.info(
                        f"[worker] rate_limit — reset 까지 {rate_limit_backoff}s backoff "
                        "(busy-retry·halt event 누적 회피)"
                    )
                time.sleep(rate_limit_backoff or POLL_INTERVAL)
                continue

            # 비에러 turn 종료인데 ISSUE 가 여전히 능동 status(running/cleanup)면 stuck.
            # 능동 status 는 worker 자신만 진전시킨다 — 여기서 _wait_for_wake 로 잠들면
            # 깨울 외부 주체가 없어 영구 데드락(조용히). 첫 발생 즉시 error 로 노출.
            #
            # 컨테이너(Project/Initiative)는 `active` 가 유일한 능동 status 이고 보통 idle-ok
            # 다 (자식 worker 완료 cascade·스케줄러 재pickup·사용자 댓글이 외부 깨움 주체).
            # 단 *이번 turn 에 아무 mutation 도 없이* active 로 끝나면 데드락 — work_finder 가
            # 매 cycle self-action 을 재발급해 워커가 영구 re-invoke 된다 (핸드오프만 반복).
            # pre/post mutation 키(updated_at, child_count)를 비교해 mutation 0 이면 waiting
            # 으로 parked (사람 댓글로만 복구). mutation 이 있었으면(자식 생성·status 전이·
            # entity 갱신) §A.5 정상 idle 이므로 가드 안 탐 — ITEMS-PROJECT-1 회귀 방지.
            fresh = _refresh_action(hub_client, action)
            fresh_entity = (fresh.entity if fresh else None) or {}
            cur_status = fresh_entity.get("status")
            if cur_status in ("running", "cleanup"):
                et = entity_type_of(fresh_entity)
                post_turn_guard(
                    ctx, fresh_entity, et, {"is_error": False},
                    fresh_status=cur_status, no_progress=True,
                )
                return True
            if cur_status == "active" and entity_type in ("project", "initiative"):
                post_mutation_key = _container_mutation_key(hub_client, fresh_entity)
                # 키를 읽지 못한 경우(child_count=-1 = fetch 실패, 또는 updated_at None)는
                # 보수적으로 mutation 있었다고 보고(parked 하지 않음) idle 로 둔다 — 오탐으로
                # 멀쩡한 컨테이너를 parking 하느니 다음 cycle 재평가가 안전. 동일 키 + child_count
                # 가 둘 다 유효(>=0) + updated_at 존재일 때만 no_progress 확정.
                _valid_key = (
                    pre_mutation_key is not None
                    and pre_mutation_key[0] is not None
                    and pre_mutation_key[1] >= 0
                    and post_mutation_key[1] >= 0
                )
                no_mutation = _valid_key and pre_mutation_key == post_mutation_key
                if no_mutation:
                    et = entity_type_of(fresh_entity)
                    post_turn_guard(
                        ctx, fresh_entity, et, {"is_error": False},
                        fresh_status=cur_status, no_progress=True,
                    )
                    # 가드가 컨테이너를 waiting 으로 park(상태는 hub 에 영속) — 정상 종결이다.
                    # exit 0 으로 끝내 K8s Job 을 Complete 시킨다. non-zero 로 끝내면 backoff(=3)
                    # 가 fresh pod 를 재기동, waiting(유효 pre_dispatch status)인 컨테이너에 claude 를
                    # 재실행→재park 만 반복(토큰·pod 낭비). 위 mcp_transport_dead 의 *의도된* 재기동
                    # exit 와 구분 — 그건 복구, 이건 종결.
                    return False

            heartbeat.set_phase("idle")
            # 외부 wake 이벤트 대기 — entity status / event 가 바뀌면 다음 cycle 진입.
            _wait_for_wake(
                client=hub_client, entity_type=entity_type_for_branch, entity_id=entity_id_for_branch,
                snapshot=action.entity, last_prompt_at=work_item.session.last_prompt_at,
                poll_interval=POLL_INTERVAL,
            )
    finally:
        # while 의 break / return / 예외 어느 경로로 빠져나가도 SDK 서브프로세스를
        # 반드시 닫는다 (옛 `async with` 가 보장하던 것과 동등).
        try:
            await sdk_client.__aexit__(None, None, None)
        except Exception as e:
            log.warning(f"[worker] 세션 종료 실패 (무시): {e}")

    return last_is_error


def _refresh_action(client: HubClient, action: Action) -> Action | None:
    """entity 최신 상태로 action.entity 를 갱신. 실패면 None 반환."""
    entity_id = action_entity_id(action)
    entity_type = entity_type_of(action.entity)
    if not entity_id or not entity_type:
        return action
    try:
        resp = client.api(f"{entity_type}.get", {f"{entity_type}_id": entity_id})
    except Exception as e:
        log.warning(f"[worker] entity refetch 실패: {e}")
        return None
    data = (resp or {}).get("data")
    if not data:
        return None
    return Action(type=action.type, entity=data, priority=action.priority)


def _container_child_count(client: HubClient, entity_type: str, entity_id: str) -> int:
    """컨테이너(project/initiative)의 자식 수. mutation 판정(자식 생성)용. 실패 시 -1."""
    try:
        if entity_type == "project":
            return len(client.get_tasks(entity_id) or [])
        if entity_type == "initiative":
            return len(client.get_initiative_projects(entity_id) or [])
    except Exception as e:
        log.warning(f"[worker] child count fetch 실패 ({entity_type} {entity_id}): {e}")
    return -1


def _container_mutation_key(client: HubClient, entity: dict) -> tuple:
    """컨테이너의 *이번 turn mutation 여부* 비교 키 = (updated_at, child_count).

    - updated_at: 모든 `*.update`(status 전이·description·plan·gates·comment+transition)가
      bump → entity-self mutation 감지.
    - child_count: 자식 생성(§A.5 자식 issue/project 생성)은 자식 파일을 쓰고 부모
      updated_at 은 안 건드리므로 별도 카운트로 감지.
    turn 전후 이 키가 같으면 이번 turn 에 아무 mutation 도 없었던 것 (no_progress).
    """
    et = entity_type_of(entity)
    eid = entity.get(id_field_for(et)) if et else None
    child = _container_child_count(client, et, eid) if (et and eid) else -1
    return (entity.get("updated_at"), child)


def _wait_for_wake(
    *, client: HubClient, entity_type: str | None, entity_id: str | None,
    snapshot: dict, last_prompt_at: str | None, poll_interval: int,
) -> None:
    """다음 cycle 을 깨울 외부 변화가 생길 때까지 hub long-poll.

    hub 의 `wake.wait_for_change` 가 entity 변경 (event / status / field / 자식
    cascade) 발생 시 즉시 응답. 60s timeout 후 빈 응답 → 자동 재호출. wake 시점은
    "cycle 종료 직후" 라 그 시점 이후 발생한 외부 변경만 잡힌다 — 자기 cycle 의
    변경이 즉시 wake 를 트리거해 빈 cycle 을 만들던 race (PR #62) 는 hub 측의
    `since` 비교로 방어된다.

    hub 일시 장애 시 poll_interval 초 sleep 후 한 사이클 짧게 polling 으로 동작
    (fallback).
    """
    if not entity_type or not entity_id:
        time.sleep(poll_interval)
        return
    # cycle 안에서 자기 status 가 terminal 로 전이됐을 수 있다 (post_dispatch 의
    # 강제 error / 정상 done 전이). 그 변경은 cycle 종료 직후 since cutoff 이전이라
    # long-poll wake 가 잡지 못해 worker 가 무한 wait. 진입 직전 한 번 확인해 즉시
    # return → 다음 cycle iteration 의 status check 가 break 처리한다.
    try:
        resp = client.api(f"{entity_type}.get", {f"{entity_type}_id": entity_id})
        fresh_status = ((resp or {}).get("data") or {}).get("status")
    except Exception as e:
        log.debug(f"[worker.wake] pre-wait status check 실패 (계속): {e}")
        fresh_status = None
    if fresh_status in ("done", "cancelled", "error", "archive"):
        # entity-agnostic union: issue terminal(done/cancelled/error) + 컨테이너
        # terminal(done/archive). 한쪽에만 있는 status 라도 무해 (status 명 비충돌).
        log.info(f"[worker.wake] terminal 감지 (status={fresh_status}) — wait 안 들어감")
        return
    # cycle 종료 직후 시각을 since 로 박는다 — 그 이후 발생한 변경만 wake 트리거.
    since = datetime.now(timezone.utc).isoformat()
    while True:
        try:
            resp = client.api(
                "wake.wait_for_change",
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "since": since,
                    "timeout": 60.0,
                },
                timeout=70,
            )
        except Exception as e:
            log.debug(f"[worker.wake] wait_for_change 실패, polling fallback: {e}")
            time.sleep(poll_interval)
            return
        reason = ((resp or {}).get("data") or {}).get("wake_reason")
        if reason in ("pending", "notified"):
            log.info(f"[worker.wake] reason={reason} — wake")
            return
        # timeout → 같은 since 로 재호출 (hub 가 또 hold).


if __name__ == "__main__":
    sys.exit(main())
