"""Initiative entity — strategic outcome anchor. Project 과 동일한 5-status container 모델.

Spec: ~/hive/specs/model/initiative_model.md
- status: backlog / active / waiting / done / archive (Project 과 통일된 container 모델).
  backlog=착수 전(미픽업, 구 planned), active=오케스트레이션(워커 픽업), waiting=사람 대기로
  parked(self-action 미픽업, pending 댓글 reply 만 — 워커가 needs_human/방향결정/완료추천에
  막혔을 때 active→waiting 으로 재invoke 루프 차단), done=완료(terminal, 사람 확정, 자동완료
  없음, 구 completed), archive=폐기(terminal, 구 archived 플래그를 status 로 흡수).
- gates.completion(auto/require/skip) 직교 축 — Project 과 동일 container 종결 전이 가드.
  '잘 가나/위험/pivot' 평가는 별도 필드가 아니라 Initiative 타임라인(event.add) narrative 로 남긴다.
- sub-initiative ≤5 depth, multi-parent projects 허용, manual curation
- 1 cell : N initiative. cross-cell 참조 없음.
- **worker entity (active 한정)** — status=active 동안 agent-loop 워커가 자율 오케스트레이션
  (자식 Project 생성·진행관찰·완료 판단). set_session·hold 보유. force_update·add_pr 은
  불필요(가드 우회 대상 없음·PR 은 자식 Project 보유)라 두지 않는다.
  정본: ~/hive/specs/model/initiative_model.md §2.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse

from ..config import CellPaths, VALID_CONTAINER_STATUSES, accessible_cell_ids, get_cell_paths
from ..cursor import offset_page, resolve_offset
from ..helpers import (
    append_jsonl, emit_event, entity_lock, find_entity,
    normalize_resources, read_entity_file, resolve_me_alias,
)
from ..models import Gates, Priority, Resource, compute_priority_score
from ..storage.idgen import new_entity_id
from . import container_transition_denied, cas_entity
from . import view
from .event import CommentSubtype


VALID_INITIATIVE_STATUSES = VALID_CONTAINER_STATUSES  # {backlog, active, waiting, done, archive}
DEFAULT_INITIATIVE_STATUS = "backlog"
DEFAULT_INITIATIVE_PRIORITY = {"value": 2}  # Low — Project/Issue 와 동일 기본값

MAX_INITIATIVE_NESTING_DEPTH = 5  # Linear 정본 — sub-initiative ≤5 depth


router = APIRouter()


class InitiativeCreateRequest(BaseModel):
    name: str = Field(description='인간이 부르는 이름. Linear 정본 — name 만 필수.')
    description: str | None = Field(default=None, description='Rich text markdown. 자유 형식.')
    status: str | None = Field(
        default=None,
        description='backlog (기본) | active | done | archive. 명시 안 하면 backlog.',
    )
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto(기본) | require. require 면 active→done 직접 전이 금지.',
    )
    owner: str | None = Field(
        default=None,
        description='Owner email. 미지정 시 creator (요청자 email).',
    )
    color: str | None = Field(default=None, description='UI 시각화 — hex 또는 palette name.')
    icon: str | None = Field(default=None, description='UI 시각화 — emoji 또는 icon name.')
    parent_initiative_id: str | None = Field(
        default=None,
        description='Sub-initiative parent. ≤5 depth 강제. 같은 cell 만 (cross-cell 거부).',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. 1=Backlog, 2=Low(기본), 3=Medium, 4=High, 5=Urgent.',
    )
    resources: list[Resource] | None = Field(
        default=None,
        description='외부 리소스 (repo·doc·api·url). Project/Issue 의 resources 와 같은 모델.',
    )


class InitiativeUpdateRequest(BaseModel):
    initiative_id: str
    name: str | None = None
    status: str | None = Field(
        default=None,
        description='backlog | active | waiting | done | archive. 역전이 허용 (실수 정정·전략 재평가). active→waiting(사람 대기 parked), waiting→active/done/archive.',
    )
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto | require.',
    )
    description: str | None = None
    owner: str | None = None
    color: str | None = None
    icon: str | None = None
    parent_initiative_id: str | None = Field(
        default=None,
        description='Sub-initiative parent 재배치. ≤5 depth.',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. None=유지. 비우려면 clear_priority=true.',
    )
    clear_priority: bool = Field(default=False)
    resources: list[Resource] | None = Field(
        default=None,
        description='전체 교체. None=유지, [] 로 비우기 가능.',
    )
    hold: bool | None = Field(
        default=None,
        description='True 면 agent-loop 가 이 initiative 를 자동 픽업하지 않는다 (수동 steering 보호). '
                    'None=유지. status 와 직교 — 해제 시 active 그대로 워커 재개. 자식 Project 엔 cascade 안 됨.',
    )
    comment: str | None = Field(
        default=None,
        description='AI status 전이 시 필수.',
    )
    comment_subtype: CommentSubtype = Field(
        default="transition",
        description='discussion=일반토론 | progress=같은상태내진척 | transition=상태전이사유(기본) | handoff=핸드오프 | halt=실패중단.',
    )
    comment_payload: dict = Field(
        default={},
        description='subtype 별 권장 structured 필드. handoff: {pr_url, summary, options?}, halt: {reason, recovery_options, options?}. options 는 ActivityFeed 인라인 원클릭 버튼 (handoff_patterns 정본). 비어 있으면 본문만 노출.',
    )


class InitiativeGetRequest(BaseModel):
    initiative_id: str


class InitiativeListRequest(BaseModel):
    status: str | None = Field(
        default=None,
        description='단일 상태 필터. backlog | active | waiting | done | archive.',
    )
    hold: bool | None = Field(
        default=None,
        description='True 면 hold=true 만, False 면 hold=false 만. 생략 시 hold 무관. status 필터와 직교(AND).',
    )
    parent_initiative_id: str | None = Field(
        default="__all__",
        description='"__all__"=전부 / None=root only / 특정 id=그 자식만.',
    )
    limit: int = 50
    offset: int = 0
    cursor: str | None = None
    include_archived: bool = Field(
        default=True,
        description='하위호환 no-op. archive 는 이제 일반 terminal status (done 처럼 정상 노출). '
                    '특정 status 만 보려면 status 필터를 쓴다. 과거 archived 플래그는 폐기됨.',
    )
    q: str | None = Field(
        default=None,
        description='자유 텍스트 substring 필터 (case-insensitive). name 과 initiative_id 양쪽에 match. 빈 문자열·공백은 무필터.',
    )


class InitiativeDeleteRequest(BaseModel):
    initiative_id: str


class InitiativeArchiveRequest(BaseModel):
    initiative_id: str


class InitiativeRestoreRequest(BaseModel):
    initiative_id: str


class InitiativeSaveRequest(BaseModel):
    """Linear save_initiative 패턴 — initiative_id 유무로 create/update 디스패치."""
    initiative_id: str | None = Field(
        default=None,
        description='제공 시 update, 없으면 create.',
    )
    name: str | None = Field(default=None, description='create 시 필수.')
    description: str | None = None
    status: str | None = None
    gates: Gates | None = None
    owner: str | None = None
    color: str | None = None
    icon: str | None = None
    parent_initiative_id: str | None = None
    priority: Priority | None = None
    clear_priority: bool = Field(default=False, description='update 전용.')
    resources: list[Resource] | None = None


def _validate_nesting_depth(cp, parent_id: str | None) -> CapabilityResponse | None:
    """Parent 체인 따라 root 까지 depth 계산. 5 초과면 거부, cycle 검출."""
    if not parent_id:
        return None
    depth = 1
    current = parent_id
    seen: set[str] = set()
    while current and depth <= MAX_INITIATIVE_NESTING_DEPTH:
        if current in seen:
            return CapabilityResponse(
                status="error", error_code="cycle_detected",
                message=f"initiative cycle: {current}",
            )
        seen.add(current)
        _, found = find_entity(cp.initiative_file, "initiative_id", current)
        if not found:
            return CapabilityResponse(
                status="error", error_code="parent_not_found",
                message=f"parent initiative {current} not found in cell {cp.cell_id}",
            )
        parent_of_current = found.get("parent_initiative_id")
        if not parent_of_current:
            return None  # parent 가 root 라 깊이 OK
        depth += 1
        current = parent_of_current
    if depth > MAX_INITIATIVE_NESTING_DEPTH:
        return CapabilityResponse(
            status="error", error_code="nesting_too_deep",
            message=f"sub-initiative nesting exceeds {MAX_INITIATIVE_NESTING_DEPTH} (Linear 정본 한도)",
        )
    return None


@router.post("/initiative.create")
async def initiative_create(req: InitiativeCreateRequest, request: Request) -> CapabilityResponse:
    """Initiative 생성. status 미지정 시 'backlog' (container 기본값)."""
    cp = get_cell_paths(request)
    initial_status = req.status or DEFAULT_INITIATIVE_STATUS
    if initial_status not in VALID_INITIATIVE_STATUSES:
        return CapabilityResponse(
            status="error", error_code="invalid_status",
            message=f"invalid status: {initial_status!r}. valid: {sorted(VALID_INITIATIVE_STATUSES)}",
        )
    depth_err = _validate_nesting_depth(cp, req.parent_initiative_id)
    if depth_err:
        return depth_err
    owner = resolve_me_alias(req.owner, request)
    if not owner and req.parent_initiative_id:
        _, parent = find_entity(cp.initiative_file, "initiative_id", req.parent_initiative_id)
        if parent and parent.get("owner"):
            owner = parent["owner"]
    if not owner:
        owner = getattr(request.state, "user_email", None)
    if not owner:
        return CapabilityResponse(
            status="error", error_code="owner_required",
            message="owner required: set explicitly, login via console, or ensure parent initiative has owner",
        )
    now = datetime.now(timezone.utc).isoformat()
    initiative_id, seq = new_entity_id(cp.cell_id, "initiative")
    priority_dict = req.priority.model_dump() if req.priority else DEFAULT_INITIATIVE_PRIORITY
    record = {
        "initiative_id": initiative_id,
        "seq": seq,
        "cell_id": cp.cell_id,
        "name": req.name,
        "status": initial_status,
        "description": req.description,
        "owner": owner,
        "color": req.color,
        "icon": req.icon,
        "parent_initiative_id": req.parent_initiative_id,
        "gates": req.gates.model_dump() if req.gates else None,
        "priority": priority_dict,
        "priority_score": compute_priority_score(priority_dict),
        "resources": normalize_resources([r.model_dump() for r in req.resources]) if req.resources else [],
        "created_at": now,
        "updated_at": now,
    }
    append_jsonl(cp.initiative_file, record)
    return CapabilityResponse(status="ok", data=record)


@router.post("/initiative.update")
async def initiative_update(req: InitiativeUpdateRequest, request: Request) -> CapabilityResponse:
    """Initiative 부분 갱신. status 역전이 허용 (Linear 정합 — 실수 정정용).

    자동 전이 없음. 모든 자식 Project 이 done 되어도 Initiative status 자동 변경 안 함.
    """
    cp = get_cell_paths(request)
    if req.status is not None and req.status not in VALID_INITIATIVE_STATUSES:
        return CapabilityResponse(
            status="error", error_code="invalid_status",
            message=f"invalid status: {req.status!r}. valid: {sorted(VALID_INITIATIVE_STATUSES)}",
        )
    # field_change old→new 로 수정 이력을 보존할 필드 (status=status_change, hold=별도 발행).
    # INFRA-ISSUE-304 — issue/project 의 _TRACKED_FIELDS 에 대응하는 initiative 판.
    tracked = ("name", "description", "owner", "priority", "resources", "gates",
               "parent_initiative_id", "color", "icon")
    box: dict = {}

    def _mutate(found):
        old_status = found.get("status")
        box["old_status"] = old_status
        box["old_hold"] = bool(found.get("hold"))
        box["old_vals"] = {f: found.get(f) for f in tracked}
        # container 종결 전이 가드 (Project 과 동일): gates.completion=require 면
        # active→done 직접 금지. req.gates 우선, 없으면 entity 의 기존 gates.
        if req.status is not None and req.status != old_status:
            completion = "auto"
            if req.gates is not None:
                completion = req.gates.completion
            elif found.get("gates"):
                completion = found["gates"].get("completion", "auto")
            denied = container_transition_denied(old_status, req.status, completion)
            if denied:
                return CapabilityResponse(status="error", error_code="transition_denied", message=denied)
        if req.parent_initiative_id is not None and req.parent_initiative_id != found.get("parent_initiative_id"):
            new_parent = req.parent_initiative_id or None  # 빈 string → None (root)
            if new_parent == req.initiative_id:
                return CapabilityResponse(
                    status="error", error_code="self_parent",
                    message="initiative cannot be its own parent",
                )
            if new_parent:
                depth_err = _validate_nesting_depth(cp, new_parent)
                if depth_err:
                    return depth_err
            found["parent_initiative_id"] = new_parent
        if req.name is not None:
            found["name"] = req.name
        if req.status is not None:
            found["status"] = req.status
        if req.gates is not None:
            found["gates"] = req.gates.model_dump()
        if req.description is not None:
            found["description"] = req.description
        if req.owner is not None:
            found["owner"] = req.owner
        if req.color is not None:
            found["color"] = req.color
        if req.icon is not None:
            found["icon"] = req.icon
        if req.resources is not None:
            found["resources"] = normalize_resources([r.model_dump() for r in req.resources])
        if req.priority is not None:
            p = req.priority.model_dump()
            found["priority"] = p
            found["priority_score"] = compute_priority_score(p)
        elif req.clear_priority:
            found["priority"] = None
            found["priority_score"] = 0
        if req.hold is not None:
            found["hold"] = bool(req.hold)
        found["updated_at"] = datetime.now(timezone.utc).isoformat()

    with entity_lock(cp.initiative_file):
        res = cas_entity(cp, "initiative", req.initiative_id, _mutate)
    if res is None:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"initiative {req.initiative_id} not found",
        )
    if isinstance(res, CapabilityResponse):
        return res
    found = res
    old_status = box["old_status"]
    old_hold = box["old_hold"]

    # 워커 루프 신호: status 전이는 cell wake (agent-loop 픽업 — 예: backlog→active 런칭),
    # hold 해제·변경은 bare initiative_id 키 wake (parked 워커 재개). emit_event 가
    # entity_id 키를 항상 notify 하고 cascade_to 를 추가 notify (events.py).
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    new_status = found.get("status")
    if new_status != old_status:
        # status 전이 사유 코멘트 — Project/Issue 와 동일 계약 (apply_entity_fields_and_persist
        # §comment). 사람이 활동 피드에서 park/handoff/done 의 이유를 읽는다. comment 먼저, 그 다음
        # status_change (공유 헬퍼 순서와 동일).
        if (req.comment or "").strip():
            comment_data: dict = {"text": req.comment.strip(), "subtype": req.comment_subtype}
            if req.comment_payload:
                comment_data["payload"] = req.comment_payload
            emit_event(
                "initiative", req.initiative_id, "comment",
                comment_data, event_dir=cp.event_dir, session_id=sid, principal=principal,
            )
        emit_event(
            "initiative", req.initiative_id, "status_change",
            {"from": old_status, "to": new_status},
            event_dir=cp.event_dir, session_id=sid, principal=principal,
            cascade_to=[f"cell:{cp.cell_id}"],
        )
    # field_change old→new — 수정 이력 자기완결 보존 (INFRA-ISSUE-304). 워커 per-turn
    # 컨텍스트엔 안 실리고 event.list 로만 조회 — description 덮어쓰기 전 백업 코멘트를 대체.
    old_vals = box["old_vals"]
    for _f in tracked:
        if old_vals[_f] != found.get(_f):
            emit_event(
                "initiative", req.initiative_id, "field_change",
                {"field": _f, "old": old_vals[_f], "new": found.get(_f)},
                event_dir=cp.event_dir, session_id=sid, principal=principal,
            )
    if bool(found.get("hold")) != old_hold:
        emit_event(
            "initiative", req.initiative_id, "field_change",
            {"field": "hold", "old": old_hold, "new": bool(found.get("hold"))},
            event_dir=cp.event_dir, session_id=sid, principal=principal,
        )

    return CapabilityResponse(status="ok", data=found)


@router.post("/initiative.get")
def initiative_get(req: InitiativeGetRequest, request: Request) -> CapabilityResponse:
    """단일 Initiative 상세 조회."""
    cp = get_cell_paths(request)
    _, found = find_entity(cp.initiative_file, "initiative_id", req.initiative_id)
    if not found:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"initiative {req.initiative_id} not found",
        )
    return CapabilityResponse(status="ok", data=found)


def _invalid_status(req) -> CapabilityResponse | None:
    """status 유효성 가드 — 불가면 error 응답, 아니면 None (list / list_all 공유)."""
    if req.status and req.status not in VALID_INITIATIVE_STATUSES:
        return CapabilityResponse(
            status="error", error_code="invalid_status",
            message=f"invalid status: {req.status!r}. valid: {sorted(VALID_INITIATIVE_STATUSES)}",
        )
    return None


def _filter_sort_paginate(initiatives, req):
    """initiative.list / initiative.list_all 공유 — 동일 필터·정렬·페이지네이션.

    두 핸들러의 유일한 차이는 소스(단일 cell vs 전 cell 머지)뿐이라, 그 뒤 로직을 여기로
    모아 drift(필터 누락 비대칭 등)를 막는다. status 유효성은 _invalid_status 가드가 선행.
    반환 (page, total, next_cursor).
    """
    if req.status:
        initiatives = [i for i in initiatives if i.get("status") == req.status]
    if req.hold is not None:
        initiatives = [i for i in initiatives if bool(i.get("hold")) == req.hold]
    if req.parent_initiative_id != "__all__":
        initiatives = [i for i in initiatives if i.get("parent_initiative_id") == req.parent_initiative_id]
    if req.q:
        needle = req.q.strip().lower()
        if needle:
            initiatives = [
                i for i in initiatives
                if needle in (i.get("name") or "").lower()
                or needle in (i.get("initiative_id") or "").lower()
            ]
    total = len(initiatives)
    initiatives.sort(key=lambda i: i.get("updated_at") or "", reverse=True)
    offset = resolve_offset(req.cursor, req.offset)
    page, next_cursor = offset_page(initiatives, offset=offset, limit=req.limit)
    return page, total, next_cursor


@router.post("/initiative.list")
def initiative_list(req: InitiativeListRequest, request: Request) -> CapabilityResponse:
    """Initiative 목록 조회. status·parent_initiative_id 필터·cursor/offset 페이지네이션."""
    cp = get_cell_paths(request)
    initiatives = read_entity_file(cp.initiative_file)  # deleted 는 storage 계층에서 이미 제외
    # archive 는 이제 일반 terminal status — done 처럼 정상 노출. include_archived 는 no-op.
    if (err := _invalid_status(req)) is not None:
        return err
    page, total, next_cursor = _filter_sort_paginate(initiatives, req)
    view.attach_read_state(page, id_field="initiative_id", entity_type="initiative", request=request)
    return CapabilityResponse(status="ok", data={
        "initiatives": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/initiative.list_all")
def initiative_list_all(req: InitiativeListRequest, request: Request) -> CapabilityResponse:
    """User-scoped aggregate. 호출자가 접근 가능한 모든 cell 의 initiative 를 머지.

    응답 envelope·필터·페이지네이션 의미론은 initiative.list 와 동일. record 의 cell_id
    가 보존돼 UI 가 그 값으로 cell 뱃지·라우팅 결정.
    """
    cell_ids = accessible_cell_ids(request)
    initiatives: list[dict] = []
    for cid in cell_ids:
        cp = CellPaths(cid)
        initiatives.extend(read_entity_file(cp.initiative_file))  # deleted 는 storage 계층에서 이미 제외
    # archive 는 이제 일반 terminal status — done 처럼 정상 노출. include_archived 는 no-op.
    if (err := _invalid_status(req)) is not None:
        return err
    page, total, next_cursor = _filter_sort_paginate(initiatives, req)
    view.attach_read_state(page, id_field="initiative_id", entity_type="initiative", request=request)
    return CapabilityResponse(status="ok", data={
        "initiatives": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/initiative.delete")
async def initiative_delete(req: InitiativeDeleteRequest, request: Request) -> CapabilityResponse:
    """Initiative 소프트 삭제 (실수·중복용). archive 와 분리 (audit trail 의도)."""
    cp = get_cell_paths(request)

    def _mutate(found):
        if found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="already_deleted",
                message=f"initiative {req.initiative_id} already deleted",
            )
        now = datetime.now(timezone.utc).isoformat()
        found["deleted"] = True
        found["deleted_at"] = now
        found["updated_at"] = now

    with entity_lock(cp.initiative_file):
        res = cas_entity(cp, "initiative", req.initiative_id, _mutate)
    if res is None:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"initiative {req.initiative_id} not found",
        )
    if isinstance(res, CapabilityResponse):
        return res
    return CapabilityResponse(status="ok", data=res)


@router.post("/initiative.archive")
async def initiative_archive(req: InitiativeArchiveRequest, request: Request) -> CapabilityResponse:
    """Initiative 폐기 — status='archive' 편의 alias (구 archived 플래그 폐기).

    container 모델에서 archive 는 별도 플래그가 아니라 terminal status 다 (Project 과 통일).
    이 capability 는 하위호환 이름 유지용 편의 — status='archive' 로 전이한다. delete 축
    (deleted 플래그) 과는 여전히 직교 — deleted 는 건드리지 않는다.
    """
    cp = get_cell_paths(request)
    box: dict = {}

    def _mutate(found):
        if found.get("status") == "archive" or found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="already_archived",
                message=f"initiative {req.initiative_id} already archived/deleted",
            )
        box["old_status"] = found.get("status")
        found["status"] = "archive"
        found["updated_at"] = datetime.now(timezone.utc).isoformat()

    with entity_lock(cp.initiative_file):
        res = cas_entity(cp, "initiative", req.initiative_id, _mutate)
    if res is None:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"initiative {req.initiative_id} not found",
        )
    if isinstance(res, CapabilityResponse):
        return res
    found = res
    old_status = box["old_status"]
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event(
        "initiative", req.initiative_id, "status_change",
        {"from": old_status, "to": "archive"},
        event_dir=cp.event_dir, session_id=sid, principal=principal,
        cascade_to=[f"cell:{cp.cell_id}"],
    )
    return CapabilityResponse(status="ok", data=found)


@router.post("/initiative.restore")
async def initiative_restore(req: InitiativeRestoreRequest, request: Request) -> CapabilityResponse:
    """폐기·삭제된 Initiative 복원.

    archive 는 이제 status 라 status='archive' → 'backlog' 로 되돌린다. delete 는
    여전히 직교 플래그 — deleted=True 면 플래그를 떨군다 (status 는 그대로). 둘 다면 둘 다 복원.
    """
    cp = get_cell_paths(request)
    box: dict = {}

    def _mutate(found):
        if not (found.get("deleted") or found.get("status") == "archive"):
            return CapabilityResponse(
                status="error", error_code="not_deleted",
                message=f"initiative {req.initiative_id} is not deleted/archived",
            )
        box["old_status"] = found.get("status")
        found.pop("deleted", None)
        found.pop("deleted_at", None)
        if found.get("status") == "archive":
            found["status"] = "backlog"
        found["updated_at"] = datetime.now(timezone.utc).isoformat()

    with entity_lock(cp.initiative_file):
        res = cas_entity(cp, "initiative", req.initiative_id, _mutate)
    if res is None:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"initiative {req.initiative_id} not found",
        )
    if isinstance(res, CapabilityResponse):
        return res
    found = res
    old_status = box["old_status"]
    if found.get("status") != old_status:
        sid = getattr(request.state, "session_id", None)
        principal = getattr(request.state, "principal", None)
        emit_event(
            "initiative", req.initiative_id, "status_change",
            {"from": old_status, "to": found.get("status")},
            event_dir=cp.event_dir, session_id=sid, principal=principal,
            cascade_to=[f"cell:{cp.cell_id}"],
        )
    return CapabilityResponse(status="ok", data=found)


@router.post("/initiative.save")
async def initiative_save(req: InitiativeSaveRequest, request: Request) -> CapabilityResponse:
    """Linear save_initiative 패턴 — initiative_id 유무로 create/update 디스패치."""
    if req.initiative_id:
        upd = InitiativeUpdateRequest(
            initiative_id=req.initiative_id,
            name=req.name,
            description=req.description,
            status=req.status,
            gates=req.gates,
            owner=req.owner,
            color=req.color,
            icon=req.icon,
            parent_initiative_id=req.parent_initiative_id,
            priority=req.priority,
            clear_priority=req.clear_priority,
            resources=req.resources,
        )
        return await initiative_update(upd, request)
    if not (req.name or "").strip():
        return CapabilityResponse(
            status="error", error_code="name_required",
            message="name is required when creating an initiative (no initiative_id provided).",
        )
    create = InitiativeCreateRequest(
        name=req.name,
        description=req.description,
        status=req.status,
        gates=req.gates,
        owner=req.owner,
        color=req.color,
        icon=req.icon,
        parent_initiative_id=req.parent_initiative_id,
        priority=req.priority,
        resources=req.resources,
    )
    return await initiative_create(create, request)


# ── session 영구화 (worker 전용 — active initiative 오케스트레이션 세션 재진입) ──

class InitiativeSetSessionRequest(BaseModel):
    initiative_id: str
    session_id: str | None = None
    last_prompt_at: str | None = None  # issue/project 측과 동일 — 재진입 시 delta cursor.


@router.post("/initiative.set_session")
async def initiative_set_session(req: InitiativeSetSessionRequest, request: Request) -> CapabilityResponse:
    """active Initiative 워커의 Claude session_id + last_prompt_at 영구화. worker 전용.

    issue/project.set_session 과 동형 — pod crash 시 다음 워커가 같은 대화를 --resume.
    """
    from . import entity_set_session
    return entity_set_session(
        cp=get_cell_paths(request), entity_type="initiative", entity_id=req.initiative_id,
        session_id=req.session_id, last_prompt_at=req.last_prompt_at,
    )


# ── 헬퍼 (Project.initiative_id 참조 검증용) ──

def get_initiative(cp, initiative_id: str) -> dict | None:
    """Project 이 initiative_id 참조 시 같은-cell 존재 확인용 헬퍼."""
    _, found = find_entity(cp.initiative_file, "initiative_id", initiative_id)
    if found and not found.get("deleted"):
        return found
    return None


def validate_initiative_ref(cp, initiative_id: str | None) -> CapabilityResponse | None:
    """Project 의 initiative_id 참조 검증. cross-cell 자동 차단 (cp 가 활성 cell 한정).

    cp.initiative_file 가 활성 cell 의 initiatives 만 보므로 cross-cell 참조는
    자동으로 not_found 가 된다 (별도 cell 비교 불필요 — product 패턴 동형).
    """
    if not initiative_id:
        return None
    if not get_initiative(cp, initiative_id):
        return CapabilityResponse(
            status="error", error_code="initiative_not_found",
            message=f"initiative {initiative_id} not found in cell {cp.cell_id} (cross-cell 참조 금지)",
        )
    return None
