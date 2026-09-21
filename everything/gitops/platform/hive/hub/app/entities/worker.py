"""Worker heartbeat — agent-loop이 spawn한 워커들의 in-flight 상태를 hub에 모아 UI/사용자에게 노출.

저장은 in-memory dict (hub replicas=1 전제). pod 재시작 시 휘발 — 다음 heartbeat이
다시 채운다. 인증된 worker principal의 cell_id/issue_id를 그대로 사용하므로 추가
입력 검증 불필요.
"""

import glob
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from threading import Lock

from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse
from ..storage.sql import (
    upsert_heartbeat, get_heartbeat, list_heartbeats, prune_heartbeats, delete_heartbeat,
)

from .. import wake_bus

router = APIRouter()

# heartbeat 주기 5s 가정, ttl 30s — 6회 연속 누락 시 stale. 저장은 SQL
# worker_heartbeats 테이블 (INFRA-ISSUE-284, 옛 in-memory _HEARTBEATS 대체) —
# multi-replica/롤아웃 overlap 에서 어느 pod 가 받아도 일관된 워커 목록.
TTL_SECONDS = 30

# ── AI activity relay (PR #146 stdout `[ai-activity]` 채널 대체) ──────────────
# 워커 runtime 이 캡처한 text/tool_use/tool_result 를 worker.activity_push 로
# 받아 세션별 ring buffer 에 적재. worker.activity_list (UI 콘솔) 가 읽고,
# push 시 wake_bus.notify(act:<entity_id>) → SSE 가 그 전용 키로 UI 를 깨워
# 거의 실시간 refetch. 저장은 in-memory (hub replicas=1 전제 — _HEARTBEATS 와
# 동일). pod 재시작 시 휘발, 다음 push 가 다시 채운다.
#
# 전용 키인 이유: bare entity_id 키는 워커 자신의 idle long-poll
# (agent worker `_wait_for_wake` → wake.wait_for_change → wake_bus
# .wait_for_change(entity_id))이 듣는 키다. activity_push 가 그 키를 bump 하면
# 워커가 *자기 transcript 스트림으로 자기 idle 대기를 깨워* waiting/cleanup
# 에서 빈 유료 turn 을 busy-loop 한다 (관측: waiting 진입 38s 동안 6턴, ~4-11s
# 간격). entity 의 *실제* 변경(comment/status/field)은 events.py 가 bare
# entity_id 로 notify 하므로 워커 wake 는 그쪽으로만 일어나야 한다. UI 는
# act:<id> 를 추가 구독(sse.py)해 그대로 near-real-time 을 유지한다.
#
# key = f"{cell_id}\x1f{entity_type}\x1f{entity_id}". project 워커는 caller token
# 에 issue_id 가 없으므로(loop._mint_caller_token) entity_type/entity_id 는 push
# payload 에서 받고 cell_id 만 신뢰된 worker principal 에서 취한다.
_ACTIVITY: dict[str, dict] = {}
_ACT_LOCK = Lock()
# 세션 transcript ring buffer 상한 (bucket 당 item 수). 긴 turn 도 최근분만 유지.
_ACT_MAX_ITEMS = 500
# 마지막 push 이후 이 시간(초) 넘게 조용한 bucket 은 list 시 정리 (메모리 상한).
# 워커 종료 후에도 사용자가 마지막 transcript 를 읽을 시간을 충분히 둔다.
_ACT_TTL_SECONDS = 1800
# 이 시간(초) 내 push 가 있었으면 워커가 active 한 것으로 표시 (UI 점멸 닷).
_ACT_ACTIVE_WINDOW = 90
# wake_bus.notify(entity_id) 디바운스. relay 는 ~1s 마다 flush 하지만, 매 push
# 마다 notify 하면 Issue/GoalDetail 의 무거운 page fetcher(issue.get + project.get +
# event.list + …)가 그 주기로 재실행된다. 버퍼는 모든 item 을 모으되 notify 만
# entity 당 이 간격으로 합쳐 page refetch 부하를 묶는다 (near-real-time 유지).
_ACT_NOTIFY_MIN_INTERVAL = 2.0
_ACT_LAST_NOTIFY: dict[str, float] = {}


def _act_key(cell_id: str, entity_type: str, entity_id: str) -> str:
    return f"{cell_id}\x1f{entity_type}\x1f{entity_id}"


# activity 스트림 전용 wake 키. bare entity_id (워커 idle long-poll 키) 와
# 분리해 워커가 자기 transcript push 로 자신을 깨우지 않게 한다. sse.py 의
# entity 구독이 이 키도 함께 듣는다 (UI near-real-time 유지).
def _act_wake_key(entity_id: str) -> str:
    return f"act:{entity_id}"


def _parse_iso(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# JSON 문자열 안에 SDK 가 흘려보낸 짝 없는 surrogate(고:`\uD800-\uDBFF` 또는
# 저:`\uDC00-\uDFFF` 단독)가 박혀 있으면, Starlette JSONResponse 의
# `json.dumps(..., ensure_ascii=False).encode("utf-8")` 가 UnicodeEncodeError 로
# 터져 endpoint 전체가 500. (관측 사례: Anthropic API 가 mid-stream 끊긴 응답을
# 그대로 JSONL 에 남겨 lone surrogate 가 다음 turn 의 transcript 에 보존됨.)
# 정상 surrogate pair 는 `json.loads` 가 JSON RFC 8259 §8.2 대로 supplementary
# 코드포인트로 결합해 주므로, 디코드 후 Python str 에 남는 surrogate 는 정의상
# 모두 orphan — `[\uD800-\uDFFF]` 단순 매치로 안전하게 잡힌다.
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _sanitize_surrogates(s: str) -> str:
    """짝 없는 surrogate 를 U+FFFD 로 치환해 항상 valid UTF-8 로 인코딩 가능하게."""
    return _SURROGATE_RE.sub("�", s)


class HeartbeatRequest(BaseModel):
    phase: str | None = None  # "bootstrap" | "claude_run" | "publish" | "post_dispatch"
    note: str | None = None   # 자유 텍스트 — 진행 메모
    session_id: str | None = None  # claude session — UI에서 Langfuse 트레이스로 직결


@router.post("/worker.heartbeat")
async def worker_heartbeat(req: HeartbeatRequest, request: Request) -> CapabilityResponse:
    """워커가 살아있다고 hub에 통보. principal에서 worker_id/cell_id/issue_id 추출."""
    p = getattr(request.state, "principal", None)
    if p is None or p.type != "worker":
        return CapabilityResponse(
            status="error", error_code="forbidden",
            message="worker principal required",
        )
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = get_heartbeat(p.id)
    # session_id는 한 번 set되면 다음 heartbeat에서 None으로 와도 보존 (claude
    # 실행 후 받은 sid가 cleanup phase 동안 사라지지 않게).
    prev_sid = (existing or {}).get("session_id")
    record = {
        "worker_id": p.id,
        "cell_id": p.cell_id,
        "issue_id": p.issue_id,
        "session_type": p.session_type,
        "started_at": (existing or {}).get("started_at", now_iso),
        "last_seen": now_iso,
        "phase": req.phase,
        "note": req.note,
        "session_id": req.session_id or prev_sid,
    }
    upsert_heartbeat(p.id, record)
    return CapabilityResponse(status="ok", data=record)


class WorkerListRequest(BaseModel):
    cell_id: str | None = None
    issue_id: str | None = None


@router.post("/worker.list_active")
def worker_list_active(req: WorkerListRequest, request: Request) -> CapabilityResponse:
    """살아있는 워커 목록. ttl 지난 항목은 정리."""
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=TTL_SECONDS)).isoformat()
    prune_heartbeats(cutoff_iso)
    out = []
    for rec in list_heartbeats(cutoff_iso):
        if req.cell_id and rec.get("cell_id") != req.cell_id:
            continue
        if req.issue_id and rec.get("issue_id") != req.issue_id:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("started_at") or "")
    return CapabilityResponse(status="ok", data={"workers": out, "count": len(out)})


@router.post("/worker.clear")
async def worker_clear(request: Request) -> CapabilityResponse:
    """워커가 정상 종료 시 자기 entry를 즉시 제거. principal에서 worker_id 추출."""
    p = getattr(request.state, "principal", None)
    if p is None or p.type != "worker":
        return CapabilityResponse(
            status="error", error_code="forbidden",
            message="worker principal required",
        )
    delete_heartbeat(p.id)
    return CapabilityResponse(status="ok", data={"worker_id": p.id})


# ── AI activity relay endpoints ──────────────────────────────────────────────

class ActivityEvent(BaseModel):
    seq: int
    ts: str
    kind: str  # "text" | "tool_use" | "tool_result" | "turn"
    text: str | None = None
    tool: str | None = None
    # tool_use↔tool_result 정확 페어링 키 (이름+추정 폐기 — 병렬·동일이름 정합).
    tool_use_id: str | None = None
    input: str | None = None
    output: str | None = None
    is_error: bool | None = None
    # kind=="turn": 그 turn 에 워커가 받은 주입 프롬프트(작업 지시/델타).
    prompt: str | None = None


class ActivityPushRequest(BaseModel):
    entity_type: str  # "issue" | "project" | "initiative"
    entity_id: str
    session_id: str | None = None
    events: list[ActivityEvent] = []


@router.post("/worker.activity_push")
async def worker_activity_push(req: ActivityPushRequest, request: Request) -> CapabilityResponse:
    """워커가 캡처한 AI activity batch 를 hub 세션별 ring buffer 에 적재.

    인증된 worker principal 의 cell_id 만 신뢰하고 entity_type/entity_id 는
    payload 에서 받는다 (project 워커는 token claim 에 issue_id 가 없음). 적재 후
    wake_bus.notify(act:<entity_id>) — 전용 키라 워커 idle long-poll 을 깨우지
    않고, sse.py 의 entity 구독이 이 키도 들으므로 UI 는 near-real-time 유지.
    """
    p = getattr(request.state, "principal", None)
    if p is None or p.type != "worker":
        return CapabilityResponse(
            status="error", error_code="forbidden",
            message="worker principal required",
        )
    entity_type = (req.entity_type or "").strip()
    entity_id = (req.entity_id or "").strip()
    if entity_type not in ("issue", "project", "initiative") or not entity_id:
        return CapabilityResponse(
            status="error", error_code="invalid_request",
            message="entity_type(issue|project|initiative) and entity_id required",
        )
    now_iso = datetime.now(timezone.utc).isoformat()
    key = _act_key(p.cell_id, entity_type, entity_id)
    with _ACT_LOCK:
        bucket = _ACTIVITY.get(key)
        # 새 claude 세션 = 새 transcript → buffer 리셋 (옛 turn 잔재 노출 방지).
        if bucket is None or (req.session_id and bucket.get("session_id") != req.session_id):
            bucket = {
                "cell_id": p.cell_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "session_id": req.session_id,
                "started_at": now_iso,
                "last_seen": now_iso,
                "last_seq": 0,
                "items": deque(maxlen=_ACT_MAX_ITEMS),
            }
            _ACTIVITY[key] = bucket
        if req.session_id:
            bucket["session_id"] = req.session_id
        bucket["last_seen"] = now_iso
        for ev in req.events:
            d = ev.model_dump(exclude_none=True)
            # ingest 경계 — corrupted text 가 ring buffer 에 들어오면 이후 모든
            # 소비자(activity_list/SSE/향후 export) 가 같이 깨진다. lone
            # surrogate 만 치환 (정상 문자는 손대지 않음).
            for k in ("text", "tool", "tool_use_id", "input", "output", "prompt"):
                v = d.get(k)
                if isinstance(v, str):
                    d[k] = _sanitize_surrogates(v)
            bucket["items"].append(d)
            if ev.seq > bucket["last_seq"]:
                bucket["last_seq"] = ev.seq
        last_seq = bucket["last_seq"]
        # notify 디바운스 — entity 당 _ACT_NOTIFY_MIN_INTERVAL 마다만.
        mono = time.monotonic()
        should_notify = bool(req.events) and (
            mono - _ACT_LAST_NOTIFY.get(key, 0.0) >= _ACT_NOTIFY_MIN_INTERVAL
        )
        if should_notify:
            _ACT_LAST_NOTIFY[key] = mono
    # 변경 통지 — activity 전용 키. SSE 구독자(Issue/GoalDetail)는 이 키도 들어
    # 깨어 refetch 하지만, 워커 자신의 idle long-poll(bare entity_id)은 안 깬다.
    if should_notify:
        wake_bus.notify(_act_wake_key(entity_id))
    return CapabilityResponse(status="ok", data={"accepted": len(req.events), "last_seq": last_seq})


class ActivityListRequest(BaseModel):
    entity_type: str
    entity_id: str
    after_seq: int | None = None  # 지정 시 그 seq 초과 item 만 (증분 조회)


@router.post("/worker.activity_list")
def worker_activity_list(req: ActivityListRequest, request: Request) -> CapabilityResponse:
    """UI 콘솔용 — 한 entity 의 live AI transcript + 워커 상태 요약.

    cell 스코프는 CellMiddleware 가 검증해 request.state.cell_id 로 주입 (콘솔
    JWT + X-Cell-Id). worker.list_active 와 같은 console 경로 계약.
    """
    cell_id = getattr(request.state, "cell_id", None)
    if not cell_id:
        return CapabilityResponse(
            status="error", error_code="cell_id_required",
            message="cell_id required",
        )
    entity_type = (req.entity_type or "").strip()
    entity_id = (req.entity_id or "").strip()
    if entity_type not in ("issue", "project", "initiative") or not entity_id:
        return CapabilityResponse(
            status="error", error_code="invalid_request",
            message="entity_type(issue|project|initiative) and entity_id required",
        )
    key = _act_key(cell_id, entity_type, entity_id)
    cutoff = datetime.now(timezone.utc).timestamp() - _ACT_TTL_SECONDS
    active_cut = datetime.now(timezone.utc).timestamp() - _ACT_ACTIVE_WINDOW
    with _ACT_LOCK:
        # TTL 정리 (조용한 bucket 메모리 회수).
        for k in list(_ACTIVITY.keys()):
            if _parse_iso(_ACTIVITY[k]["last_seen"]) < cutoff:
                del _ACTIVITY[k]
                _ACT_LAST_NOTIFY.pop(k, None)
        bucket = _ACTIVITY.get(key)
        if bucket is None:
            data = {
                "session_id": None, "started_at": None, "last_seen": None,
                "active": False, "last_seq": 0, "items": [],
            }
        else:
            items = list(bucket["items"])
            if req.after_seq is not None:
                items = [it for it in items if it.get("seq", 0) > req.after_seq]
            data = {
                "session_id": bucket.get("session_id"),
                "started_at": bucket.get("started_at"),
                "last_seen": bucket.get("last_seen"),
                "active": _parse_iso(bucket["last_seen"]) >= active_cut,
                "last_seq": bucket.get("last_seq", 0),
                "items": items,
            }
    return CapabilityResponse(status="ok", data=data)


# ── durable 과거 이력 (worker.activity_history) ───────────────────────────────
# ring buffer 는 휘발성(최근 turn·30분·hub 재시작 전까지)이라 과거 이력이 안
# 남는다. 그런데 Agent SDK 가 turn 마다 세션 transcript 를 JSONL 로 남기고
# (HOME=/data/shared → /data/shared/.claude/projects/<cwd-slug>/<sid>.jsonl),
# 그게 hub 와 같은 NFS(data PVC)라 hub 가 직접 읽을 수 있다. 신규 저장소 없이
# 이미 존재하는 세션 파일을 durable 과거 소스로 재사용한다 (Langfuse·신규 DB
# 불필요).

# hub 가 보는 공유 .claude/projects 루트. data PVC 가 /data 에, 그 하위
# shared/.claude/projects 가 워커의 $HOME/.claude/projects 와 같은 위치.
_CLAUDE_PROJECTS_ROOT = os.environ.get(
    "CLAUDE_PROJECTS_ROOT", "/data/shared/.claude/projects"
)
# 과거 파싱 상한 (entity 당, 최신 우선). 거대한 누적 세션에서 OOM·지연 차단 —
# 사이드바 과거 스크롤엔 최근 수천 프레임이면 충분.
_HIST_MAX_EVENTS = 20000
_HIST_TEXT_LIMIT = 4000
_HIST_FIELD_LIMIT = 2000


def _hist_fmt(value, limit: int) -> str:
    """history 프레임 필드 절단 — live relay(_trunc)와 동일하게 원문(개행
    포함)을 보존하고 길이만 절단한다.

    과거엔 `" ".join(s.split())` 로 모든 공백·개행을 단일 스페이스로 뭉갰다.
    그 결과 durable 과거(첫·옛 turn)의 prompt·답이 한 줄로 붙어 마크다운
    구조(헤더·리스트·코드펜스)가 사라졌고, 개행을 보존하는 live turn 과
    렌더가 갈렸다 — "첫 요청만 마크다운 미적용"의 근본 원인. live(_trunc)
    와 정확히 동일 동작(길이 절단만)으로 맞춰 parity 를 복원한다.
    """
    if isinstance(value, str):
        s = value
    else:
        try:
            s = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            s = str(value)
    # ingest 경계 — JSONL 에 보존된 lone surrogate 가 응답 직렬화(UTF-8 인코딩)를
    # 깨뜨리지 않게 여기서 치환한다. live push 와 동일한 정책.
    s = _sanitize_surrogates(s)
    return s if len(s) <= limit else f"{s[:limit]}…(+{len(s) - limit} chars)"


def _entity_session_dirs(cell_id: str, entity_type: str, entity_id: str) -> list[str]:
    """그 entity 의 **loop 워커** cwd(/data/workspaces/<cell>/<entity>/cell)에 대응
    하는 SDK projects 디렉토리들. slug = cwd 의 '/'→'-'. WORKSPACE 변형·legacy 대비
    `-data-workspaces-*-<entity_id>-cell` glob 도 합쳐 robust 하게.

    매칭은 loop 워커 workspace(`/data/workspaces/...`)로 한정한다. 사람이 직접
    attach 한 터미널 skill 세션은 cwd 가 `/work/sessions/<cell>/<type>/<id>/cell`
    → slug `-work-sessions-…-<id>-cell` 로 같은 `-<id>-cell` 접미사를 갖지만, AI
    Activity 는 자율 loop 의 이력이라 사람 터미널 세션이 섞이면 안 된다. 접두
    `-data-workspaces-` 로 가른다 (metric.py `_WS_DIR_RE` 와 동일 경계)."""
    root = _CLAUDE_PROJECTS_ROOT
    found: set[str] = set()
    exact_cwd = f"/data/workspaces/{cell_id}/{entity_id}/cell"
    exact = root + "/" + exact_cwd.replace("/", "-")
    if os.path.isdir(exact):
        found.add(exact)
    prefix = "-data-workspaces-"
    suffix = f"-{entity_id}-cell"
    try:
        for d in glob.glob(f"{root}/{prefix}*{suffix}"):
            b = os.path.basename(d)
            if os.path.isdir(d) and b.startswith(prefix) and b.endswith(suffix):
                found.add(d)
    except OSError:
        pass
    return sorted(found)


def _ts_epoch(ts) -> float:
    """ISO8601 → epoch 초. `...Z` / `...+00:00` / naive / 결측 모두 흡수.
    파싱 불가는 0.0 (tiebreaker 가 원래 순서 보존)."""
    if not ts or not isinstance(ts, str):
        return 0.0
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def _parse_session_events(path: str) -> list[dict]:
    """SDK 세션 JSONL → 배포된 ActivityEvent 스키마(text/tool_use/tool_result).
    thinking·user prompt·meta 라인은 제외 (live runtime 이 emit 하던 것과 동일).
    """
    out: list[dict] = []
    tool_names: dict[str, str] = {}
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            typ = o.get("type")
            ts = o.get("timestamp") or ""
            msg = o.get("message") or {}
            if typ == "assistant":
                for b in (msg.get("content") or []):
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "text":
                        txt = (b.get("text") or "").strip()
                        if txt:
                            out.append({"ts": ts, "kind": "text",
                                        "text": _hist_fmt(txt, _HIST_TEXT_LIMIT)})
                    elif bt == "tool_use":
                        nm = b.get("name") or "?"
                        bid = b.get("id") or ""
                        if bid:
                            tool_names[bid] = nm
                        out.append({"ts": ts, "kind": "tool_use", "tool": nm,
                                    "tool_use_id": bid,
                                    "input": _hist_fmt(b.get("input"), _HIST_FIELD_LIMIT)})
                    # thinking 등은 제외.
            elif typ == "user":
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict) or b.get("type") != "tool_result":
                            continue
                        rid = b.get("tool_use_id") or ""
                        out.append({
                            "ts": ts, "kind": "tool_result",
                            "tool": tool_names.get(rid, "?"),
                            "tool_use_id": rid,
                            "is_error": bool(b.get("is_error", False)),
                            "output": _hist_fmt(b.get("content"), _HIST_FIELD_LIMIT),
                        })
                elif isinstance(content, str) and content.strip():
                    # 자율 워커가 매 turn 받는 주입 프롬프트(엔티티 JSON/델타).
                    # 사용자 채팅이 아니라 "이 turn 의 트리거" — turn 경계로 노출
                    # 해 도구가 왜 이때 시작됐는지 맥락을 준다 (UI 는 압축
                    # 구분선 + 펼치면 전문). thinking(왜)은 빈값이라 불가.
                    out.append({
                        "ts": ts, "kind": "turn",
                        "prompt": _hist_fmt(content, _HIST_TEXT_LIMIT),
                    })
    return out


class ActivityHistoryRequest(BaseModel):
    entity_type: str
    entity_id: str
    before_idx: int | None = None  # 이 idx 미만(과거)만. None → 최신부터.
    limit: int | None = None       # 기본 100, 상한 300.


@router.post("/worker.activity_history")
async def worker_activity_history(req: ActivityHistoryRequest, request: Request) -> CapabilityResponse:
    """한 entity 의 durable 과거 AI transcript — Agent SDK 세션 JSONL(NFS) 기반.

    워커 실행중이 아니어도, hub 재시작·세션 교체 후에도 보존된다 (파일 기반).
    cell 스코프·인증은 worker.activity_list 와 동일 console 경로(CellMiddleware
    가 request.state.cell_id 주입). 역방향 페이지네이션: UI 가 위로 스크롤할 때
    before_idx 로 더 과거를 이어 받는다. seq=idx (그 entity 전 세션 통합 정렬
    순번) — UI 는 ts 로 live ring buffer 와 머지·경계 dedup.
    """
    cell_id = getattr(request.state, "cell_id", None)
    if not cell_id:
        return CapabilityResponse(status="error", error_code="cell_id_required",
                                  message="cell_id required")
    entity_type = (req.entity_type or "").strip()
    entity_id = (req.entity_id or "").strip()
    if entity_type not in ("issue", "project", "initiative") or not entity_id:
        return CapabilityResponse(status="error", error_code="invalid_request",
                                  message="entity_type(issue|project|initiative) and entity_id required")
    limit = max(1, min(req.limit or 100, 300))

    # 파일 mtime asc → 라인 순. 세션 여러 개면 시간순 통합. 상한 초과 시 최신 우선.
    dirs = _entity_session_dirs(cell_id, entity_type, entity_id)
    files: list[str] = []
    for d in dirs:
        try:
            files.extend(glob.glob(f"{d}/*.jsonl"))
        except OSError:
            pass
    files.sort(key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0.0))
    events: list[dict] = []
    for fp in files:
        events.extend(_parse_session_events(fp))
        if len(events) > _HIST_MAX_EVENTS:
            events = events[-_HIST_MAX_EVENTS:]
    # 실제 진행 순서로 정렬한다. SDK 세션 JSONL 의 라인 순서는 스트리밍·병렬
    # tool 로 인해 timestamp 와 단조 일치하지 않는다(파일 내 국소 역전 관측).
    # idx 가 시간순이어야 UI 표시·역방향 페이지네이션이 진행 순서를 보존한다.
    # 동일 ts·파싱 불가 시 원래 파일 순서를 tiebreaker 로 (stable).
    events = [{**ev, "_o": i} for i, ev in enumerate(events)]
    events.sort(key=lambda e: (_ts_epoch(e.get("ts")), e["_o"]))
    total = len(events)
    for i, ev in enumerate(events):
        ev["idx"] = i
        ev["seq"] = i
        ev.pop("_o", None)
    end = total if req.before_idx is None else max(0, min(req.before_idx, total))
    start = max(0, end - limit)
    # turn 경계로 스냅: 페이지가 turn 중간에서 시작하면(머리 tool 들이 그
    # turn 헤더 없이 노출 — "맥락 없이 갑자기 Bash") 직전 turn 마커까지 start
    # 를 당겨 모든 로드 페이지가 turn 헤더로 시작하게 한다. 무한 확장 방지로
    # 역방향 스캔은 limit 만큼만(워커는 매 cycle prompt 주입이라 turn 이
    # 촘촘 — 이 한도 내 거의 항상 발견; 없으면 원래 start 유지).
    if start > 0:
        floor = max(0, start - limit)
        s = start
        while s > floor and events[s].get("kind") != "turn":
            s -= 1
        if events[s].get("kind") == "turn":
            start = s
    page = events[start:end]
    return CapabilityResponse(status="ok", data={
        "items": page,
        "total": total,
        "oldest_idx": start,
        "has_more": start > 0,
    })
