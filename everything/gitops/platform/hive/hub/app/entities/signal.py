import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field
from ..storage.idgen import new_entity_id

from capability_framework import CapabilityResponse
from ..config import CellPaths, accessible_cell_ids, get_cell_paths
from ..cursor import offset_page, resolve_offset
from ..helpers import (
    read_jsonl, write_jsonl, append_jsonl, today_path, find_by_id,
    iter_partitions_for_query, entity_lock,
)

SignalType = Literal[
    "capability.insufficient",
    "capability.failed",
    "capability.unauthorized",
    "improvement.harness",
    "opportunity.detected",
    "observation.notable",
    "infra.pod_failed",
]

# 옛 입력 호환용 enum (record 에는 priority(int 1-5) 만 저장).
SignalSeverity = Literal["info", "warn", "error", "critical"]
SignalImpact = Literal["minor", "moderate", "major", "decisive"]


# ── Priority 정규화 (Issues/Projects 와 동일한 1-5 scale) ──
_IMPACT_TO_PRIORITY = {"minor": 2, "moderate": 3, "major": 4, "decisive": 5}
_SEVERITY_TO_PRIORITY = {"info": 2, "warn": 3, "error": 4, "critical": 5}


def _coerce_priority(*, priority: int | None, impact: str | None, severity: str | None) -> int:
    if isinstance(priority, int) and 1 <= priority <= 5:
        return priority
    if impact and impact in _IMPACT_TO_PRIORITY:
        return _IMPACT_TO_PRIORITY[impact]
    if severity and severity in _SEVERITY_TO_PRIORITY:
        return _SEVERITY_TO_PRIORITY[severity]
    return 2  # default Low


def _build_description(*, description: str | None, message: str | None,
                       reason: str | None, raw: dict | None) -> str:
    """description 우선. 옛 입력 (message + raw + reason) 은 markdown 으로 합성."""
    if description:
        return description
    parts: list[str] = []
    primary = message or reason
    if primary:
        parts.append(primary)
    if raw and isinstance(raw, dict) and len(raw) > 0:
        items = "\n".join(f"- **{k}**: {v}" for k, v in raw.items() if v not in (None, ""))
        if items:
            parts.append(items)
    return "\n\n".join(parts)


def _normalize_record(s: dict) -> dict:
    """옛 nested record (origin/subject/detail/payload/source_context/reason/impact/severity)
    → 평탄 필드 (description/priority/issue_id/project_id/session_id) 보장.
    원본 필드는 호환 위해 record 에서 제거하지 않음.
    """
    if "priority" not in s:
        s["priority"] = _coerce_priority(
            priority=None,
            impact=s.get("impact"),
            severity=s.get("severity"),
        )
    subj = s.get("subject") or {}
    sc = s.get("source_context") or {}
    if not s.get("issue_id"):
        s["issue_id"] = subj.get("issue_id") or sc.get("issue_id")
    if not s.get("project_id"):
        s["project_id"] = subj.get("project_id") or sc.get("project_id")
    if not s.get("initiative_id"):
        s["initiative_id"] = subj.get("initiative_id") or sc.get("initiative_id")
    if not s.get("session_id"):
        s["session_id"] = (s.get("origin") or {}).get("session_id")
    if not s.get("description"):
        s["description"] = _build_description(
            description=None,
            message=(s.get("detail") or {}).get("message"),
            reason=s.get("reason"),
            raw=(s.get("detail") or {}).get("raw") or s.get("payload"),
        )
    return s


# ── Schema-driven validator ──────────────────────────────────
# 정본: schemas/signal-types.schema.json. Dockerfile 은 이를 /app/schemas/ 로 복사.

def _load_schema() -> dict | None:
    candidates: list[Path] = []
    if env := os.environ.get("SIGNAL_SCHEMA_PATH"):
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    for depth in range(2, len(here.parents)):
        candidates.append(here.parents[depth] / "schemas" / "signal-types.schema.json")
    for p in candidates:
        try:
            if p.is_file():
                return json.loads(p.read_text())
        except (OSError, ValueError):
            continue
    return None


_SCHEMA = _load_schema()
_VALIDATOR = Draft202012Validator(_SCHEMA) if _SCHEMA else None

router = APIRouter()


# ── Sub-models (옛 입력 호환용 — 새 호출자는 평탄 필드 사용) ──

class SignalOrigin(BaseModel):
    emitter: str | None = None
    hive_id: str | None = None
    session_id: str | None = None
    phase: str | None = None


class SignalSubject(BaseModel):
    issue_id: str | None = None
    project_id: str | None = None
    initiative_id: str | None = None
    capability_id: str | None = None


class SignalDetail(BaseModel):
    message: str = ""
    raw: dict | None = None


# ── Request / Response models ────────────────────────────────

class SignalEmitRequest(BaseModel):
    type: SignalType = Field(
        description='capability.insufficient | capability.failed | capability.unauthorized | improvement.harness | opportunity.detected | observation.notable | infra.pod_failed.',
    )
    title: str | None = None
    # 새 평탄 필드 (선호)
    description: str | None = None
    priority: int | None = Field(
        default=None,
        ge=1, le=5,
        description='1=Backlog, 2=Low(기본), 3=Medium, 4=High, 5=Urgent. impact/severity 와 동시 지정 시 priority 가 우선.',
    )
    issue_id: str | None = None
    project_id: str | None = None
    initiative_id: str | None = None
    session_id: str | None = None
    # 옛 nested 입력 호환 (record 저장 시 평탄 필드로 매핑)
    severity: SignalSeverity | None = Field(
        default=None,
        description='옛 입력. info=2 / warn=3 / error=4 / critical=5 로 priority 매핑.',
    )
    impact: SignalImpact | None = Field(
        default=None,
        description='옛 입력. minor=2 / moderate=3 / major=4 / decisive=5 로 priority 매핑.',
    )
    source_context: dict | None = None
    payload: dict | None = None
    reason: str | None = None
    origin: SignalOrigin | None = None
    subject: SignalSubject | None = None
    detail: SignalDetail | None = None


class SignalListRequest(BaseModel):
    status: str | None = Field(
        default=None,
        description='emitted | consumed | dismissed.',
    )
    statuses: list[str] | None = Field(
        default=None,
        description='다중 상태 필터. status 와 동시 지정 시 status 가 우선.',
    )
    type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 50
    offset: int = 0
    cursor: str | None = Field(
        default=None,
        description='이전 응답의 next_cursor. 제공되면 offset 무시.',
    )
    issue_id: str | None = None
    project_id: str | None = None
    initiative_id: str | None = None
    session_id: str | None = None
    include_deleted: bool = False
    q: str | None = Field(
        default=None,
        description='자유 텍스트 substring 필터 (case-insensitive). title 과 signal_id 양쪽에 match. 빈 문자열·공백은 무필터.',
    )


class SignalUpdateRequest(BaseModel):
    signal_id: str
    status: str = Field(
        description='consumed | dismissed | emitted(Reopen).',
    )
    by: str | None = None
    note: str | None = None
    project_id: str | None = None
    issue_id: str | None = None
    initiative_id: str | None = None


@router.post("/signal.emit")
async def signal_emit(req: SignalEmitRequest, request: Request) -> CapabilityResponse:
    """이벤트를 Signal record 로 기록. 새 호출자는 평탄 필드 사용,
    옛 호출자(agent-loop 의 origin/subject/detail 등) 는 backend 가 자동 매핑.
    """
    if _VALIDATOR is not None:
        body = req.model_dump(exclude_none=True)
        errors = sorted(_VALIDATOR.iter_errors(body), key=lambda e: list(e.path))
        if errors:
            messages = []
            for e in errors[:5]:
                loc = ".".join(str(p) for p in e.path) or "<root>"
                messages.append(f"{loc}: {e.message}")
            return CapabilityResponse(
                status="error",
                error_code="schema_validation_failed",
                message="; ".join(messages),
            )

    subject = req.subject.model_dump(exclude_none=True) if req.subject else {}
    detail = req.detail.model_dump(exclude_none=True) if req.detail else {}
    origin = req.origin.model_dump(exclude_none=True) if req.origin else {}

    issue_id = req.issue_id or subject.get("issue_id")
    project_id = req.project_id or subject.get("project_id")
    initiative_id = req.initiative_id or subject.get("initiative_id")
    session_id = req.session_id or origin.get("session_id")
    priority = _coerce_priority(priority=req.priority, impact=req.impact, severity=req.severity)
    description = _build_description(
        description=req.description,
        message=detail.get("message"),
        reason=req.reason,
        raw=detail.get("raw") or req.payload or req.source_context,
    )

    principal = getattr(request.state, "principal", None)
    by = principal.id if principal else None
    cp = get_cell_paths(request)
    record = emit_signal_to_cell(
        cell_id=cp.cell_id,
        type=req.type,
        title=req.title,
        description=description,
        priority=priority,
        issue_id=issue_id,
        project_id=project_id,
        initiative_id=initiative_id,
        session_id=session_id,
        raw=detail.get("raw") or req.payload,
        by=by,
    )
    return CapabilityResponse(status="ok", data=record)


def emit_signal_to_cell(
    *,
    cell_id: str,
    type: str,
    title: str | None,
    description: str,
    priority: int | None,
    issue_id: str | None = None,
    project_id: str | None = None,
    initiative_id: str | None = None,
    session_id: str | None = None,
    raw: dict | None = None,
    by: str | None = None,
) -> dict:
    """cell scope 로 signal record 를 만들고 저장한다. signal_emit 핸들러와
    bus.publish fan-out 의 공유 helper. fan-out 시 cell_id 만 override 하면
    동일한 payload 를 매칭 cell 마다 적재 가능.
    """
    cp = CellPaths(cell_id)
    now = datetime.now(timezone.utc).isoformat()
    signal_id, seq = new_entity_id(cp.cell_id, "signal")
    record = {
        "signal_id": signal_id,
        "seq": seq,
        "type": type,
        "ts_emitted": now,
        "status": "emitted",
        "history": [{"ts": now, "status": "emitted", "by": by, "note": None}],
        "title": title,
        "description": description,
        "priority": priority,
        "issue_id": issue_id,
        "project_id": project_id,
        "initiative_id": initiative_id,
        "session_id": session_id,
        "cell_id": cp.cell_id,
        # signal-types.schema 가 detail.raw 를 required 로 강제하고 consumer
        # (UI, dedupe, 분석) 가 structured evidence 를 활용할 수 있도록 raw 를
        # 보존한다. description 텍스트 합성과는 별개 채널.
        "raw": raw,
    }
    append_jsonl(today_path(cp.signal_dir), record)
    from .. import wake_bus
    wake_bus.notify(f"signals:{cp.cell_id}")
    return record


def _filter_sort_paginate(signals, req):
    """signal.list / signal.list_all 공유 — read 이후 동일 정규화·필터·정렬·페이지네이션.

    두 핸들러의 유일한 차이는 소스(단일 cell vs 전 cell 머지)뿐이라, 그 뒤 로직을 여기로
    모아 drift(필터 누락 비대칭 등)를 막는다. owner/me-alias 가 없어 request 불필요.
    반환 (page, total, next_cursor).
    """
    if not req.include_deleted:
        signals = [s for s in signals if not s.get("deleted")]
    signals = [_normalize_record(s) for s in signals]
    if req.status:
        signals = [s for s in signals if s["status"] == req.status]
    if req.statuses:
        allowed = set(req.statuses)
        signals = [s for s in signals if s["status"] in allowed]
    if req.type:
        signals = [s for s in signals if s["type"] == req.type]
    if req.issue_id:
        signals = [s for s in signals if s.get("issue_id") == req.issue_id]
    if req.project_id:
        signals = [s for s in signals if s.get("project_id") == req.project_id]
    if req.initiative_id:
        signals = [s for s in signals if s.get("initiative_id") == req.initiative_id]
    if req.session_id:
        signals = [s for s in signals if s.get("session_id") == req.session_id]
    if req.q:
        needle = req.q.strip().lower()
        if needle:
            signals = [
                s for s in signals
                if needle in (s.get("title") or "").lower()
                or needle in (s.get("signal_id") or "").lower()
            ]
    # ts_emitted 내림차순 정렬 후 페이지네이션. cursor/offset 미지정 = 첫 페이지(0).
    # 무한스크롤 caller 가 first page 부터 next_cursor 를 받을 수 있도록 항상 페이지네이션.
    signals.sort(key=lambda s: s.get("ts_emitted") or "", reverse=True)
    total = len(signals)
    offset = resolve_offset(req.cursor, req.offset)
    page, next_cursor = offset_page(signals, offset=offset, limit=req.limit)
    return page, total, next_cursor


@router.post("/signal.list")
def signal_list(req: SignalListRequest, request: Request) -> CapabilityResponse:
    """Signal 목록 조회. 옛 nested record 는 read 시 평탄 필드로 정규화 후 반환. cursor 또는 offset 페이지네이션."""
    cp = get_cell_paths(request)
    full_scan = bool(req.issue_id or req.project_id or req.initiative_id or req.session_id or req.status or req.statuses or req.type)
    paths = iter_partitions_for_query(
        cp.signal_dir, req.date_from, req.date_to, entity_scoped=full_scan
    )
    signals = []
    for p in paths:
        signals.extend(read_jsonl(p))
    page, total, next_cursor = _filter_sort_paginate(signals, req)
    return CapabilityResponse(status="ok", data={
        "signals": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/signal.list_all")
def signal_list_all(req: SignalListRequest, request: Request) -> CapabilityResponse:
    """User-scoped aggregate. 호출자가 접근 가능한 모든 cell 의 signal 을 머지.

    필터·정규화·페이지네이션 의미론은 signal.list 와 동일. signal 레코드는 cell_id
    필드를 이미 포함하므로 UI 는 응답 항목의 cell_id 로 cell 뱃지·라우팅 결정.
    """
    cell_ids = accessible_cell_ids(request)
    full_scan = bool(req.issue_id or req.project_id or req.initiative_id or req.session_id or req.status or req.statuses or req.type)
    signals = []
    for cid in cell_ids:
        cp = CellPaths(cid)
        paths = iter_partitions_for_query(
            cp.signal_dir, req.date_from, req.date_to, entity_scoped=full_scan
        )
        for p in paths:
            signals.extend(read_jsonl(p))
    page, total, next_cursor = _filter_sort_paginate(signals, req)
    return CapabilityResponse(status="ok", data={
        "signals": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


class SignalGetRequest(BaseModel):
    signal_id: str


@router.post("/signal.get")
def signal_get(req: SignalGetRequest, request: Request) -> CapabilityResponse:
    """단일 Signal 상세 조회."""
    cp = get_cell_paths(request)
    _, _, found = find_by_id(cp.signal_dir, "signal_id", req.signal_id)
    if not found:
        return CapabilityResponse(status="error", error_code="not_found", message=f"signal {req.signal_id} not found")
    return CapabilityResponse(status="ok", data=_normalize_record(found))


@router.post("/signal.update_status")
async def signal_update_status(req: SignalUpdateRequest, request: Request) -> CapabilityResponse:
    """Signal 상태를 consumed, dismissed, emitted(Reopen) 로 전환."""
    if req.status not in ("consumed", "dismissed", "emitted"):
        return CapabilityResponse(status="error", error_code="invalid_status", message="status must be consumed, dismissed, or emitted")

    cp = get_cell_paths(request)
    with entity_lock(cp.signal_dir):
        path, entries, found = find_by_id(cp.signal_dir, "signal_id", req.signal_id)
        if not found:
            return CapabilityResponse(status="error", error_code="not_found", message=f"signal {req.signal_id} not found")
        if found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="entity_deleted",
                message=f"cannot update deleted signal {req.signal_id}. restore it first.",
            )

        now = datetime.now(timezone.utc).isoformat()
        found["status"] = req.status
        if req.project_id:
            found["project_id"] = req.project_id
        if req.issue_id:
            found["issue_id"] = req.issue_id
        if req.initiative_id:
            found["initiative_id"] = req.initiative_id
        principal = getattr(request.state, "principal", None)
        by = principal.id if principal else req.by
        history = found.get("history") or []
        history.append({"ts": now, "status": req.status, "by": by, "note": req.note})
        found["history"] = history
        write_jsonl(path, entries)
    return CapabilityResponse(status="ok", data=_normalize_record(found))


class SignalDeleteRequest(BaseModel):
    signal_id: str


@router.post("/signal.delete")
async def signal_delete(req: SignalDeleteRequest, request: Request) -> CapabilityResponse:
    """Signal 소프트 삭제."""
    cp = get_cell_paths(request)
    with entity_lock(cp.signal_dir):
        path, entries, found = find_by_id(cp.signal_dir, "signal_id", req.signal_id)
        if not found:
            return CapabilityResponse(status="error", error_code="not_found", message=f"signal {req.signal_id} not found")
        if found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="already_deleted",
                message=f"signal {req.signal_id} is already deleted",
            )
        now = datetime.now(timezone.utc).isoformat()
        found["deleted"] = True
        found["deleted_at"] = now
        history = found.get("history") or []
        history.append({"ts": now, "status": "deleted", "by": None, "note": None})
        found["history"] = history
        write_jsonl(path, entries)
    return CapabilityResponse(status="ok", data=_normalize_record(found))


class SignalRestoreRequest(BaseModel):
    signal_id: str


@router.post("/signal.restore")
async def signal_restore(req: SignalRestoreRequest, request: Request) -> CapabilityResponse:
    """삭제된 Signal 복원."""
    cp = get_cell_paths(request)
    with entity_lock(cp.signal_dir):
        path, entries, found = find_by_id(cp.signal_dir, "signal_id", req.signal_id)
        if not found:
            return CapabilityResponse(status="error", error_code="not_found", message=f"signal {req.signal_id} not found")
        if not found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="not_deleted",
                message=f"signal {req.signal_id} is not deleted",
            )
        now = datetime.now(timezone.utc).isoformat()
        found.pop("deleted", None)
        found.pop("deleted_at", None)
        history = found.get("history") or []
        history.append({"ts": now, "status": "restored", "by": None, "note": None})
        found["history"] = history
        write_jsonl(path, entries)
    return CapabilityResponse(status="ok", data=_normalize_record(found))
