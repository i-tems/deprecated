"""Label entity — Linear style label (cell-scoped, flat list).

Project/Issue 에 다대다로 붙는 분류 태그. cell 별로 마스터를 관리하고 (cell_id 가 다르면
같은 이름의 label 이 존재 가능), project/issue record 는 ``labels: [label_id, ...]`` 만 들고 있다.

Linear MCP 와 capability 분리 방식 동일:
- label.create / label.list / label.get / label.update / label.delete (마스터 CRUD)
- 적용은 project.create/update, issue.create/update 의 ``labels`` 인라인

PR2 시점에 추가: ``validate_label_ids`` (project/issue 측 검증용), label.delete 시
project/issue 의 labels list 에서 cascade 제거.
"""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel
from ..storage.idgen import new_entity_id

from capability_framework import CapabilityResponse
from ..config import get_cell_paths
from . import cas_entity
from ..helpers import (
    append_jsonl, emit_event, entity_lock, find_entity, read_entity_file,
)


router = APIRouter()


# Linear 의 기본 label 색상 팔레트 (https://linear.app 의 default colors).
# 미지정 시 hash 기반으로 결정적 선택 — 같은 이름이면 항상 같은 색.
DEFAULT_PALETTE = [
    "#EB5757",  # red
    "#F2994A",  # orange
    "#F2C94C",  # yellow
    "#4CB782",  # green
    "#26B5CE",  # teal
    "#5E6AD2",  # indigo
    "#BB87FC",  # purple
    "#F699B6",  # pink
    "#95A2B3",  # gray
]

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _pick_default_color(name: str) -> str:
    """이름 hash 기반 deterministic 선택 — UI 가 같은 label 을 항상 같은 색으로 본다."""
    if not name:
        return DEFAULT_PALETTE[0]
    idx = sum(ord(c) for c in name) % len(DEFAULT_PALETTE)
    return DEFAULT_PALETTE[idx]


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _validate_color(color: str | None) -> str | None:
    """hex (#RRGGBB) 만 허용. None 이면 그대로 통과 (caller 가 default 결정)."""
    if color is None:
        return None
    color = color.strip()
    if not _HEX_RE.match(color):
        return None
    return color.upper()


def _name_conflict(entries: list[dict], name: str, *, exclude_id: str | None = None) -> bool:
    """cell 내 active label 중 같은 이름이 있는지. case-insensitive."""
    key = name.lower()
    for e in entries:
        if e.get("deleted"):
            continue
        if exclude_id and e.get("label_id") == exclude_id:
            continue
        if (e.get("name") or "").lower() == key:
            return True
    return False


def normalize_label_ids(cp, label_ids: list[str] | None) -> tuple[list[str] | None, CapabilityResponse | None]:
    """project/issue 가 받은 labels 를 검증 + dedupe.

    Returns (cleaned_ids, error_response). error 가 None 이면 cleaned 사용.
    - 존재하지 않거나 deleted 인 label_id 는 ``invalid_label`` 에러.
    - 중복 제거 + 순서 유지.
    - None 입력은 None 반환 (caller 가 "필드 미지정" 으로 해석).
    """
    if label_ids is None:
        return None, None
    seen: set[str] = set()
    cleaned: list[str] = []
    for lid in label_ids:
        if not isinstance(lid, str) or not lid:
            continue
        if lid in seen:
            continue
        seen.add(lid)
        cleaned.append(lid)
    if not cleaned:
        return [], None
    entries = read_entity_file(cp.label_file)
    valid: set[str] = {e["label_id"] for e in entries if not e.get("deleted")}
    missing = [lid for lid in cleaned if lid not in valid]
    if missing:
        return None, CapabilityResponse(
            status="error", error_code="invalid_label",
            message=f"unknown or deleted label_id(s): {missing}",
        )
    return cleaned, None


# ── Requests ──

class LabelCreateRequest(BaseModel):
    name: str
    color: str | None = None  # hex "#RRGGBB". 없으면 팔레트에서 자동.
    description: str | None = None


class LabelListRequest(BaseModel):
    include_deleted: bool = False


class LabelGetRequest(BaseModel):
    label_id: str


class LabelUpdateRequest(BaseModel):
    label_id: str
    name: str | None = None
    color: str | None = None
    description: str | None = None


class LabelDeleteRequest(BaseModel):
    label_id: str


class LabelRestoreRequest(BaseModel):
    label_id: str


# ── Capabilities ──

@router.post("/label.create")
async def label_create(req: LabelCreateRequest, request: Request) -> CapabilityResponse:
    """Label 생성. name 은 cell 내 unique (case-insensitive). color 미지정 시 팔레트 자동 선택."""
    cp = get_cell_paths(request)
    name = _normalize_name(req.name)
    if not name:
        return CapabilityResponse(status="error", error_code="name_required", message="label.name is required")

    with entity_lock(cp.label_file):
        entries = read_entity_file(cp.label_file)
        if _name_conflict(entries, name):
            return CapabilityResponse(
                status="error", error_code="name_conflict",
                message=f"label with name {name!r} already exists in this cell",
            )

        color = _validate_color(req.color) or _pick_default_color(name)
        now = datetime.now(timezone.utc).isoformat()
        label_id, _seq = new_entity_id(cp.cell_id, "label")
        record = {
            "label_id": label_id,
            "cell_id": cp.cell_id,
            "name": name,
            "color": color,
            "description": req.description or None,
            "created_at": now,
            "updated_at": now,
        }
        append_jsonl(cp.label_file, record)

    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event("label", record["label_id"], "created",
               {"name": name, "color": color},
               event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data=record)


@router.post("/label.list")
def label_list(req: LabelListRequest, request: Request) -> CapabilityResponse:
    """cell 내 label 목록. 기본은 active 만, include_deleted=True 면 전부."""
    cp = get_cell_paths(request)
    entries = read_entity_file(cp.label_file)
    if not req.include_deleted:
        entries = [e for e in entries if not e.get("deleted")]
    entries.sort(key=lambda e: (e.get("name") or "").lower())
    return CapabilityResponse(status="ok", data={"labels": entries, "count": len(entries)})


@router.post("/label.get")
def label_get(req: LabelGetRequest, request: Request) -> CapabilityResponse:
    cp = get_cell_paths(request)
    _, found = find_entity(cp.label_file, "label_id", req.label_id)
    if not found:
        return CapabilityResponse(status="error", error_code="not_found", message=f"label {req.label_id} not found")
    return CapabilityResponse(status="ok", data=found)


@router.post("/label.update")
async def label_update(req: LabelUpdateRequest, request: Request) -> CapabilityResponse:
    """Label 필드 수정. name 변경 시 cell 내 unique 재검증."""
    cp = get_cell_paths(request)
    # name unique 검사는 셀 전체 label 을 봐야 하므로 cas 밖에서 pre-check (cross-pod 동시
    # 동일-이름 생성 race 는 사람이 드물게 만드는 label 특성상 수용 — 중복명은 복구가능·비손실).
    # 실제 쓰기는 per-entity CAS (labels 테이블 lost-update 방지, INFRA-ISSUE-284).
    with entity_lock(cp.label_file):
        entries = read_entity_file(cp.label_file)
        target = next((e for e in entries if e.get("label_id") == req.label_id), None)
        if not target:
            return CapabilityResponse(status="error", error_code="not_found", message=f"label {req.label_id} not found")
        if target.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="entity_deleted",
                message=f"cannot update deleted label {req.label_id}. restore it first.",
            )
        new_name = None
        if req.name is not None:
            new_name = _normalize_name(req.name)
            if not new_name:
                return CapabilityResponse(status="error", error_code="name_required", message="label.name cannot be empty")
            if _name_conflict(entries, new_name, exclude_id=req.label_id):
                return CapabilityResponse(
                    status="error", error_code="name_conflict",
                    message=f"label with name {new_name!r} already exists in this cell",
                )
        new_color = None
        if req.color is not None:
            new_color = _validate_color(req.color)
            if not new_color:
                return CapabilityResponse(
                    status="error", error_code="invalid_color",
                    message=f"color must be hex '#RRGGBB', got {req.color!r}",
                )

        def _mutate(found):
            if new_name is not None:
                found["name"] = new_name
            if new_color is not None:
                found["color"] = new_color
            if req.description is not None:
                found["description"] = req.description or None
            found["updated_at"] = datetime.now(timezone.utc).isoformat()

        res = cas_entity(cp, "label", req.label_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"label {req.label_id} not found")
    found = res
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event("label", req.label_id, "updated", {},
               event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data=found)


def _cascade_remove_from_entities(cp, entity_file, id_field: str, label_id: str,
                                  *, sid: str | None, principal,
                                  entity_type: str) -> list[str]:
    """project/issue 의 labels list 에서 label_id 를 제거. 영향받은 entity_id 목록 반환."""
    affected: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    def _remove(found):
        found["labels"] = [l for l in (found.get("labels") or []) if l != label_id]
        found["updated_at"] = now

    # whole-cell 재기록 대신 영향받는 entity 만 per-entity CAS — hot 테이블(issues/projects)
    # cross-pod lost-update 방지 (INFRA-ISSUE-284). entity_lock 으로 within-pod 직렬화 유지.
    with entity_lock(entity_file):
        for e in read_entity_file(entity_file):
            if label_id in (e.get("labels") or []):
                cas_entity(cp, entity_type, e[id_field], _remove)
                affected.append(e[id_field])
    for entity_id in affected:
        emit_event(entity_type, entity_id, "field_change",
                   {"field": "labels", "removed": label_id},
                   event_dir=cp.event_dir, session_id=sid, principal=principal)
    return affected


@router.post("/label.delete")
async def label_delete(req: LabelDeleteRequest, request: Request) -> CapabilityResponse:
    """Label soft delete + cascade: 같은 cell 의 project/issue labels 에서 제거."""
    cp = get_cell_paths(request)

    def _mutate(found):
        if found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="already_deleted",
                message=f"label {req.label_id} is already deleted",
            )
        now = datetime.now(timezone.utc).isoformat()
        found["deleted"] = True
        found["deleted_at"] = now
        found["updated_at"] = now

    with entity_lock(cp.label_file):
        res = cas_entity(cp, "label", req.label_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"label {req.label_id} not found")
    if isinstance(res, CapabilityResponse):
        return res
    found = res
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    affected_goals = _cascade_remove_from_entities(
        cp, cp.project_file, "project_id", req.label_id,
        sid=sid, principal=principal, entity_type="project",
    )
    affected_tasks = _cascade_remove_from_entities(
        cp, cp.issue_file, "issue_id", req.label_id,
        sid=sid, principal=principal, entity_type="issue",
    )
    emit_event("label", req.label_id, "deleted",
               {"cascade": {"projects": len(affected_goals), "issues": len(affected_tasks)}},
               event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data={
        **found,
        "cascade": {"projects": affected_goals, "issues": affected_tasks},
    })


@router.post("/label.restore")
async def label_restore(req: LabelRestoreRequest, request: Request) -> CapabilityResponse:
    """삭제된 label 복원. 같은 이름의 active label 이 생긴 경우 name_conflict 거부."""
    cp = get_cell_paths(request)
    with entity_lock(cp.label_file):
        entries, target = find_entity(cp.label_file, "label_id", req.label_id, include_deleted=True)
        if not target:
            return CapabilityResponse(status="error", error_code="not_found", message=f"label {req.label_id} not found")
        if not target.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="not_deleted",
                message=f"label {req.label_id} is not deleted",
            )
        if _name_conflict(entries, target.get("name") or "", exclude_id=req.label_id):
            return CapabilityResponse(
                status="error", error_code="name_conflict",
                message=f"another active label with name {target.get('name')!r} exists. rename it first.",
            )

        def _mutate(found):
            found.pop("deleted", None)
            found.pop("deleted_at", None)
            found["updated_at"] = datetime.now(timezone.utc).isoformat()

        res = cas_entity(cp, "label", req.label_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"label {req.label_id} not found")
    found = res
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event("label", req.label_id, "restored", {},
               event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data=found)
