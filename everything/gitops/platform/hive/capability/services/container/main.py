"""Container capability — k8s native sandbox.

단일 hive namespace 안에 ephemeral Pod을 띄워 사용자 인터랙티브 sandbox를 제공한다.
cell 격리는 pod label(`hive.i-tems.com/cell-id`)로만 수행. TTL/extend 기반 auto-destroy.

엔드포인트:
- sandbox.create / destroy / list / status / extend
- sandbox.exec (단일 명령)
- sandbox.ws (WebSocket 터미널)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import httpx
import jwt
from fastapi import Request, WebSocket, WebSocketDisconnect
from kubernetes import client as k8s_client, config as k8s_config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream as k8s_stream
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse, create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("container")

# ── Config ───────────────────────────────────────────────────────────────────

DEFAULT_CELL_ID = os.environ.get("CELL_ID", "default")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me")
JWT_ALGORITHM = "HS256"

SANDBOX_NAMESPACE = os.environ.get("SANDBOX_NAMESPACE", "hive")
DEFAULT_IMAGE = os.environ.get("SANDBOX_DEFAULT_IMAGE", "ubuntu:24.04")
# worker와 동일한 PVC 를 마운트해 claude 인증·세션 공유.
# 비우면 PVC 마운트 생략(독립 sandbox — cell repo clone 불가).
SANDBOX_HOME_PVC = os.environ.get("SANDBOX_HOME_PVC", "")
SANDBOX_HOME_SUBPATH = os.environ.get("SANDBOX_HOME_SUBPATH", "shared")
# worker 와 동일한 mount 레이아웃: /data 는 PVC 루트, /shared 는 subPath=shared.
SANDBOX_DATA_MOUNT = "/data"
SANDBOX_SHARED_MOUNT = "/shared"
SANDBOX_WORK_MOUNT = "/work"
SANDBOX_CELL_DIR = f"{SANDBOX_WORK_MOUNT}/cell"
# 이름 붙은 sandbox 의 영속 cell-repo clone 베이스. PVC 의 HOME 영역(/shared, subPath
# =shared) 하위 — 런타임 uid(1000)가 claude HOME 처럼 쓸 수 있는 곳. PVC 루트(/data)는
# 소유/권한이 불확실해 피한다. /shared/.claude(claude 인증·specs)와는 별도 네임스페이스.
SANDBOX_TERMINALS_DIR = f"{SANDBOX_SHARED_MOUNT}/terminals"
# 셀 토큰 secret — worker 와 동일 (k8s_jobs.py 참조).
SANDBOX_CELL_TOKEN_SECRET = os.environ.get("SANDBOX_CELL_TOKEN_SECRET", "hive-cell-tokens")
# Hub URL — sandbox.create 시 cell.repo_url 조회에 사용. 비우면 repo clone 생략.
HUB_URL = os.environ.get("HUB_URL", "").rstrip("/")
DEFAULT_TTL_HOURS = float(os.environ.get("DEFAULT_TTL_HOURS", "2"))
MAX_TTL_HOURS = float(os.environ.get("MAX_TTL_HOURS", "24"))
DEFAULT_CPUS = int(os.environ.get("DEFAULT_CPUS", "1"))
DEFAULT_MEMORY_MB = int(os.environ.get("DEFAULT_MEMORY_MB", "1024"))
REAPER_INTERVAL = int(os.environ.get("REAPER_INTERVAL", "60"))
MAX_EXEC_OUTPUT_CHARS = int(os.environ.get("MAX_EXEC_OUTPUT_CHARS", "12000"))

# UI에서 보내는 in-band 제어 메시지 접두사. UI lib/terminal.ts의 CONTROL_PREFIX와 동기화.
WS_CONTROL_PREFIX = "__hive_control__:"
# k8s exec WebSocket의 resize 채널 번호 (SPDY 채널 4)
K8S_EXEC_RESIZE_CHANNEL = 4
# 갓 만든 sandbox는 Pending이므로 WS 연결 시 Running까지 대기할 최대 초.
# initContainer 가 cell repo 를 clone 하므로 첫 진입은 수십 초 걸릴 수 있음.
WS_POD_READY_TIMEOUT = float(os.environ.get("WS_POD_READY_TIMEOUT", "120"))

LABEL_MANAGED = "hive.i-tems.com/managed"
LABEL_ROLE = "hive.i-tems.com/role"
LABEL_CELL_ID = "hive.i-tems.com/cell-id"
LABEL_SANDBOX_ID = "hive.i-tems.com/sandbox-id"
LABEL_SANDBOX_NAME = "hive.i-tems.com/sandbox-name"
ROLE_SANDBOX = "sandbox"
ANNO_CREATED_AT = "hive.i-tems.com/created-at"
ANNO_EXPIRES_AT = "hive.i-tems.com/expires-at"
ANNO_OWNER_EMAIL = "hive.i-tems.com/owner-email"
ANNO_SESSION_ID = "hive.i-tems.com/session-id"
ANNO_IMAGE = "hive.i-tems.com/image"
# WS 터미널 진입 시 cd 할 기본 작업 디렉토리. clone 된 cell repo 경로 또는 /shared.
ANNO_WORKDIR = "hive.i-tems.com/workdir"
ANNO_HOME_DIR = "hive.i-tems.com/home-dir"
ANNO_WORKSPACE_ROOT = "hive.i-tems.com/workspace-root"
# skill-bound 세션 — 설정 시 sandbox.ws 진입에서 bash 대신 claude 를 띄우고
# 해당 skill 로 부팅한다. entity 3종은 `/steering-{type}s {id}`, attending 은
# id 없이 `/attending-user` (cross-cell 광역 1:1), directing 은 id 없이
# `/directing-cells {cell}` (그 cell 의 CEO 전략 대화).
ANNO_ENTITY_TYPE = "hive.i-tems.com/entity-type"
ANNO_ENTITY_ID = "hive.i-tems.com/entity-id"

ENTITY_TYPES = ("issue", "project", "initiative")
ATTENDING_KIND = "attending"
DIRECTING_KIND = "directing"
# entity_id 가 없는 cell-scoped/cross-cell kind — cell 은 pod 에 이미 박혀 있다.
CELL_SCOPED_KINDS = (ATTENDING_KIND, DIRECTING_KIND)
SESSION_KINDS = ENTITY_TYPES + CELL_SCOPED_KINDS
_ENTITY_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")
_SANDBOX_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,61}[A-Za-z0-9])?$")

# ── App ──────────────────────────────────────────────────────────────────────

app = create_app(
    service_id="container",
    version="0.3.0",
    description="k8s native sandbox — sandbox.* (create/destroy/list/status/extend/exec/ws).",
)

# ── k8s client ───────────────────────────────────────────────────────────────

try:
    k8s_config.load_incluster_config()
    log.info("loaded in-cluster config")
except Exception:
    try:
        k8s_config.load_kube_config()
        log.info("loaded kubeconfig")
    except Exception as e:
        log.warning("no k8s config available: %s", e)

core_v1 = k8s_client.CoreV1Api()
# exec 스트림(WS 터미널·sandbox.exec) 전용 클라이언트 — 일반 read/list/write 와
# ApiClient 를 분리한다. kubernetes.stream.stream() 은 호출 동안 api_client.request
# 를 websocket_call 로 monkeypatch 했다 finally 에서 복원하는데, 공유 클라이언트면
# 그 창에 동시 실행되는 일반 호출(read_namespaced_pod 등)이 websocket 경로로 새어
# ApiException(status=0) 으로 죽는다 — 동시 sandbox.ws 연결(브라우저+CLI, 재연결
# 레이스) 시 핸들러가 exec 셋업 전에 터져 WS 가 즉시 닫히던("바로 연결 종료") 원인.
# 별도 ApiClient 로 monkeypatch 를 격리해 일반 호출 오염을 막는다.
exec_v1 = k8s_client.CoreV1Api(k8s_client.ApiClient())


# ── Helpers ──────────────────────────────────────────────────────────────────

# initContainer 부트스트랩 스크립트 — agent worker 의 _bootstrap_workspace 와 동일.
# /work 는 emptyDir 이라 컨테이너 간에 공유돼 메인 셸이 그대로 사용한다.
_BOOTSTRAP_SCRIPT = r"""set -eu
mkdir -p /work
# GIT_CONFIG_GLOBAL 은 컨테이너 env(_shell_envs)로 init·메인 셸 양쪽에 주입된다.
# (과거엔 이 스크립트 안에서만 export 해 메인 셸이 /work/.gitconfig 를 못 봐서
#  credential.helper 가 안 잡히고 `Username for github.com` 프롬프트가 떴다.)
export GIT_CONFIG_GLOBAL="${GIT_CONFIG_GLOBAL:-/work/.gitconfig}"
git config --global user.name "${SANDBOX_GIT_LOGIN:-hive-sandbox}"
git config --global user.email "${SANDBOX_GIT_EMAIL:-sandbox@hive.local}"
git config --global init.defaultBranch main
git config --global --add safe.directory '*'
if [ -n "${GITHUB_TOKEN:-}" ]; then
  printf 'https://x-access-token:%s@github.com\n' "$GITHUB_TOKEN" > /work/.git-credentials
  chmod 600 /work/.git-credentials
  git config --global credential.helper "store --file=/work/.git-credentials"
fi
mkdir -p "$(dirname "$PROJECT_DIR")"
mkdir -p "$HOME"
if [ -d "$PROJECT_DIR/.git" ]; then
  echo "[bootstrap] cell repo already cloned"
else
  echo "[bootstrap] cloning $CELL_REPO_URL"
  git clone --filter=blob:none --no-tags "$CELL_REPO_URL" "$PROJECT_DIR"
fi
# 샌드박스에서 띄우는 claude 의 기본 권한모드 = bypassPermissions.
# 기본 이미지(hive-agent)는 비-root(uid 1000)라 /etc managed-settings·root 경로
# 불가. HOME=/shared 는 agent worker 공용이라 오염 금지(스코프 결정). Claude Code
# 의 project settings 는 git repo 루트의 .claude/ 에서만 발견되므로(상위 미탐색),
# clone 된 cell repo 루트($PROJECT_DIR)에 둔다. 익명 sandbox 는 기존처럼
# /work/cell(emptyDir), 이름 붙은 sandbox 는 /data/terminals/{owner}/{name}/cell.
# settings.local.json = CLI 다음 우선순위
# 라 repo 가 settings.json 을 커밋했어도 defaultMode 만 deep-merge override.
# 컨벤션상 gitignore 대상이므로 .git/info/exclude(로컬·비추적)에 등록해
# git status 오염·오커밋을 막는다 (추적 .gitignore 는 건드리지 않음).
if [ -d "$PROJECT_DIR/.git" ]; then
  mkdir -p "$PROJECT_DIR/.claude"
  # enableAllProjectMcpServers = project .mcp.json 의 MCP 서버 trust 프롬프트
  # 무인 승인 (bypassPermissions 는 tool 실행 게이트라 MCP-trust 게이트와 별개).
  # .mcp.json 없으면 무해(inert)하므로 항상 박는다.
  # hooks.Stop = 매 turn 마다 ui_terminal_hook 이 transcript delta 를 Langfuse 로
  # 적재(사람 셸 토큰·주의력을 워커와 같은 단일 소스로). 훅은 stdin 읽고 fork-detach 라
  # turn 흐름을 막지 않으며, app 패키지는 이미지 venv 에 설치돼 있다.
  printf '%s\n' '{"permissions": {"defaultMode": "bypassPermissions"}, "enableAllProjectMcpServers": true, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/home/agent/venv/bin/python3 -m app.ui_terminal_hook", "timeout": 20}]}]}}' \
    > "$PROJECT_DIR/.claude/settings.local.json"
  grep -qxF '.claude/settings.local.json' "$PROJECT_DIR/.git/info/exclude" 2>/dev/null \
    || echo '.claude/settings.local.json' >> "$PROJECT_DIR/.git/info/exclude"
fi
# hive MCP — 사람 console JWT 를 그대로 실어, sandbox 안 claude 가 그 사람으로서
# (X-Source: console → principal_type=user) capability 를 호출한다.
# 토큰 발급 경로 신설 없음(기존 자격증명 전파). project .mcp.json 은 claude 가
# git repo 루트(=터미널 cd 대상 $PROJECT_DIR)에서만 자동 발견하므로 거기 둔다.
# /work 는 emptyDir(pod-로컬·ephemeral)·0600 → PVC·worker 무영향, pod 소멸 시 증발.
# settings.local.json 과 같은 이유로 .git/info/exclude 에 등록(오커밋 차단).
if [ -d "$PROJECT_DIR/.git" ] && [ -n "${HIVE_MCP_TOKEN:-}" ] && [ -n "${HUB_URL:-}" ]; then
  # cell-agnostic transport — sandbox 안 claude 가 매 invoke 의 cell 인자에
  # 대상 cell 을 명시한다. project .claude/CLAUDE.md 가 활성 cell 컨벤션 정본.
  printf '{"mcpServers":{"hive":{"type":"http","url":"%s/mcp/","headers":{"Authorization":"Bearer %s","X-Source":"console"}}}}\n' \
    "$HUB_URL" "$HIVE_MCP_TOKEN" > "$PROJECT_DIR/.mcp.json"
  chmod 600 "$PROJECT_DIR/.mcp.json"
  grep -qxF '.mcp.json' "$PROJECT_DIR/.git/info/exclude" 2>/dev/null \
    || echo '.mcp.json' >> "$PROJECT_DIR/.git/info/exclude"
  echo "[bootstrap] hive MCP configured (.mcp.json)"
  # MCP JWT 갱신 daemon — 2h 주기로 .mcp.json 토큰을 갱신해 sandbox 운영 중
  # JWT 만료(sandbox 생성 시 갱신에도 불구한 엣지 케이스)를 방어한다.
  # 메인 컨테이너 기동 시 백그라운드로 실행된다(/work/mcp-refresh-daemon.sh).
  cat > /work/mcp-refresh-daemon.sh << 'MCP_DAEMON_EOF'
#!/bin/bash
LOG="/work/mcp-refresh.log"
refresh_mcp_jwt() {
  python3 - <<'PYEOF'
import json, os, urllib.request, urllib.error, sys
MCP_JSON = os.path.join(os.environ.get("PROJECT_DIR", "/work/cell"), ".mcp.json")
HUB_URL = os.environ.get("HUB_URL", "")
if not HUB_URL:
    sys.exit(0)
try:
    d = json.load(open(MCP_JSON))
    token = d["mcpServers"]["hive"]["headers"]["Authorization"].replace("Bearer ", "", 1)
except Exception:
    sys.exit(0)
req = urllib.request.Request(
    HUB_URL + "/auth.refresh",
    headers={"Authorization": "Bearer " + token},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
    if body.get("status") == "ok":
        d["mcpServers"]["hive"]["headers"]["Authorization"] = "Bearer " + body["data"]["token"]
        with open(MCP_JSON, "w") as fp:
            json.dump(d, fp)
        print("refreshed")
    else:
        print("refresh failed:", body.get("error_code", "unknown"), file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print("refresh error:", e, file=sys.stderr)
    sys.exit(1)
PYEOF
}
while true; do
  sleep 7200
  [ -f "$PROJECT_DIR/.mcp.json" ] || continue
  if refresh_mcp_jwt >> "$LOG" 2>&1; then
    printf '%s: ok\n' "$(date -u)" >> "$LOG"
  else
    printf '%s: failed — MCP auth may expire\n' "$(date -u)" >> "$LOG"
  fi
done
MCP_DAEMON_EOF
  chmod 750 /work/mcp-refresh-daemon.sh
fi
echo "[bootstrap] done"
"""


def _shell_envs(
    cell_id: str, repo_url: str | None, owner_email: str | None = None,
    *, git_login: str | None = None, git_email: str | None = None,
    entity_type: str | None = None, entity_id: str | None = None,
    project_dir: str | None = None,
    home_dir: str | None = None,
) -> list[k8s_client.V1EnvVar]:
    """worker 와 동일한 env. EXEC_CWD/PROJECT_DIR 가 cell repo clone 경로를 가리킨다.

    GIT_CONFIG_GLOBAL 을 init·메인 셸 양쪽에 주입해 부트스트랩이 /work/.gitconfig 에
    쓴 credential.helper·safe.directory·identity 를 메인 셸 git 이 그대로 읽게 한다.
    SANDBOX_GIT_LOGIN/EMAIL = git author. 우선순위:
      1) git_login/git_email (hub /user.settings 의 effective 값 — 사용자 프로필
         override 또는 그 기본값)
      2) owner_email 로컬 파트 (hub 미응답 시 오프라인 폴백)
      3) 둘 다 없으면 부트스트랩의 hive-sandbox 폴백.
    """
    project_dir = project_dir or (SANDBOX_CELL_DIR if repo_url else SANDBOX_SHARED_MOUNT)
    home_dir = home_dir or SANDBOX_SHARED_MOUNT
    env = [
        # UTF-8 로케일 — 미설정 시 터미널·claude 가 한글 등 멀티바이트를 깨뜨린다(`____`).
        # ubuntu 기본 제공 C.UTF-8 사용 (locale-gen 불필요).
        k8s_client.V1EnvVar(name="LANG", value="C.UTF-8"),
        k8s_client.V1EnvVar(name="LC_ALL", value="C.UTF-8"),
        k8s_client.V1EnvVar(name="HOME", value=home_dir),
        k8s_client.V1EnvVar(name="HIVE_ROOT", value=SANDBOX_DATA_MOUNT),
        k8s_client.V1EnvVar(name="SHARED_DIR", value=home_dir),
        k8s_client.V1EnvVar(name="PROJECT_DIR", value=project_dir),
        k8s_client.V1EnvVar(name="EXEC_CWD", value=project_dir),
        k8s_client.V1EnvVar(name="SPECS_ROOT", value=f"{home_dir}/specs"),
        k8s_client.V1EnvVar(name="CELL_ID", value=cell_id),
        k8s_client.V1EnvVar(
            name="GIT_CONFIG_GLOBAL", value=f"{SANDBOX_WORK_MOUNT}/.gitconfig",
        ),
    ]
    resolved_login = (git_login or "").strip()
    resolved_email = (git_email or "").strip()
    if not resolved_login and owner_email and "@" in owner_email:
        resolved_login = owner_email.split("@", 1)[0].strip()
        resolved_email = resolved_email or owner_email
    if resolved_login:
        env.append(k8s_client.V1EnvVar(name="SANDBOX_GIT_LOGIN", value=resolved_login))
    if resolved_email:
        env.append(k8s_client.V1EnvVar(name="SANDBOX_GIT_EMAIL", value=resolved_email))
    if HUB_URL:
        env.append(k8s_client.V1EnvVar(name="HUB_URL", value=HUB_URL))
    if repo_url:
        env.append(k8s_client.V1EnvVar(name="CELL_REPO_URL", value=repo_url))
        env.append(k8s_client.V1EnvVar(
            name="GITHUB_TOKEN",
            value_from=k8s_client.V1EnvVarSource(
                secret_key_ref=k8s_client.V1SecretKeySelector(
                    name=SANDBOX_CELL_TOKEN_SECRET, key=cell_id, optional=True,
                ),
            ),
        ))
    # ui_terminal_hook(Stop 훅)이 읽는 신원 — 사람이 직접 모는 claude 세션의 토큰·
    # 주의력을 owner/entity 로 귀속해 Langfuse 에 적재(channel=ui_terminal). console
    # JWT 와 달리 식별자뿐이라 메인 셸 env 에 둬도 안전.
    if owner_email:
        env.append(k8s_client.V1EnvVar(name="HIVE_TERM_OWNER", value=owner_email))
    if entity_type:
        env.append(k8s_client.V1EnvVar(name="HIVE_TERM_ENTITY_TYPE", value=entity_type))
    if entity_id:
        env.append(k8s_client.V1EnvVar(name="HIVE_TERM_ENTITY_ID", value=entity_id))
    return env


def _path_segment(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip(".-")
    return cleaned[:48] or fallback


def _owner_workspace_segment(owner_email: str | None) -> str:
    owner = (owner_email or "anonymous").strip().lower() or "anonymous"
    digest = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:10]
    return f"{_path_segment(owner, fallback='anonymous')}-{digest}"


def _named_workspace_root(cell_id: str, owner_email: str | None, sandbox_name: str | None) -> str | None:
    name = (sandbox_name or "").strip()
    if not name:
        return None
    # cell_id 를 키에 포함 — 같은 owner 가 여러 cell 에서 같은 이름을 써도 clone 경로가
    # 겹치지 않게 한다 (안 그러면 둘째 cell pod 이 첫 cell 의 repo 를 재사용).
    return f"{SANDBOX_TERMINALS_DIR}/{_owner_workspace_segment(owner_email)}/{cell_id}/{name}"


def _skill_workspace_root(
    cell_id: str, owner_email: str | None,
    entity_type: str | None, entity_id: str | None,
) -> str | None:
    """skill 세션(entity/directing/attending)의 **고유** 작업 디렉토리 root.

    named 세션과 같은 원리 — cwd 를 세션 정체성마다 고유하게 만들어 claude project
    slug 를 분리한다. 그래야 --continue 가 그 세션의 대화만 resume 한다(한 entity =
    한 세션 + 재개). 안 그러면 모든 skill 세션이 /work/cell 을 공유해 --continue 가
    아무 최신 대화나 resume 하던 버그가 난다.

    /work(emptyDir, pod-로컬)에 둔다 — repo 는 pod 마다 재clone 되지만 경로가 (owner,
    cell, type, id)로 **결정적**이라 pod 재생성·재접속에도 같은 /shared transcript
    (slug 로 키잉)를 찾아 resume 된다. entity_id 는 _ENTITY_ID_RE([A-Za-z0-9_-])로
    검증돼 경로 안전.

    모든 세션은 **owner 별로 분리**한다 — cwd 에 owner segment 를 넣어 같은 entity/
    directing/attending 을 여러 사용자가 열어도 claude project slug 가 갈리고
    --continue 가 그 사용자 자신의 대화만 resume 한다. owner 가 빠지면 같은 cell
    권한자끼리 한 세션을 공유해(다른 사용자의 대화가 보임) per-user 격리가 깨진다.
    """
    seg_owner = _owner_workspace_segment(owner_email)
    if entity_type in ENTITY_TYPES and entity_id:
        seg = f"{seg_owner}/{entity_type}/{entity_id}"
    elif entity_type == DIRECTING_KIND:
        seg = f"{seg_owner}/directing"
    elif entity_type == ATTENDING_KIND:
        seg = f"attending/{seg_owner}"
    else:
        return None
    return f"{SANDBOX_WORK_MOUNT}/sessions/{cell_id}/{seg}"


def _claude_project_dir(home_dir: str, cwd: str) -> str:
    """claude 가 그 cwd 의 세션 transcript 를 저장하는 project 디렉토리.

    claude 는 cwd 를 슬러그화해 `$HOME/.claude/projects/<slug>/` 에 저장하는데,
    슬러그는 영숫자·하이픈을 제외한 **모든 문자**(`/` `.` `_` `~` `@` 등)를 `-` 로
    바꾼 것이다 (대소문자 보존). 실측 확인: `/tmp/Ab_cd.ef-GH/ij`→
    `-tmp-Ab-cd-ef-GH-ij`. 존재 체크를 이 정확한 경로로 해야 cwd 한정으로 맞아
    떨어진다 (`pwd|sed 's#/#-#g'` 는 `.` 를 안 바꿔 owner segment 의 `gmail.com`
    에서 어긋났다 — "session not found"/"already in use" 의 원인)."""
    slug = re.sub(r"[^A-Za-z0-9-]", "-", cwd)
    return f"{home_dir.rstrip('/')}/.claude/projects/{slug}"


def _build_pod(sandbox_id: str, cell_id: str, image: str, *, cpus: int, memory_mb: int,
               owner_email: str | None, session_id: str | None,
               created_at: datetime, expires_at: datetime,
               repo_url: str | None,
               git_login: str | None = None, git_email: str | None = None,
               console_jwt: str | None = None,
               entity_type: str | None = None, entity_id: str | None = None,
               sandbox_name: str | None = None,
               ) -> k8s_client.V1Pod:
    # 이름 붙은 sandbox 는 per-name PVC 경로(/shared/terminals, 영속), skill 세션
    # (entity/directing/attending)은 per-identity /work 경로 — 둘 다 cwd 를 고유하게
    # 만들어 claude project slug 를 분리하고 --continue 가 그 세션 대화만 resume 하게
    # 한다(한 entity = 한 세션 + 재개). HOME 은 항상 공유 /shared (claude oauth 인증·
    # specs 거주) — cwd 만 분리하면 대화는 격리되고 인증은 유지된다.
    if sandbox_name:
        workspace_root = _named_workspace_root(cell_id, owner_email, sandbox_name)
    else:
        workspace_root = _skill_workspace_root(cell_id, owner_email, entity_type, entity_id)
    # skill·named 세션(workspace_root 있음)은 repo 유무와 무관히 **항상 고정·고유 cwd**
    # `{workspace_root}/cell` 를 쓴다 (repo 없으면 빈 디렉토리, exec 에서 mkdir -p).
    # `/cell` 접미사를 repo_url 에 따라 붙였다 떼면(과거) cwd 가 접속마다 흔들려
    # (.../attending ↔ .../attending/cell) 세션이 서로 다른 claude project 로 쪼개지고
    # 재개가 어긋난다. cwd 는 (owner, cell, name|entity)마다 결정적·불변이어야 그 project
    # 에 이 정체성 세션만 모이고 --continue 가 그것만 resume 한다(격리·재개). 공유 /shared
    # 폴백도 금지(전역 cwd 라 교차). 익명 plain 세션(workspace_root 없음)만 bash 라 무방.
    if workspace_root:
        workdir = f"{workspace_root}/cell"
    elif repo_url:
        workdir = SANDBOX_CELL_DIR
    else:
        workdir = SANDBOX_SHARED_MOUNT
    home_dir = SANDBOX_SHARED_MOUNT
    annotations = {
        ANNO_CREATED_AT: created_at.isoformat(),
        ANNO_EXPIRES_AT: expires_at.isoformat(),
        ANNO_IMAGE: image,
        ANNO_WORKDIR: workdir,
        ANNO_HOME_DIR: home_dir,
    }
    if workspace_root:
        annotations[ANNO_WORKSPACE_ROOT] = workspace_root
    if owner_email:
        annotations[ANNO_OWNER_EMAIL] = owner_email
    if session_id:
        annotations[ANNO_SESSION_ID] = session_id
    if entity_type:
        annotations[ANNO_ENTITY_TYPE] = entity_type
        if entity_id:
            annotations[ANNO_ENTITY_ID] = entity_id

    # worker 패턴: PVC 를 /data 와 /shared(subPath=shared) 에 동시에 마운트.
    # /work 는 익명 sandbox 호환을 위해 emptyDir 로 유지하고, 이름 붙은 sandbox 만
    # /data/terminals/{owner}/{name} 아래를 PROJECT_DIR/HOME 으로 쓴다.
    volumes = [
        k8s_client.V1Volume(name="work", empty_dir=k8s_client.V1EmptyDirVolumeSource()),
    ]
    data_mounts: list[k8s_client.V1VolumeMount] = []
    if SANDBOX_HOME_PVC:
        volumes.append(k8s_client.V1Volume(
            name="data",
            persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                claim_name=SANDBOX_HOME_PVC,
            ),
        ))
        data_mounts = [
            k8s_client.V1VolumeMount(name="data", mount_path=SANDBOX_DATA_MOUNT),
            k8s_client.V1VolumeMount(
                name="data", mount_path=SANDBOX_SHARED_MOUNT,
                sub_path=SANDBOX_HOME_SUBPATH,
            ),
        ]
    work_mount = k8s_client.V1VolumeMount(name="work", mount_path=SANDBOX_WORK_MOUNT)

    sec_ctx = k8s_client.V1SecurityContext(
        allow_privilege_escalation=False,
        privileged=False,
        capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
    )

    init_containers: list[k8s_client.V1Container] = []
    if repo_url:
        # console JWT 는 bootstrap(init) 컨테이너 env 에만 주입한다 — 메인 셸
        # 컨테이너엔 넣지 않아 사람의 장수명 토큰이 대화형 셸 프로세스 환경에
        # 남지 않게 한다 (at-rest 는 .mcp.json 0600 + pod spec 한정).
        bootstrap_env = _shell_envs(
            cell_id, repo_url, owner_email,
            git_login=git_login, git_email=git_email,
            project_dir=workdir,
            home_dir=home_dir,
        )
        if console_jwt and HUB_URL:
            bootstrap_env.append(
                k8s_client.V1EnvVar(name="HIVE_MCP_TOKEN", value=console_jwt)
            )
        init_containers.append(k8s_client.V1Container(
            name="bootstrap",
            image=image,
            # 기본 이미지 태그가 moving(:main)이라 IfNotPresent 면 노드 캐시 때문에
            # 갱신(예: tmux 추가)이 새 sandbox 에 안 닿는다 → Always 로 매 생성 시
            # 레지스트리 digest 확인(캐시 일치 시 빠름). SHA-pin 이미지였다면 불필요.
            image_pull_policy="Always",
            command=["bash", "-lc", _BOOTSTRAP_SCRIPT],
            env=bootstrap_env,
            volume_mounts=[*data_mounts, work_mount],
            security_context=sec_ctx,
            resources=k8s_client.V1ResourceRequirements(
                requests={"cpu": "50m", "memory": "128Mi"},
                limits={"cpu": "1", "memory": "512Mi"},
            ),
        ))

    return k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(
            name=sandbox_id,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: ROLE_SANDBOX,
                LABEL_CELL_ID: cell_id,
                LABEL_SANDBOX_ID: sandbox_id,
                **({LABEL_SANDBOX_NAME: sandbox_name} if sandbox_name else {}),
            },
            annotations=annotations,
        ),
        spec=k8s_client.V1PodSpec(
            restart_policy="Never",
            termination_grace_period_seconds=5,
            automount_service_account_token=False,
            security_context=k8s_client.V1PodSecurityContext(
                seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
            ),
            volumes=volumes,
            init_containers=init_containers or None,
            containers=[
                k8s_client.V1Container(
                    name="shell",
                    image=image,
                    image_pull_policy="Always",  # moving :main 갱신 반영 (위 bootstrap 주석)
                    # mcp-refresh-daemon.sh 가 있으면 백그라운드로 기동 후 sleep.
                    command=["bash", "-lc",
                             "[ -f /work/mcp-refresh-daemon.sh ] && bash /work/mcp-refresh-daemon.sh &"
                             " exec sleep infinity"],
                    env=_shell_envs(cell_id, repo_url, owner_email,
                            git_login=git_login, git_email=git_email,
                            entity_type=entity_type, entity_id=entity_id,
                            project_dir=workdir, home_dir=home_dir),
                    resources=k8s_client.V1ResourceRequirements(
                        requests={"cpu": f"{max(50, cpus * 100)}m", "memory": f"{memory_mb // 4}Mi"},
                        limits={"cpu": str(cpus), "memory": f"{memory_mb}Mi"},
                    ),
                    security_context=sec_ctx,
                    volume_mounts=[*data_mounts, work_mount],
                    tty=True,
                    stdin=True,
                )
            ],
        ),
    )


def _pod_info(pod) -> dict:
    meta = pod.metadata
    annos = meta.annotations or {}
    labels = meta.labels or {}
    return {
        "id": labels.get(LABEL_SANDBOX_ID, meta.name),
        "name": meta.name,
        "sandbox_name": labels.get(LABEL_SANDBOX_NAME),
        "namespace": meta.namespace,
        "cell_id": labels.get(LABEL_CELL_ID),
        "image": annos.get(ANNO_IMAGE),
        "created_at": annos.get(ANNO_CREATED_AT) or (meta.creation_timestamp.isoformat() if meta.creation_timestamp else None),
        "expires_at": annos.get(ANNO_EXPIRES_AT),
        "owner_email": annos.get(ANNO_OWNER_EMAIL),
        "session_id": annos.get(ANNO_SESSION_ID),
        "workdir": annos.get(ANNO_WORKDIR),
        "home_dir": annos.get(ANNO_HOME_DIR),
        "workspace_root": annos.get(ANNO_WORKSPACE_ROOT),
        "entity_type": annos.get(ANNO_ENTITY_TYPE),
        "entity_id": annos.get(ANNO_ENTITY_ID),
        "status": (pod.status.phase if pod.status else None) or "unknown",
    }


def _trim(text: str, max_chars: int = MAX_EXEC_OUTPUT_CHARS) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return f"{text[:max_chars]}\n...[truncated]", True


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def _request_owner_email(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        payload = _decode_jwt(auth[7:].strip())
        if payload and payload.get("sub"):
            return str(payload["sub"]).strip().lower() or None
    cookie_header = request.headers.get("cookie") or ""
    if cookie_header:
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get("auth_token")
        if morsel:
            payload = _decode_jwt(morsel.value)
            if payload and payload.get("sub"):
                return str(payload["sub"]).strip().lower() or None
    return None


def _request_console_jwt(request: Request) -> str | None:
    """sandbox.create 요청이 실어온 사람 console JWT 원문. attribution 보존용.

    _request_owner_email 과 동일한 출처 규약(Authorization Bearer → auth_token
    쿠키). 디코드하지 않고 원문을 그대로 돌려준다 — sandbox 안 claude 가 hive
    MCP 를 `X-Source: console` 경로로 그 사람으로서 호출하도록 .mcp.json 에 박는다.
    """
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    cookie_header = request.headers.get("cookie") or ""
    if cookie_header:
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get("auth_token")
        if morsel and morsel.value.strip():
            return morsel.value.strip()
    return None


def _websocket_owner_email(ws: WebSocket) -> str | None:
    # 네이티브 CLI(hive-term)는 브라우저의 httpOnly auth_token 쿠키 대신
    # Authorization: Bearer 로 console JWT 를 싣는다 — 쿠키 jar 가 없기 때문.
    # 우선순위: Authorization Bearer → auth_token 쿠키. owner 검증 로직은 불변
    # (디코드된 sub 만 본다). _request_console_jwt 의 WS 분기와 동일한 출처 규약.
    auth = ws.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        payload = _decode_jwt(auth[7:].strip())
        if payload and payload.get("sub"):
            return str(payload["sub"]).strip().lower() or None
    cookie_header = ws.headers.get("cookie") or ""
    if cookie_header:
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get("auth_token")
        if morsel:
            payload = _decode_jwt(morsel.value)
            if payload and payload.get("sub"):
                return str(payload["sub"]).strip().lower() or None
    return None


def _check_owner(pod, owner_email: str | None, cell_id: str | None) -> bool:
    """cell_id 라벨과 owner annotation을 비교. 인증된 요청은 owner 일치 필수."""
    annos = pod.metadata.annotations or {}
    pod_cell = (pod.metadata.labels or {}).get(LABEL_CELL_ID)
    pod_owner = annos.get(ANNO_OWNER_EMAIL)
    if cell_id and pod_cell and cell_id != pod_cell:
        return False
    # 요청자가 인증되어 있으면 pod owner와 반드시 일치해야 함
    # (pod_owner가 비어있는 레거시 pod도 거부 — 안전 우선)
    if owner_email:
        return pod_owner == owner_email
    # 미인증(예: dev 환경) — cell만 일치하면 허용
    return True


def _request_cell_id(request: Request) -> str:
    return (request.headers.get("X-Cell-Id") or DEFAULT_CELL_ID).strip() or DEFAULT_CELL_ID


async def _fetch_cell_repo_url(cell_id: str, request: Request) -> str | None:
    """Hub /cell.get 호출해 cell.repo_url 조회.

    console JWT 를 _request_console_jwt 로 뽑아 명시적 Bearer + X-Source: console
    로 인증한다 (_authorize_cell_access 와 동일). 요청 헤더를 그대로 forward 하던
    옛 방식은 브라우저 WebSocket attach 경로에서 깨졌다 — WS 핸드셰이크는 커스텀
    헤더(X-Source)·Authorization 을 못 실어 Cookie 만 도착하는데, hub 는
    X-Source==console 일 때만 console JWT 를 인증하므로 401 → repo_url=None →
    bootstrap(clone·.mcp.json·settings.local.json·토큰 daemon) 전체 스킵으로 이어졌다.

    HUB_URL 미설정·console JWT 없음·hub 비응답·repo_url 없음 모두 None 반환
    (sandbox 는 repo clone 없이 생성된다 — 레거시 fallback).
    """
    if not HUB_URL:
        return None
    console_jwt = _request_console_jwt(request)
    if not console_jwt:
        return None
    headers = {
        "Content-Type": "application/json",
        "X-Source": "console",
        "Authorization": f"Bearer {console_jwt}",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{HUB_URL}/cell.get", json={"cell_id": cell_id}, headers=headers)
    except Exception as e:
        log.warning("cell.get failed for %s: %s", cell_id, e)
        return None
    if resp.status_code != 200:
        log.warning("cell.get %s → %s", cell_id, resp.status_code)
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    if body.get("status") != "ok":
        return None
    repo_url = (body.get("data") or {}).get("repo_url")
    return repo_url.strip() if isinstance(repo_url, str) and repo_url.strip() else None


async def _authorize_cell_access(cell_id: str, console_jwt: str | None) -> bool:
    """요청자(console JWT 의 sub)가 cell_id 에 접근 가능한지 hub 에 권위 확인.

    이 컨테이너 서비스는 hub 인가 경계 **밖**에 있다 — nginx 가 /container/ 를 hub
    cell 미들웨어를 건너뛰고 직접 프록시하므로, sandbox 생성/attach 의 cell 인가를
    여기서 명시적으로 재확인해야 한다. hub /cell.get 은 X-Source=console 일 때
    admin/allowed_emails 로 게이트한다(cell_get → _can_access_cell). 그 판정을 그대로
    권위로 삼는다 (cell_id 단위 — entity 는 그 cell 에 속하므로 cell 게이트로 충분).

    fail-closed: hub 가 명시적으로 status=ok 를 줄 때만 True. forbidden·에러 응답·
    hub 비응답·토큰 없음은 모두 False. 단 HUB_URL 미설정(로컬/dev — 물어볼 hub 가
    없음)만 게이트 불가로 True (다른 hub 의존 동작과 동일한 degrade)."""
    if not HUB_URL:
        return True
    if not console_jwt:
        return False
    headers = {
        "Content-Type": "application/json",
        "X-Source": "console",
        "Authorization": f"Bearer {console_jwt}",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{HUB_URL}/cell.get", json={"cell_id": cell_id}, headers=headers,
            )
    except Exception as e:
        log.warning("cell access check failed for %s: %s", cell_id, e)
        return False
    if resp.status_code != 200:
        return False
    try:
        body = resp.json()
    except Exception:
        return False
    return body.get("status") == "ok"


async def _fetch_user_git_identity(
    request: Request,
) -> tuple[str | None, str | None]:
    """Hub /user.settings.get 호출해 로그인 사용자의 effective git identity 조회.

    effective_git_* = 사용자 프로필 override 또는 그 기본값(이메일 로컬 파트)을
    hub 가 합성한 값. 인증은 _fetch_cell_repo_url 과 동일하게 console JWT 를
    명시적 Bearer + X-Source: console 로 싣는다 (WS attach 헤더 forward 가 401 되던
    문제 동일 수정). HUB_URL 미설정·console JWT 없음·hub 비응답·미인증 모두
    (None, None) 반환 → _shell_envs 가 owner_email 기반 오프라인 폴백을 사용한다.
    """
    if not HUB_URL:
        return None, None
    console_jwt = _request_console_jwt(request)
    if not console_jwt:
        return None, None
    headers = {
        "Content-Type": "application/json",
        "X-Source": "console",
        "Authorization": f"Bearer {console_jwt}",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{HUB_URL}/user.settings.get", json={}, headers=headers,
            )
    except Exception as e:
        log.warning("user.settings.get failed: %s", e)
        return None, None
    if resp.status_code != 200:
        log.warning("user.settings.get → %s", resp.status_code)
        return None, None
    try:
        body = resp.json()
    except Exception:
        return None, None
    if body.get("status") != "ok":
        return None, None
    data = body.get("data") or {}
    name = data.get("effective_git_name")
    email = data.get("effective_git_email")
    name = name.strip() if isinstance(name, str) and name.strip() else None
    email = email.strip() if isinstance(email, str) and email.strip() else None
    return name, email


async def _refresh_jwt_via_hub(console_jwt: str) -> str | None:
    """Hub /auth.refresh 로 console JWT 를 갱신해 fresh 7-day JWT 를 반환.

    sandbox 생성 시 호출해 수명 말기 JWT 가 sandbox TTL(최대 24h) 안에 만료되는 것을
    방지한다. hub 미설정·비응답·이미 만료된 JWT 모두 None 반환 (원본 폴백).
    """
    if not HUB_URL or not console_jwt:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{HUB_URL}/auth.refresh",
                headers={"Authorization": f"Bearer {console_jwt}"},
            )
        if resp.status_code == 200:
            body = resp.json()
            if body.get("status") == "ok":
                return (body.get("data") or {}).get("token") or None
        log.warning("jwt refresh → %s", resp.status_code)
    except Exception as e:
        log.warning("jwt refresh failed: %s", e)
    return None


# ── Models ───────────────────────────────────────────────────────────────────

class SandboxCreateRequest(BaseModel):
    name: str | None = Field(
        default=None,
        description="Owner 범위에서 재사용할 sandbox 이름. 설정 시 살아 있는 동명 pod를 반환하고, 새 pod는 PVC workspace를 사용.",
    )
    image: str | None = Field(default=None, description="컨테이너 이미지. 비우면 기본 이미지 사용.")
    session_id: str | None = Field(default=None, description="세션 바인딩.")
    ttl_hours: float = Field(default=DEFAULT_TTL_HOURS, description=f"시간 제한 (최대 {MAX_TTL_HOURS}h).")
    cpus: int = Field(default=DEFAULT_CPUS, description="CPU 코어.")
    memory_mb: int = Field(default=DEFAULT_MEMORY_MB, description="메모리 (MB).")
    entity_type: str | None = Field(
        default=None,
        description=f"skill-bound 세션 종류. 허용: {', '.join(SESSION_KINDS)}. "
        "entity 3종은 WS 진입에서 claude /steering-* 실행, 'attending' 은 "
        "id 없이 /attending-user (cross-cell 광역 1:1), 'directing' 은 id 없이 "
        "/directing-cells {cell} (그 cell 의 CEO 전략 대화). 미설정 시 plain bash.",
    )
    entity_id: str | None = Field(
        default=None,
        description="entity 세션의 대상 id. 안전 문자(`[A-Za-z0-9_-]`)만, 최대 128자. "
        "attending 세션은 불필요(무시).",
    )


class SandboxIdRequest(BaseModel):
    id: str


class SandboxExtendRequest(BaseModel):
    id: str
    hours: float = 1.0


class SandboxListRequest(BaseModel):
    pass


class SandboxExecRequest(BaseModel):
    id: str
    command: str
    workdir: str | None = None


# ── Pod 조회 헬퍼 ────────────────────────────────────────────────────────────

def _find_pod(sandbox_id: str, cell_id: str):
    try:
        pod = core_v1.read_namespaced_pod(name=sandbox_id, namespace=SANDBOX_NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            return None
        raise
    # 다른 cell의 pod 이름으로 우회 접근 방지
    pod_cell = (pod.metadata.labels or {}).get(LABEL_CELL_ID)
    if cell_id and pod_cell and cell_id != pod_cell:
        return None
    return pod


def _find_named_pod(cell_id: str, owner_email: str | None, sandbox_name: str):
    selector = (
        f"{LABEL_MANAGED}=true,{LABEL_ROLE}={ROLE_SANDBOX},"
        f"{LABEL_CELL_ID}={cell_id},{LABEL_SANDBOX_NAME}={sandbox_name}"
    )
    pods = core_v1.list_namespaced_pod(namespace=SANDBOX_NAMESPACE, label_selector=selector)
    for pod in pods.items:
        if not _check_owner(pod, owner_email, cell_id):
            continue
        phase = (pod.status.phase if pod.status else "") or ""
        if phase not in ("Failed", "Succeeded"):
            return pod
    return None


def _list_pods_for_cell(cell_id: str):
    selector = f"{LABEL_MANAGED}=true,{LABEL_ROLE}={ROLE_SANDBOX},{LABEL_CELL_ID}={cell_id}"
    try:
        pods = core_v1.list_namespaced_pod(namespace=SANDBOX_NAMESPACE, label_selector=selector)
        return pods.items
    except ApiException as e:
        if e.status == 404:
            return []
        raise


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post(
    "/sandbox.create",
    summary="Sandbox 생성",
    description="hive namespace에 임시 Pod을 띄움. TTL 만료 또는 destroy 시 정리.",
    openapi_extra={"x-side-effects": "external", "x-requires-approval": False},
)
async def sandbox_create(req: SandboxCreateRequest, request: Request) -> CapabilityResponse:
    cell_id = _request_cell_id(request)
    owner_email = _request_owner_email(request)
    if not await _authorize_cell_access(cell_id, _request_console_jwt(request)):
        return CapabilityResponse(
            status="error", error_code="cell_forbidden",
            message=f"cell '{cell_id}' 에 접근할 권한이 없습니다.",
        )
    image = req.image or DEFAULT_IMAGE
    ttl = min(req.ttl_hours, MAX_TTL_HOURS)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl)
    sandbox_id = f"sandbox-{uuid.uuid4().hex[:8]}"
    sandbox_name = (req.name or "").strip() or None
    if sandbox_name and not _SANDBOX_NAME_RE.match(sandbox_name):
        return CapabilityResponse(
            status="error",
            error_code="invalid_name",
            message="name must be 1-63 chars: letters, numbers, dot, underscore, hyphen; start/end with a letter or number.",
        )
    if sandbox_name and not SANDBOX_HOME_PVC:
        return CapabilityResponse(
            status="error",
            error_code="named_requires_pvc",
            message="named sandbox requires SANDBOX_HOME_PVC so workspace and Claude history can persist.",
        )

    if sandbox_name:
        try:
            existing = await asyncio.to_thread(
                _find_named_pod, cell_id, owner_email, sandbox_name,
            )
        except ApiException as e:
            return CapabilityResponse(status="error", error_code="lookup_failed", message=str(e))
        if existing:
            patch = {"metadata": {"annotations": {ANNO_EXPIRES_AT: expires_at.isoformat()}}}
            try:
                await asyncio.to_thread(
                    core_v1.patch_namespaced_pod,
                    name=existing.metadata.name,
                    namespace=existing.metadata.namespace,
                    body=patch,
                )
                existing.metadata.annotations = {
                    **(existing.metadata.annotations or {}),
                    ANNO_EXPIRES_AT: expires_at.isoformat(),
                }
            except ApiException as e:
                return CapabilityResponse(status="error", error_code="extend_failed", message=str(e))
            data = _pod_info(existing)
            data["reused"] = True
            return CapabilityResponse(status="ok", data=data)

    entity_type = (req.entity_type or "").strip() or None
    entity_id = (req.entity_id or "").strip() or None
    if entity_type is not None and entity_type not in SESSION_KINDS:
        return CapabilityResponse(
            status="error", error_code="invalid_entity_type",
            message=f"entity_type must be one of {SESSION_KINDS}.",
        )
    if entity_type in CELL_SCOPED_KINDS:
        # attending(/attending-user)·directing(/directing-cells)은 cell 단위라
        # entity_id 가 없다 — 대상 cell 은 pod 에 이미 박혀 있다.
        entity_id = None
    elif entity_type in ENTITY_TYPES:
        if not entity_id or not _ENTITY_ID_RE.match(entity_id):
            return CapabilityResponse(
                status="error", error_code="invalid_entity_id",
                message="entity_id must match [A-Za-z0-9_-]{1,128} for entity sessions.",
            )
    elif entity_id is not None:
        return CapabilityResponse(
            status="error", error_code="invalid_entity",
            message="entity_id requires an entity_type.",
        )

    repo_url = await _fetch_cell_repo_url(cell_id, request)
    git_login, git_email = await _fetch_user_git_identity(request)
    console_jwt = _request_console_jwt(request)

    # sandbox TTL(최대 24h) 안에 JWT 가 만료되지 않도록 생성 시점에 갱신.
    if console_jwt and HUB_URL:
        refreshed = await _refresh_jwt_via_hub(console_jwt)
        if refreshed:
            console_jwt = refreshed
            log.info("console JWT refreshed at sandbox creation for %s", owner_email)
        else:
            log.warning(
                "console JWT refresh failed at sandbox creation for %s — "
                "using original (MCP auth may expire if JWT is near end-of-life)",
                owner_email,
            )

    pod = _build_pod(
        sandbox_id, cell_id, image,
        cpus=req.cpus, memory_mb=req.memory_mb,
        owner_email=owner_email, session_id=req.session_id,
        created_at=now, expires_at=expires_at,
        repo_url=repo_url,
        git_login=git_login, git_email=git_email,
        console_jwt=console_jwt,
        entity_type=entity_type, entity_id=entity_id,
        sandbox_name=sandbox_name,
    )
    try:
        await asyncio.to_thread(core_v1.create_namespaced_pod, SANDBOX_NAMESPACE, pod)
    except ApiException as e:
        return CapabilityResponse(status="error", error_code="create_failed", message=str(e))

    data = {
        "id": sandbox_id,
        "namespace": SANDBOX_NAMESPACE,
        "image": image,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "cell_id": cell_id,
        "owner_email": owner_email,
        "sandbox_name": sandbox_name,
        "status": "Pending",
        "repo_url": repo_url,
        "workdir": (pod.metadata.annotations or {}).get(ANNO_WORKDIR),
        "home_dir": (pod.metadata.annotations or {}).get(ANNO_HOME_DIR),
        "workspace_root": (pod.metadata.annotations or {}).get(ANNO_WORKSPACE_ROOT),
        "reused": False,
    }
    if req.session_id:
        data["session_id"] = req.session_id
    if entity_type:
        data["entity_type"] = entity_type
        if entity_id:
            data["entity_id"] = entity_id
    return CapabilityResponse(status="ok", data=data)


@app.post(
    "/sandbox.destroy",
    summary="Sandbox 삭제",
    openapi_extra={"x-side-effects": "external", "x-requires-approval": False},
)
async def sandbox_destroy(req: SandboxIdRequest, request: Request) -> CapabilityResponse:
    cell_id = _request_cell_id(request)
    owner_email = _request_owner_email(request)
    pod = await asyncio.to_thread(_find_pod, req.id, cell_id)
    if not pod:
        return CapabilityResponse(status="error", error_code="not_found", message=f"sandbox {req.id} not found.")
    if not _check_owner(pod, owner_email, cell_id):
        return CapabilityResponse(status="error", error_code="forbidden", message="access denied.")

    try:
        await asyncio.to_thread(
            core_v1.delete_namespaced_pod,
            name=req.id,
            namespace=pod.metadata.namespace,
            grace_period_seconds=5,
        )
    except ApiException as e:
        return CapabilityResponse(status="error", error_code="destroy_failed", message=str(e))
    return CapabilityResponse(status="ok", data={"id": req.id, "destroyed": True})


@app.post(
    "/sandbox.list",
    summary="Sandbox 목록",
    openapi_extra={"x-side-effects": "read-only", "x-requires-approval": False},
)
async def sandbox_list(req: SandboxListRequest, request: Request) -> CapabilityResponse:
    cell_id = _request_cell_id(request)
    owner_email = _request_owner_email(request)
    pods = await asyncio.to_thread(_list_pods_for_cell, cell_id)
    items = []
    for pod in pods:
        if not _check_owner(pod, owner_email, cell_id):
            continue
        items.append(_pod_info(pod))
    return CapabilityResponse(status="ok", data=items)


@app.post(
    "/sandbox.status",
    summary="Sandbox 상태 조회",
    openapi_extra={"x-side-effects": "read-only", "x-requires-approval": False},
)
async def sandbox_status(req: SandboxIdRequest, request: Request) -> CapabilityResponse:
    cell_id = _request_cell_id(request)
    owner_email = _request_owner_email(request)
    pod = await asyncio.to_thread(_find_pod, req.id, cell_id)
    if not pod:
        return CapabilityResponse(status="error", error_code="not_found", message=f"sandbox {req.id} not found.")
    if not _check_owner(pod, owner_email, cell_id):
        return CapabilityResponse(status="error", error_code="forbidden", message="access denied.")
    return CapabilityResponse(status="ok", data=_pod_info(pod))


@app.post(
    "/sandbox.extend",
    summary="Sandbox TTL 연장",
    description=f"현재 expires_at에 hours를 더함. 총 {MAX_TTL_HOURS}h 초과 불가.",
    openapi_extra={"x-side-effects": "mutates", "x-requires-approval": False},
)
async def sandbox_extend(req: SandboxExtendRequest, request: Request) -> CapabilityResponse:
    cell_id = _request_cell_id(request)
    owner_email = _request_owner_email(request)
    pod = await asyncio.to_thread(_find_pod, req.id, cell_id)
    if not pod:
        return CapabilityResponse(status="error", error_code="not_found", message=f"sandbox {req.id} not found.")
    if not _check_owner(pod, owner_email, cell_id):
        return CapabilityResponse(status="error", error_code="forbidden", message="access denied.")

    annos = pod.metadata.annotations or {}
    try:
        created_at = datetime.fromisoformat(annos[ANNO_CREATED_AT])
        current_expires = datetime.fromisoformat(annos[ANNO_EXPIRES_AT])
    except (KeyError, ValueError):
        return CapabilityResponse(status="error", error_code="invalid_state", message="annotation missing/invalid.")

    new_expires = current_expires + timedelta(hours=req.hours)
    total_hours = (new_expires - created_at).total_seconds() / 3600
    if total_hours > MAX_TTL_HOURS:
        return CapabilityResponse(
            status="error", error_code="ttl_exceeded",
            message=f"total {total_hours:.1f}h exceeds {MAX_TTL_HOURS}h.",
        )

    patch = {"metadata": {"annotations": {ANNO_EXPIRES_AT: new_expires.isoformat()}}}
    try:
        await asyncio.to_thread(
            core_v1.patch_namespaced_pod,
            name=req.id, namespace=pod.metadata.namespace, body=patch,
        )
    except ApiException as e:
        return CapabilityResponse(status="error", error_code="extend_failed", message=str(e))

    return CapabilityResponse(status="ok", data={
        "id": req.id, "expires_at": new_expires.isoformat(), "total_hours": round(total_hours, 1),
    })


def _exec_sync(ns: str, name: str, command: list[str]) -> tuple[int, str, str]:
    """동기 exec — output을 모아서 반환. exit_code, stdout, stderr."""
    resp = k8s_stream(
        exec_v1.connect_get_namespaced_pod_exec,
        name, ns,
        command=command,
        stderr=True, stdin=False, stdout=True, tty=False,
        _preload_content=False,
    )
    stdout_buf, stderr_buf = [], []
    while resp.is_open():
        resp.update(timeout=1)
        if resp.peek_stdout():
            stdout_buf.append(resp.read_stdout())
        if resp.peek_stderr():
            stderr_buf.append(resp.read_stderr())
    exit_code = 0
    try:
        # k8s exec returns exit code via error channel in JSON status
        rc = resp.returncode
        if rc is not None:
            exit_code = int(rc)
    except Exception:
        pass
    resp.close()
    return exit_code, "".join(stdout_buf), "".join(stderr_buf)


@app.post(
    "/sandbox.exec",
    summary="Sandbox에서 명령 실행",
    openapi_extra={"x-side-effects": "external", "x-requires-approval": False},
)
async def sandbox_exec(req: SandboxExecRequest, request: Request) -> CapabilityResponse:
    command = (req.command or "").strip()
    if not command:
        return CapabilityResponse(status="error", error_code="invalid_request", message="command is required.")

    cell_id = _request_cell_id(request)
    owner_email = _request_owner_email(request)
    pod = await asyncio.to_thread(_find_pod, req.id, cell_id)
    if not pod:
        return CapabilityResponse(status="error", error_code="not_found", message=f"sandbox {req.id} not found.")
    if not _check_owner(pod, owner_email, cell_id):
        return CapabilityResponse(status="error", error_code="forbidden", message="access denied.")
    if pod.status and pod.status.phase != "Running":
        return CapabilityResponse(
            status="error", error_code="not_running",
            message=f"sandbox {req.id} phase={pod.status.phase}.",
        )

    cmd = ["bash", "-lc", command if not req.workdir else f"cd {req.workdir!r} && {command}"]
    try:
        exit_code, stdout, stderr = await asyncio.to_thread(
            _exec_sync, pod.metadata.namespace, req.id, cmd,
        )
    except ApiException as e:
        return CapabilityResponse(status="error", error_code="exec_failed", message=str(e))

    stdout_t, stdout_trunc = _trim(stdout)
    stderr_t, stderr_trunc = _trim(stderr)
    return CapabilityResponse(status="ok", data={
        "id": req.id,
        "command": command,
        "workdir": req.workdir or "",
        "exit_code": exit_code,
        "stdout": stdout_t,
        "stderr": stderr_t,
        "stdout_truncated": stdout_trunc,
        "stderr_truncated": stderr_trunc,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    })


# ── WebSocket 터미널 ─────────────────────────────────────────────────────────

def _handle_ws_control(kube_stream, payload: str) -> None:
    """UI의 in-band 제어 메시지(__hive_control__:{...}) 처리. 현재는 resize만 지원."""
    try:
        msg = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return
    if msg.get("type") == "resize":
        cols = int(msg.get("cols") or 0)
        rows = int(msg.get("rows") or 0)
        if cols <= 0 or rows <= 0:
            return
        try:
            kube_stream.write_channel(K8S_EXEC_RESIZE_CHANNEL,
                                      json.dumps({"Width": cols, "Height": rows}))
        except Exception as e:
            log.warning("resize failed: %s", e)


@app.websocket("/sandbox.ws")
async def sandbox_ws(websocket: WebSocket):
    await websocket.accept()
    sandbox_id = (websocket.query_params.get("id") or "").strip()
    sandbox_name = (websocket.query_params.get("name") or "").strip() or None
    cell_id = (websocket.query_params.get("cell_id") or DEFAULT_CELL_ID).strip() or DEFAULT_CELL_ID
    if sandbox_name and not _SANDBOX_NAME_RE.match(sandbox_name):
        await websocket.send_text("[error] invalid sandbox name")
        await websocket.close(code=1008)
        return
    if not sandbox_id and not sandbox_name:
        await websocket.send_text("[error] sandbox id or name required")
        await websocket.close(code=1008)
        return

    owner_email = _websocket_owner_email(websocket)
    # cell 인가 게이트 — 생성·attach 공통. 권한 없는 cell 의 세션을 띄우거나(생성)
    # 사전 존재 pod 에 재접속(attach)하는 것을 차단한다. 하류 MCP 게이트가 데이터
    # 접근은 막지만, 무력한 세션 껍데기조차 권한 없으면 열리면 안 된다 (방어 다층화).
    if not await _authorize_cell_access(cell_id, _request_console_jwt(websocket)):
        await websocket.send_text(f"[error] cell '{cell_id}' 접근 권한이 없습니다")
        await websocket.close(code=1008)
        return
    if not sandbox_id and sandbox_name:
        if not SANDBOX_HOME_PVC:
            await websocket.send_text("[error] named sandbox requires SANDBOX_HOME_PVC")
            await websocket.close(code=1011)
            return
        pod = await asyncio.to_thread(_find_named_pod, cell_id, owner_email, sandbox_name)
        if not pod:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(hours=DEFAULT_TTL_HOURS)
            repo_url = await _fetch_cell_repo_url(cell_id, websocket)
            git_login, git_email = await _fetch_user_git_identity(websocket)
            console_jwt = _request_console_jwt(websocket)
            if console_jwt and HUB_URL:
                refreshed = await _refresh_jwt_via_hub(console_jwt)
                console_jwt = refreshed or console_jwt

            entity_type = (websocket.query_params.get("entity_type") or "").strip() or None
            entity_id = (websocket.query_params.get("entity_id") or "").strip() or None
            if entity_type in CELL_SCOPED_KINDS:
                entity_id = None
            elif entity_type in ENTITY_TYPES:
                if not entity_id or not _ENTITY_ID_RE.match(entity_id):
                    await websocket.send_text("[error] invalid entity binding")
                    await websocket.close(code=1008)
                    return
            elif entity_type is not None or entity_id is not None:
                await websocket.send_text("[error] invalid entity binding")
                await websocket.close(code=1008)
                return

            sandbox_id = f"sandbox-{uuid.uuid4().hex[:8]}"
            new_pod = _build_pod(
                sandbox_id, cell_id, DEFAULT_IMAGE,
                cpus=DEFAULT_CPUS, memory_mb=DEFAULT_MEMORY_MB,
                owner_email=owner_email, session_id=None,
                created_at=now, expires_at=expires_at,
                repo_url=repo_url,
                git_login=git_login, git_email=git_email,
                console_jwt=console_jwt,
                entity_type=entity_type, entity_id=entity_id,
                sandbox_name=sandbox_name,
            )
            try:
                await asyncio.to_thread(core_v1.create_namespaced_pod, SANDBOX_NAMESPACE, new_pod)
            except ApiException as e:
                await websocket.send_text(f"[error] sandbox create failed: {e}")
                await websocket.close(code=1011)
                return
            pod = new_pod
        sandbox_id = pod.metadata.name

    pod = await asyncio.to_thread(_find_pod, sandbox_id, cell_id)
    if not pod:
        await websocket.send_text(f"[error] sandbox {sandbox_id} not found")
        await websocket.close(code=1008)
        return
    if not _check_owner(pod, owner_email, cell_id):
        await websocket.close(code=1008)
        return

    # 갓 만든 sandbox는 ContainerCreating 단계라 Running까지 대기.
    deadline = asyncio.get_event_loop().time() + WS_POD_READY_TIMEOUT
    while pod.status and pod.status.phase != "Running":
        if pod.status.phase in ("Failed", "Succeeded"):
            await websocket.send_text(f"[error] sandbox phase={pod.status.phase}")
            await websocket.close(code=1011)
            return
        if asyncio.get_event_loop().time() > deadline:
            await websocket.send_text(f"[error] sandbox not ready (phase={pod.status.phase})")
            await websocket.close(code=1011)
            return
        await asyncio.sleep(1)
        pod = await asyncio.to_thread(_find_pod, sandbox_id, cell_id)
        if not pod:
            await websocket.send_text(f"[error] sandbox {sandbox_id} disappeared")
            await websocket.close(code=1008)
            return

    ns = pod.metadata.namespace
    annos = pod.metadata.annotations or {}
    labels = pod.metadata.labels or {}
    default_workdir = annos.get(ANNO_WORKDIR) or "/"
    workdir = (websocket.query_params.get("workdir") or default_workdir).strip() or default_workdir
    home_dir = annos.get(ANNO_HOME_DIR) or SANDBOX_SHARED_MOUNT
    sandbox_name = labels.get(LABEL_SANDBOX_NAME)
    entity_type = annos.get(ANNO_ENTITY_TYPE) or None
    entity_id = annos.get(ANNO_ENTITY_ID) or None
    # skill-bound 세션은 bash 대신 claude 를 띄우고 해당 skill 로 부팅한다.
    # 진입 검증(타입·문자집합)은 sandbox.create 가 이미 수행했으므로 여기선 신뢰.
    prompt: str | None = None
    if entity_type == ATTENDING_KIND:
        # cross-cell 광역 1:1. entity_id 없음.
        prompt = "/attending-user"
    elif entity_type == DIRECTING_KIND:
        # 이 cell 의 CEO 전략 대화. 대상 cell 은 pod 의 cell 라벨 — query param 보다
        # 권위 있는 출처(_find_pod 가 이미 cell 일치를 검증). 라벨 부재 시 query 폴백.
        # entity_id(steering) 와 같은 자리 — prompt 전체가 아래서 shlex.quote 되어
        # claude 한 인자로 들어간다. cell id 는 안전 문자라 추가 인용 불필요.
        pod_cell = (pod.metadata.labels or {}).get(LABEL_CELL_ID) or cell_id
        prompt = f"/directing-cells {pod_cell}"
    elif entity_type in ENTITY_TYPES and entity_id and _ENTITY_ID_RE.match(entity_id):
        # issue 는 --direct 기본 — UI 진입은 사람이 직접 코드·PR 을 모는 케이스라
        # hold 가드 + 직접 실행 모드가 자연 default (i-tems/hive steering-issues spec).
        # project · initiative skill 은 --direct 옵션이 없어 그대로.
        prompt = f"/steering-{entity_type}s {entity_id}"
        if entity_type == "issue":
            prompt += " --direct"
    # 좀비 정리(claude 세션 공통): k8s exec 는 stream 이 닫혀도 프로세스를 안 죽여
    # tmux 없는 지금 직전 접속의 claude 가 좀비로 남는다. 새로 띄우기 전에 기존
    # claude(comm 정확히 "claude")를 정리해 단일 claude 보장(동시 2접속은 last-wins).
    # bash 런처·mcp daemon 은 comm 이 달라 무사.
    kill_stale = (
        "pkill -TERM -x claude 2>/dev/null || true; "
        "for _ in 1 2 3 4 5; do pgrep -x claude >/dev/null 2>&1 || break; sleep 0.4; done; "
        "pkill -KILL -x claude 2>/dev/null || true; "
    )
    if prompt is not None or sandbox_name:
        # 재개(resume)는 claude 네이티브 --continue('이 cwd 의 최신 대화')로 한다.
        # 이 cwd 의 project 에 transcript 가 있으면 --continue, 없으면 첫 실행이라 초기
        # 명령으로 시작 — skill 은 스킬 프롬프트(claude /steering-* 등), named 는 bare.
        #
        # 격리는 **cwd** 가 보장한다 — _build_pod 가 cwd 를 (owner, cell, name|entity)별
        # 고유·불변으로 만들어, 그 project 엔 이 정체성의 세션만 있고 --continue 가 그것만
        # resume 한다. 다른 사용자·엔티티는 cwd 가 달라 절대 안 섞인다.
        #
        # 결정적 session-id(--session-id/--resume) 방식은 쓰지 않는다: claude 의 id
        # 유일성 검사는 **전역**인데 --resume 은 **cwd 한정**이라, 같은 id 가 다른
        # project(예: cwd 포맷 변경으로 생긴 옛 transcript)에 있으면 생성은 "already in
        # use", 재개는 "no conversation found" 로 갈려 막힌다. --continue 는 생성 시 id 를
        # 안 박아(claude 가 매번 새 id 생성) 이 충돌 자체가 없다.
        #
        # 존재 체크는 claude 의 실제 project 경로로 한다(_claude_project_dir). cwd 슬러그는
        # 영숫자·하이픈 외 모든 문자를 '-' 로 바꾼 것 — `sed 's#/#-#g'` 로 추측하면 owner
        # segment 의 '.'(gmail.com) 에서 어긋난다.
        proj = _claude_project_dir(home_dir, workdir)
        first = f"claude {shlex.quote(prompt)}" if prompt is not None else "claude"
        inner = kill_stale + (
            f"if ls {shlex.quote(proj)}/*.jsonl >/dev/null 2>&1; then exec claude --continue; "
            f"else exec {first}; fi"
        )
    else:
        # 익명 1회용 sandbox — plain shell.
        inner = "exec bash -il"
    # tmux 래퍼 제거 — 완전 네이티브 터미널: 수식키(Shift+Enter 등)·드래그·복사·붙여넣기
    # 가 터미널↔claude 직결로 동작한다(tmux 가 중간에서 키/마우스를 가공하지 않음).
    # 영속성은 위 claude --continue 로 대체(detach/reattach 대신 resume). resize 는 WS 가
    # exec PTY 의 resize 채널로 직접 전달.
    # CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1: claude 를 classic 렌더(메인 화면, alt
    # screen 미사용)로 돌린다 → 대화가 터미널 일반 스크롤백에 찍혀 **휠=네이티브
    # 스크롤**, 그리고 claude 가 마우스를 아예 안 잡아 **드래그=네이티브 선택**. 둘 다
    # 네이티브로 해결한다. (fullscreen 이 2.1.89+ 기본인데, 거기서 마우스를 끄면 휠이
    # 화살표키로 와 "scroll wheel sending arrow keys" 로 깨졌다 — 그래서 DISABLE_MOUSE
    # 대신 alt-screen 자체를 끈다. A/B 검증: alt_screen·mouse_enable 둘 다 True→False.)
    cmd = ["bash", "-lc",
           f"mkdir -p {shlex.quote(home_dir)} {shlex.quote(workdir)} 2>/dev/null; "
           f"export HOME={shlex.quote(home_dir)} SHARED_DIR={shlex.quote(home_dir)} "
           f"SPECS_ROOT={shlex.quote(home_dir + '/specs')} CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1; "
           f"cd {shlex.quote(workdir)} 2>/dev/null; "
           f"{inner}"]

    try:
        kube_stream = await asyncio.to_thread(
            lambda: k8s_stream(
                exec_v1.connect_get_namespaced_pod_exec,
                sandbox_id, ns,
                command=cmd,
                stderr=True, stdin=True, stdout=True, tty=True,
                _preload_content=False,
            )
        )
    except ApiException as e:
        await websocket.send_text(f"[error] exec init failed: {e}")
        await websocket.close(code=1011)
        return

    loop = asyncio.get_running_loop()
    stop_event = threading.Event()

    def _pump_kube_to_ws():
        while not stop_event.is_set() and kube_stream.is_open():
            try:
                kube_stream.update(timeout=0.2)
                if kube_stream.peek_stdout():
                    chunk = kube_stream.read_stdout()
                    asyncio.run_coroutine_threadsafe(websocket.send_text(chunk), loop)
                if kube_stream.peek_stderr():
                    chunk = kube_stream.read_stderr()
                    asyncio.run_coroutine_threadsafe(websocket.send_text(chunk), loop)
            except Exception:
                break
        # kube_stream 이 자연 종료(안에서 돌던 claude/bash exit) 했을 때만 WS 를
        # 정상 종료 코드(1000)로 닫는다 — 클라이언트가 transient 끊김으로 오인해
        # retry 3회 (= bash exec 3회 재실행 = 안에서 claude 3번 재부팅) 하던 것 차단.
        # stop_event 가 set 됐다면 메인 측 cleanup 경로라 여기서 또 닫으면 race.
        if not stop_event.is_set():
            try:
                asyncio.run_coroutine_threadsafe(
                    websocket.close(code=1000, reason="exec finished"),
                    loop,
                )
            except Exception as e:
                log.debug("pump close failed: %s", e)

    pump = threading.Thread(target=_pump_kube_to_ws, daemon=True)
    pump.start()

    try:
        while True:
            msg = await websocket.receive_text()
            if not msg:
                continue
            if msg.startswith(WS_CONTROL_PREFIX):
                _handle_ws_control(kube_stream, msg[len(WS_CONTROL_PREFIX):])
                continue
            kube_stream.write_stdin(msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ws error: %s", e)
    finally:
        stop_event.set()
        try:
            kube_stream.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


# ── Reaper — 만료된 sandbox 정리 ─────────────────────────────────────────────

async def _reaper_loop():
    log.info("reaper started, interval=%ss", REAPER_INTERVAL)
    while True:
        try:
            await asyncio.to_thread(_reap_expired_pods)
        except Exception as e:
            log.warning("reaper error: %s", e)
        await asyncio.sleep(REAPER_INTERVAL)


def _reap_expired_pods():
    now = datetime.now(timezone.utc)
    selector = f"{LABEL_MANAGED}=true,{LABEL_ROLE}={ROLE_SANDBOX}"
    try:
        pods = core_v1.list_namespaced_pod(SANDBOX_NAMESPACE, label_selector=selector)
    except ApiException as e:
        log.warning("reaper list failed: %s", e)
        return
    for pod in pods.items:
        annos = pod.metadata.annotations or {}
        expires_raw = annos.get(ANNO_EXPIRES_AT)
        if not expires_raw:
            continue
        try:
            expires_at = datetime.fromisoformat(expires_raw)
        except ValueError:
            continue
        if expires_at <= now:
            try:
                core_v1.delete_namespaced_pod(pod.metadata.name, SANDBOX_NAMESPACE, grace_period_seconds=5)
                log.info("reaped expired sandbox %s", pod.metadata.name)
            except ApiException as e:
                log.warning("reap failed %s: %s", pod.metadata.name, e)


@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(_reaper_loop())
