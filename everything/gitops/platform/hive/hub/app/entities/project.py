from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from ..storage.idgen import new_entity_id

from capability_framework import CapabilityResponse
from ..config import CellPaths, VALID_CONTAINER_STATUSES, accessible_cell_ids, get_cell_paths
from ..cursor import offset_page, resolve_offset
from ..models import Resource, Priority, Gates, compute_priority_score
from ..helpers import (
    append_jsonl, read_entity_file, find_entity, get_entity_by_id,
    emit_event, resolve_me_alias, resolve_owner,
    normalize_resources,
    entity_lock,
)
from . import (
    apply_entity_fields_and_persist, cas_entity, container_transition_denied,
    entity_add_pr, entity_set_session,
)
from .event import CommentSubtype
from . import view
from .initiative import validate_initiative_ref
from ..git_scan import scan_artifacts
from ..meta_deployments import scan_deployments


DEFAULT_PRIORITY = {"value": 2}  # Low — 사용자가 지정 안 하면 기본 Low

router = APIRouter()


def _resolve_resource_path(project_id: str, *, cell_name: str) -> str:
    """Project entity space 경로. 모든 Project 은 자기 space 를 갖는다 (Linear 정합)."""
    return f"data/cells/{cell_name}/projects/{project_id}"


def _ensure_resource_path(project: dict, *, cell_name: str) -> dict:
    """읽기 시 resource_path가 없으면 동적으로 계산 (기존 데이터 호환)."""
    if "resource_path" not in project:
        project["resource_path"] = _resolve_resource_path(
            project["project_id"], cell_name=cell_name,
        )
    return project


def _ensure_initiative_id(project: dict) -> dict:
    """initiative_id 필드가 없으면 None 으로 backfill — null 도 명시 노출 (curation 검증 가능).

    feature 도입 이전에 저장된 legacy project 은 디스크에 키가 없을 수 있다.
    """
    project.setdefault("initiative_id", None)
    return project


def _ensure_initiative_summary(project: dict, *, cp) -> dict:
    """Project.initiative_id 가 있으면 얕은 깊이 summary 를 derived field 로 첨부.

    worker prompt outcome 정렬 참조용. name/status 만 — description /
    sub-initiative chain 제외 (Chroma context rot 회피).
    """
    initiative_id = project.get("initiative_id")
    if not initiative_id:
        return project
    from .initiative import get_initiative
    parent = get_initiative(cp, initiative_id)
    if parent:
        project["initiative"] = {
            "initiative_id": parent["initiative_id"],
            "name": parent["name"],
            "status": parent["status"],
        }
    return project


class ProjectCreateRequest(BaseModel):
    title: str
    description: str | None = None
    plan: str | None = Field(
        default=None,
        description='워커가 작성하는 planning_frameworks 본문. 사람은 보통 비워둔다.',
    )
    owner: str | None = Field(
        default=None,
        description='Owner email. "me" 단축형 지원 — 호출자 이메일로 치환.',
    )
    dependencies: list[str] | None = None
    resources: list[Resource] | None = None
    apps: list[str] | None = Field(
        default=None,
        description='이 Project 이 소유/관련된 meta App 이름 리스트. hub 가 meta 에서 그 앱의 live 배포 URL 을 derived `deployments` 로 노출. 앱을 scaffold 한 워커가 그 앱 이름을 선언한다.',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. 1=Backlog, 2=Low(기본), 3=Medium, 4=High, 5=Urgent.',
    )
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto(기본) | require. require 면 active→done 직접 전이 금지 (워커가 active→waiting 핸드오프, 사람이 waiting→done 확정).',
    )
    metadata: dict | None = None
    source_signal_ids: list[str] | None = None
    labels: list[str] | None = None  # label_id 리스트. 없으면 빈 list.
    status: str | None = Field(
        default=None,
        description='backlog | active(기본) | waiting | done | archive.',
    )
    hold: bool = Field(
        default=False,
        description='True 면 agent-loop 가 이 project(및 직속 자식 issue) 을 자동 픽업하지 않는다. 개인 세션 수동 작업 중 자동 워커 간섭 방지.',
    )
    initiative_id: str | None = Field(
        default=None,
        description='이 Project 이 advance 하는 Initiative (strategic anchor). 같은 cell 의 initiative_id 만 허용 (cross-cell 거부). 미설정 시 null — standalone Project 허용 (Linear 정합).',
    )


def _effective_activity(e: dict) -> str:
    """변경 최신성 — 코멘트/상태전이(last_activity_ts)와 필드변경(updated_at) 중 최신.
    last_activity_ts 는 코멘트만, updated_at 은 필드변경만 잡아 단독으론 누락이 생긴다."""
    return max(e.get("last_activity_ts") or "", e.get("updated_at") or "")


class ProjectListRequest(BaseModel):
    status: str | None = Field(
        default=None,
        description='backlog | active | waiting | done | archive.',
    )
    hold: bool | None = Field(
        default=None,
        description='True 면 hold=true 만, False 면 hold=false 만. 생략 시 hold 무관. status 필터와 직교(AND).',
    )
    owner: str | None = Field(
        default=None,
        description='Owner email 또는 "me" (호출자 이메일로 치환).',
    )
    initiative_id: str | None = Field(
        default="__all__",
        description='"__all__"=전부(기본) / None=standalone(initiative 미attach) / 특정 id=그 initiative 에 attach 된 Project 만. Linear parent_id 패턴.',
    )
    limit: int = 50
    offset: int = 0
    cursor: str | None = Field(
        default=None,
        description='이전 응답의 next_cursor 토큰. 제공되면 offset 무시.',
    )
    sort_by: Literal["updated_at", "created_at"] = "updated_at"
    sort_order: Literal["asc", "desc"] = "desc"
    activity_since: str | None = Field(
        default=None,
        description='ISO8601. 지정 시 effective activity(max(last_activity_ts, updated_at)) 가 이 값 이상인 것만 — 코멘트만 달려 updated_at 이 안 움직인 항목도 포함. 이때 정렬은 effective activity 기준(sort_by 무시). "오늘 변경" 집계용.',
    )
    q: str | None = Field(
        default=None,
        description='자유 텍스트 substring 필터 (case-insensitive). title 과 project_id 양쪽에 match. 빈 문자열·공백은 무필터.',
    )


class ProjectGetRequest(BaseModel):
    project_id: str


class ProjectUpdateRequest(BaseModel):
    project_id: str
    status: str | None = Field(
        default=None,
        description='backlog | active | waiting | done | archive. None=유지. active→waiting(사람 대기로 parked), waiting→active(재개)/done(사람 완료 확정)/archive(폐기).',
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
        description='subtype 별 권장 structured 필드. handoff: {pr_url, summary, options?}, halt: {reason, recovery_options, options?}. options 는 ActivityFeed 원본 코멘트의 인라인 원클릭 버튼 (handoff_patterns 정본): [{label, key?, tone?, action: {type:"transition", status, comment?} | {type:"reply", text, subtype?} | {type:"create", entity:"project"|"issue", draft}}]. 비어 있으면 본문/payload 만 노출 (하위 호환).',
    )
    title: str | None = None
    description: str | None = None
    plan: str | None = Field(
        default=None,
        description='워커가 planning_frameworks 본문을 쓰는 슬롯. None=유지.',
    )
    owner: str | None = Field(
        default=None,
        description='Owner email. "me" 단축형 지원.',
    )
    resources: list[Resource] | None = None
    apps: list[str] | None = Field(
        default=None,
        description='meta App 이름 리스트. 지정 시 통째 교체, None=유지. derived `deployments` 소스.',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. 1=Backlog, 2=Low, 3=Medium, 4=High, 5=Urgent. None=유지.',
    )
    clear_priority: bool = False  # True면 priority를 None으로 비움
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto | require.',
    )
    metadata: dict | None = None
    source_signal_ids: list[str] | None = None
    labels: list[str] | None = None  # 지정하면 통째로 교체 (None 이면 변경 안 함).
    dependencies: list[str] | None = Field(
        default=None,
        description='추가할 dependency project_id 리스트. append-only — 기존 유지. Linear blockedBy 패턴.',
    )
    remove_dependencies: list[str] | None = Field(
        default=None,
        description='제거할 dependency project_id 리스트. Linear removeBlockedBy 패턴.',
    )
    hold: bool | None = Field(
        default=None,
        description='True=agent-loop 자동 픽업 차단, False=해제, None=유지. 개인 세션 수동 작업 보호용.',
    )
    initiative_id: str | None = Field(
        default=None,
        description='이 Project 이 advance 하는 Initiative. None=유지. 변경 시 같은 cell 의 initiative_id 만 허용.',
    )


class ProjectSaveRequest(BaseModel):
    """Linear ``save_project`` 패턴 — id 유무로 create/update 분기.

    ``project_id`` 가 있으면 update, 없으면 create (title 필수). MCP 호출자는 이 한 툴로
    project mutation 전부 가능. 기존 project.create / project.update 도 alias 로 유지.
    """
    project_id: str | None = Field(
        default=None,
        description='제공 시 update, 없으면 create.',
    )
    title: str | None = Field(
        default=None,
        description='create 시 필수. update 시 None=변경없음.',
    )
    description: str | None = None
    plan: str | None = Field(
        default=None,
        description='워커가 작성하는 planning_frameworks 본문.',
    )
    owner: str | None = Field(
        default=None,
        description='Owner email. "me" 단축형 지원.',
    )
    dependencies: list[str] | None = Field(
        default=None,
        description='create: 초기 dependency 리스트. update: 추가할 project_id (append-only). Linear blockedBy 패턴.',
    )
    remove_dependencies: list[str] | None = Field(
        default=None,
        description='update 전용. 제거할 dependency project_id.',
    )
    resources: list[Resource] | None = None
    apps: list[str] | None = Field(
        default=None,
        description='meta App 이름 리스트. derived `deployments` 소스.',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. 1=Backlog, 2=Low, 3=Medium, 4=High, 5=Urgent.',
    )
    clear_priority: bool = Field(
        default=False,
        description='update 시 priority None 으로. create 에선 무시.',
    )
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto | require.',
    )
    metadata: dict | None = None
    source_signal_ids: list[str] | None = None
    labels: list[str] | None = None
    status: str | None = Field(
        default=None,
        description='backlog | active | waiting | done | archive.',
    )
    comment: str | None = Field(
        default=None,
        description='update 시 AI status 전이 필수.',
    )
    comment_subtype: CommentSubtype = Field(
        default="transition",
        description='discussion | progress | transition(기본) | handoff | halt.',
    )
    comment_payload: dict = Field(default={})
    hold: bool | None = Field(
        default=None,
        description='True=agent-loop 자동 픽업 차단, False=해제, None=유지(create 시 False).',
    )
    initiative_id: str | None = Field(
        default=None,
        description='이 Project 이 advance 하는 Initiative. 같은 cell 의 initiative_id 만 허용.',
    )


@router.post("/project.create")
async def project_create(req: ProjectCreateRequest, request: Request) -> CapabilityResponse:
    """Project 생성. status 명시 시 우선, 기본은 active."""
    cp = get_cell_paths(request)
    cell_name = cp.cell_id

    now = datetime.now(timezone.utc).isoformat()
    initial_status = req.status or "active"
    if initial_status not in VALID_CONTAINER_STATUSES:
        return CapabilityResponse(
            status="error", error_code="invalid_status",
            message=f"invalid status: {initial_status!r}. valid: {sorted(VALID_CONTAINER_STATUSES)}",
        )
    owner = resolve_me_alias(req.owner, request)
    if not owner:
        owner = getattr(request.state, "user_email", None)
    # owner 미해석 시 미할당(None) — 자동화 생성은 owner 없이, console 사람 생성은
    # user_email fallback 으로 자기할당 유지 (issue.create 와 동일 정책).
    initiative_err = validate_initiative_ref(cp, req.initiative_id)
    if initiative_err:
        return initiative_err
    project_id, seq = new_entity_id(cell_name, "project")
    resource_path = _resolve_resource_path(project_id, cell_name=cell_name)
    from .label import normalize_label_ids
    label_ids, label_err = normalize_label_ids(cp, req.labels)
    if label_err:
        return label_err
    record = {
        "project_id": project_id,
        "seq": seq,
        "title": req.title,
        "description": req.description,
        "plan": req.plan,
        "owner": owner,
        "status": initial_status,
        "dependencies": req.dependencies or [],
        "gates": req.gates.model_dump() if req.gates else None,
        "source_signal_ids": req.source_signal_ids or [],
        "cell_id": cell_name,
        "resource_path": resource_path,
        "resources": normalize_resources([r.model_dump() for r in req.resources]) if req.resources else [],
        "apps": req.apps or [],
        "priority": (req.priority.model_dump() if req.priority else DEFAULT_PRIORITY),
        "priority_score": compute_priority_score(req.priority.model_dump() if req.priority else DEFAULT_PRIORITY),
        "labels": label_ids or [],
        "metadata": req.metadata or {},
        "hold": bool(req.hold),
        "initiative_id": req.initiative_id,
        "created_at": now,
        "updated_at": now,
    }
    append_jsonl(cp.project_file, record)
    # seq 는 project_id 발급 시 entity_seq 에서 함께 받아 record 에 이미 포함.
    # push 알림: cell agent-loop 가 새 actionable 등장 → 즉시 spawn.
    from .. import wake_bus
    wake_bus.notify(f"cell:{cp.cell_id}")
    return CapabilityResponse(status="ok", data=record)


def _filter_sort_paginate(projects, req, request):
    """project.list / project.list_all 공유 — 동일 필터·정렬·페이지네이션.

    두 핸들러의 유일한 차이는 소스(단일 cell vs 전 cell 머지)와 페이지 backfill 뿐이라,
    그 사이 필터/정렬/페이지 로직을 여기로 모아 drift(필터 누락 비대칭 등)를 막는다.
    반환 (page, total, next_cursor).
    """
    if req.status:
        projects = [g for g in projects if g["status"] == req.status]
    if req.hold is not None:
        projects = [g for g in projects if bool(g.get("hold")) == req.hold]
    if req.initiative_id != "__all__":
        projects = [g for g in projects if g.get("initiative_id") == req.initiative_id]
    owner_filter = resolve_me_alias(req.owner, request)
    if owner_filter:
        projects = [g for g in projects if g.get("owner") == owner_filter]
    if req.q:
        needle = req.q.strip().lower()
        if needle:
            projects = [
                g for g in projects
                if needle in (g.get("title") or "").lower()
                or needle in (g.get("project_id") or "").lower()
            ]
    if req.activity_since:
        projects = [g for g in projects if _effective_activity(g) >= req.activity_since]
    total = len(projects)
    if req.activity_since:
        projects.sort(key=_effective_activity, reverse=(req.sort_order == "desc"))
    else:
        projects.sort(
            key=lambda g: g.get(req.sort_by) or "",
            reverse=(req.sort_order == "desc"),
        )
    offset = resolve_offset(req.cursor, req.offset)
    page, next_cursor = offset_page(projects, offset=offset, limit=req.limit)
    return page, total, next_cursor


@router.post("/project.list")
def project_list(req: ProjectListRequest, request: Request) -> CapabilityResponse:
    """Project 목록 조회. status 로 필터링. cursor 또는 offset 페이지네이션."""
    cp = get_cell_paths(request)
    projects = read_entity_file(cp.project_file)  # deleted 는 storage 계층에서 이미 제외
    page, total, next_cursor = _filter_sort_paginate(projects, req, request)
    # resolved_owner + resource_path + initiative_id backfill.
    for g in page:
        g["resolved_owner"] = resolve_owner(g, "project", project_file=cp.project_file)
        _ensure_resource_path(g, cell_name=cp.cell_id)
        _ensure_initiative_id(g)
    view.attach_read_state(page, id_field="project_id", entity_type="project", request=request)
    return CapabilityResponse(status="ok", data={
        "projects": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/project.list_all")
def project_list_all(req: ProjectListRequest, request: Request) -> CapabilityResponse:
    """User-scoped aggregate. 호출자가 접근 가능한 모든 cell 의 project 을 머지.

    응답 envelope·필터·페이지네이션 의미론은 project.list 와 동일. record 의 cell_id
    가 보존돼 UI 가 그 값으로 cell 뱃지·라우팅 결정.
    resolved_owner / resource_path backfill 은 페이지 슬라이스 한정 — 항목 cell
    의 project_file 만 lazy 로드해 중복 I/O 회피.
    """
    cell_ids = accessible_cell_ids(request)
    projects: list[dict] = []
    for cid in cell_ids:
        cp = CellPaths(cid)
        projects.extend(read_entity_file(cp.project_file))  # deleted 는 storage 계층에서 이미 제외
    page, total, next_cursor = _filter_sort_paginate(projects, req, request)
    for g in page:
        gcell = g.get("cell_id")
        if not gcell:
            continue
        cp_g = CellPaths(gcell)
        g["resolved_owner"] = resolve_owner(g, "project", project_file=cp_g.project_file)
        _ensure_resource_path(g, cell_name=gcell)
        _ensure_initiative_id(g)
    view.attach_read_state(page, id_field="project_id", entity_type="project", request=request)
    return CapabilityResponse(status="ok", data={
        "projects": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/project.get")
def project_get(req: ProjectGetRequest, request: Request) -> CapabilityResponse:
    """단일 Project 상세 조회."""
    cp = get_cell_paths(request)
    _, found = find_entity(cp.project_file, "project_id", req.project_id)
    if not found:
        return CapabilityResponse(status="error", error_code="not_found", message=f"project {req.project_id} not found")
    found["resolved_owner"] = resolve_owner(found, "project", project_file=cp.project_file)
    _ensure_resource_path(found, cell_name=cp.cell_id)
    _ensure_initiative_id(found)
    _ensure_initiative_summary(found, cp=cp)
    found["artifacts"] = scan_artifacts(cp.cell_id, "project", req.project_id)
    found["deployments"] = scan_deployments(cp.cell_id, app_names=found.get("apps") or [])
    return CapabilityResponse(status="ok", data=found)


class ProjectDeleteRequest(BaseModel):
    project_id: str


@router.post("/project.delete")
async def project_delete(req: ProjectDeleteRequest, request: Request) -> CapabilityResponse:
    """Project 소프트 삭제. deleted 플래그를 설정한다."""
    cp = get_cell_paths(request)

    def _mutate(found):
        if found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="already_deleted",
                message=f"project {req.project_id} is already deleted",
            )
        now = datetime.now(timezone.utc).isoformat()
        found["deleted"] = True
        found["deleted_at"] = now
        found["updated_at"] = now

    res = cas_entity(cp, "project", req.project_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"project {req.project_id} not found")
    if isinstance(res, CapabilityResponse):
        return res
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event("project", req.project_id, "deleted", {}, event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data=res)


class ProjectRestoreRequest(BaseModel):
    project_id: str


@router.post("/project.restore")
async def project_restore(req: ProjectRestoreRequest, request: Request) -> CapabilityResponse:
    """삭제된 Project 복원."""
    cp = get_cell_paths(request)

    def _mutate(found):
        if not found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="not_deleted",
                message=f"project {req.project_id} is not deleted",
            )
        found.pop("deleted", None)
        found.pop("deleted_at", None)
        found["updated_at"] = datetime.now(timezone.utc).isoformat()

    res = cas_entity(cp, "project", req.project_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"project {req.project_id} not found")
    if isinstance(res, CapabilityResponse):
        return res
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event("project", req.project_id, "restored", {}, event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data=res)


@router.post("/project.update")
async def project_update(req: ProjectUpdateRequest, request: Request) -> CapabilityResponse:
    """Project 상태 전이 및 필드 수정.

    container 종결 전이 가드만 강제: gates.completion=require 면 active→done 직접 금지
    (워커가 active→waiting 핸드오프, 사람이 waiting→done 확정). auto(기본)/skip 은
    active→done 직접 허용 — cleanup 중간 상태 없음. waiting 은 non-terminal (active↔waiting,
    waiting→done/archive 자유). terminal(done/archive)에서 나가는 전이는 금지(force_update).
    archive 는 어느 비-terminal 에서도 허용. 그 외 전이 graph·검증은 spec 위임 (AI 책임).
    가드 우회는 ``project.force_update``.
    """
    cp = get_cell_paths(request)
    if req.owner == "me":
        req.owner = resolve_me_alias(req.owner, request)
    with entity_lock(cp.project_file):
        return apply_entity_fields_and_persist(
            req=req, request=request, cp=cp, entity_type="project",
            validate_status=_project_validate_status,
        )


@router.post("/project.save")
async def project_save(req: ProjectSaveRequest, request: Request) -> CapabilityResponse:
    """Linear ``save_project`` 패턴 — ``project_id`` 유무로 create/update 디스패치.

    내부적으로 ``project.create`` / ``project.update`` 그대로 호출 — 동작/검증/event/inbox
    /cascade 처리 100% 일치. 새 호출자는 한 툴로 모든 project mutation 가능,
    기존 호출자는 ``project.create``/``project.update`` alias 그대로.
    """
    if req.project_id:
        upd = ProjectUpdateRequest(
            project_id=req.project_id,
            status=req.status,
            comment=req.comment,
            comment_subtype=req.comment_subtype,
            comment_payload=req.comment_payload,
            title=req.title,
            description=req.description,
            plan=req.plan,
            owner=req.owner,
            resources=req.resources,
            apps=req.apps,
            priority=req.priority,
            clear_priority=req.clear_priority,
            gates=req.gates,
            metadata=req.metadata,
            source_signal_ids=req.source_signal_ids,
            labels=req.labels,
            dependencies=req.dependencies,
            remove_dependencies=req.remove_dependencies,
            hold=req.hold,
            initiative_id=req.initiative_id,
        )
        return await project_update(upd, request)
    if not (req.title or "").strip():
        return CapabilityResponse(
            status="error", error_code="title_required",
            message="title is required when creating a project (no project_id provided).",
        )
    create = ProjectCreateRequest(
        title=req.title,
        description=req.description,
        plan=req.plan,
        owner=req.owner,
        dependencies=req.dependencies,
        resources=req.resources,
        apps=req.apps,
        priority=req.priority,
        gates=req.gates,
        metadata=req.metadata,
        source_signal_ids=req.source_signal_ids,
        labels=req.labels,
        status=req.status,
        hold=bool(req.hold),
        initiative_id=req.initiative_id,
    )
    return await project_create(create, request)


@router.post("/project.force_update")
async def project_force_update(req: ProjectUpdateRequest, request: Request) -> CapabilityResponse:
    """project.update 와 동일 본문이되 종결 전이 가드를 우회."""
    cp = get_cell_paths(request)
    if req.owner == "me":
        req.owner = resolve_me_alias(req.owner, request)
    with entity_lock(cp.project_file):
        return apply_entity_fields_and_persist(
            req=req, request=request, cp=cp, entity_type="project",
            validate_status=_project_validate_status, enforce_guard=False,
        )


def _project_validate_status(old_status, new_status, req, found, enforce_guard) -> CapabilityResponse | None:
    """project(container) status 전이 검증 — CAS 루프 안에서 fresh entity 기준 매 시도 재실행.
    invalid_status 는 항상, container 종결 가드는 enforce_guard 만. completion 은 req.gates 우선.
    """
    if new_status not in VALID_CONTAINER_STATUSES:
        return CapabilityResponse(status="error", error_code="invalid_status", message=f"invalid status: {new_status}")
    if enforce_guard:
        completion = "auto"
        if req.gates is not None:
            completion = req.gates.completion
        elif found.get("gates"):
            completion = found["gates"].get("completion", "auto")
        denied = container_transition_denied(old_status, new_status, completion)
        if denied:
            return CapabilityResponse(status="error", error_code="transition_denied", message=denied)
    return None


# ── session 영구화 + PR 누적 ──

class GoalSetSessionRequest(BaseModel):
    project_id: str
    session_id: str | None = None
    last_prompt_at: str | None = None  # issue 측과 동일 — 재진입 시 delta cursor.


@router.post("/project.set_session")
async def project_set_session(req: GoalSetSessionRequest, request: Request) -> CapabilityResponse:
    return entity_set_session(
        cp=get_cell_paths(request), entity_type="project", entity_id=req.project_id,
        session_id=req.session_id, last_prompt_at=req.last_prompt_at,
    )


class GoalAddPrRequest(BaseModel):
    project_id: str
    pr: dict


@router.post("/project.add_pr")
async def project_add_pr(req: GoalAddPrRequest, request: Request) -> CapabilityResponse:
    return entity_add_pr(cp=get_cell_paths(request), entity_type="project", entity_id=req.project_id, pr=req.pr)


