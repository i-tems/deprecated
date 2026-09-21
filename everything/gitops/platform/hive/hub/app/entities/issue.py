from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

ModelName = Literal["high", "medium", "low"]
from ..storage.idgen import new_entity_id

from capability_framework import CapabilityResponse
from ..config import CellPaths, VALID_STATUSES, accessible_cell_ids, get_cell_paths
from ..cursor import offset_page, resolve_offset
from ..models import Resource, Priority, Gates, compute_priority_score
from ..helpers import (
    append_jsonl, read_entity_file, find_entity, get_entity_by_id,
    emit_event, resolve_me_alias, resolve_owner,
    normalize_resources,
    entity_lock,
)


from . import (
    apply_entity_fields_and_persist, cas_entity, entity_add_pr, entity_set_session,
    terminal_transition_denied,
)
from .event import CommentSubtype
from . import view
from .initiative import validate_initiative_ref
from ..git_scan import scan_artifacts
from ..meta_deployments import preview_readiness, scan_deployments

DEFAULT_PRIORITY = {"value": 2}  # Low — 사용자가 지정 안 하면 기본 Low

router = APIRouter()


def _ensure_initiative_id(issue: dict) -> dict:
    """initiative_id 필드가 없으면 None backfill — feature 도입 이전 legacy issue 호환.

    null 도 명시 노출 (project.py `_ensure_initiative_id` 동형).
    """
    issue.setdefault("initiative_id", None)
    return issue


def _effective_initiative_id(issue: dict, projects_by_id: dict) -> str | None:
    """Issue 의 effective initiative.

    project 가 있으면 상위 Project 의 initiative 를 따라가고 (Issue 자체 initiative_id
    는 dormant — project 떼면 부활), standalone 이면 자체 initiative_id.
    """
    pid = issue.get("project_id")
    if pid:
        proj = projects_by_id.get(pid)
        return proj.get("initiative_id") if proj else None
    return issue.get("initiative_id")


def _ensure_initiative_summary(issue: dict, *, cp, projects_by_id: dict) -> dict:
    """effective initiative 의 얕은 summary 를 derived `initiative` field 로 첨부.

    project.py `_ensure_initiative_summary` 미러 — name/status 만 (description·
    sub-initiative chain 제외). `effective_initiative_id` 도 함께 노출.
    """
    eff = _effective_initiative_id(issue, projects_by_id)
    issue["effective_initiative_id"] = eff
    if not eff:
        return issue
    from .initiative import get_initiative
    parent = get_initiative(cp, eff)
    if parent:
        issue["initiative"] = {
            "initiative_id": parent["initiative_id"],
            "name": parent["name"],
            "status": parent["status"],
        }
    return issue


class IssueCreateRequest(BaseModel):
    title: str
    project_id: str | None = None
    description: str | None = None
    plan: str | None = Field(
        default=None,
        description='워커가 작성하는 planning_frameworks 본문. 사람은 보통 비워둔다.',
    )
    owner: str | None = Field(
        default=None,
        description='Owner email. "me" 단축형 지원 — 호출자(JWT principal)의 이메일로 치환. 미지정 시 부모 project 의 owner 상속.',
    )
    dependencies: list[str] | None = None
    capability: list[str] | None = None
    model: ModelName | None = Field(
        default=None,
        description='worker 모델 등급. high | medium | low. running 전이 전 필수.',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. 1=Backlog, 2=Low(기본), 3=Medium, 4=High, 5=Urgent. 미지정 시 Low.',
    )
    resources: list[Resource] | None = None
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto(기본) | require. require 면 running→done 직접 전이 금지.',
    )
    metadata: dict | None = None
    source_signal_ids: list[str] | None = None
    labels: list[str] | None = None  # label_id 리스트. 없으면 빈 list.
    status: str | None = Field(
        default=None,
        description='backlog | todo(기본) | running | waiting | cleanup | done | cancelled | error. 미지정 시 todo.',
    )
    hold: bool = Field(
        default=False,
        description='True 면 agent-loop 가 이 issue 를 자동 픽업하지 않는다 (status 와 무관, 사람이 명시 해제할 때까지). 개인 세션에서 수동 작업 중 자동 워커 간섭을 막는 용도.',
    )
    initiative_id: str | None = Field(
        default=None,
        description='이 Issue 가 advance 하는 Initiative (strategic anchor). 같은 cell 의 initiative_id 만 허용 (cross-cell 거부). project 가 있으면 effective initiative 는 상위 Project 를 따라가고 이 값은 dormant 로 보존 (standalone↔project 전이 round-trip). standalone Issue 일 때만 effective.',
    )


def _effective_activity(e: dict) -> str:
    """변경 최신성 — 코멘트/상태전이(last_activity_ts)와 필드변경(updated_at) 중 최신.
    last_activity_ts 는 코멘트만, updated_at 은 필드변경만 잡아 단독으론 누락이 생긴다."""
    return max(e.get("last_activity_ts") or "", e.get("updated_at") or "")


class IssueListRequest(BaseModel):
    project_id: str | None = None
    standalone: bool | None = None
    initiative_id: str | None = Field(
        default="__all__",
        description='"__all__"=전부(기본) / None=initiative 미연결 / 특정 id=그 initiative 에 effective 연결된 Issue 만. effective 기준 — project 있는 Issue 는 상위 Project 의 initiative. standalone=true 와 조합하면 직접 anchor 된 standalone Issue 만. Linear parent_id 패턴.',
    )
    status: str | None = Field(
        default=None,
        description='단일 상태 필터. backlog | todo | running | waiting | cleanup | done | cancelled | error.',
    )
    statuses: list[str] | None = Field(
        default=None,
        description='다중 상태 필터 (any-of). status 와 동시 지정 시 status 가 우선.',
    )
    hold: bool | None = Field(
        default=None,
        description='True 면 hold=true 만, False 면 hold=false 만. 생략 시 hold 무관. status 필터와 직교(AND).',
    )
    owner: str | None = Field(
        default=None,
        description='Owner email 또는 "me" (호출자 이메일로 치환).',
    )
    limit: int = 50
    offset: int = 0
    cursor: str | None = Field(
        default=None,
        description='이전 응답의 next_cursor 토큰. 제공되면 offset 무시. Linear MCP cursor 패턴.',
    )
    sort_by: Literal["updated_at", "created_at"] = "updated_at"
    sort_order: Literal["asc", "desc"] = "desc"
    activity_since: str | None = Field(
        default=None,
        description='ISO8601. 지정 시 effective activity(max(last_activity_ts, updated_at)) 가 이 값 이상인 것만 — 코멘트만 달려 updated_at 이 안 움직인 항목도 포함. 이때 정렬은 effective activity 기준(sort_by 무시), pagination 이 코멘트만 달린 항목을 자르지 않게 한다. "오늘 변경" 집계용.',
    )
    q: str | None = Field(
        default=None,
        description='자유 텍스트 substring 필터 (case-insensitive). title 과 issue_id 양쪽에 match. 빈 문자열·공백은 무필터.',
    )


class IssueGetRequest(BaseModel):
    issue_id: str


class IssueUpdateRequest(BaseModel):
    issue_id: str
    status: str | None = Field(
        default=None,
        description='backlog | todo | running | waiting | cleanup | done | cancelled | error. None=유지 (필드만 수정).',
    )
    comment: str | None = Field(
        default=None,
        description='AI status 전이 시 필수 (사람이 활동 피드에서 이유를 읽음).',
    )
    comment_subtype: CommentSubtype = Field(
        default="transition",
        description='discussion=일반토론 | progress=같은상태내진척 | transition=상태전이사유(기본) | handoff=waiting/review 진입핸드오프 | halt=실패중단.',
    )
    comment_payload: dict = Field(
        default={},
        description='subtype 별 권장 structured 필드 — handoff: {pr_url, summary, options?}, halt: {reason, recovery_options, options?}, done: {options?} (후속 create 버튼). options 는 ActivityFeed 원본 코멘트의 인라인 원클릭 버튼 (handoff_patterns 정본): [{label, key?, tone?, action: {type:"transition", status, comment?} | {type:"reply", text, subtype?} | {type:"create", entity:"project"|"issue", draft}}]. 비어 있으면 본문/payload 만 노출 (하위 호환).',
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
    capability: list[str] | None = None
    model: ModelName | None = Field(
        default=None,
        description='high | medium | low.',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. 1=Backlog, 2=Low, 3=Medium, 4=High, 5=Urgent. None=유지.',
    )
    clear_priority: bool = False  # True면 priority를 None으로 비움
    resources: list[Resource] | None = None
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto | require.',
    )
    metadata: dict | None = None
    source_signal_ids: list[str] | None = None
    labels: list[str] | None = None  # 지정하면 통째로 교체 (None 이면 변경 안 함).
    dependencies: list[str] | None = Field(
        default=None,
        description='추가할 dependency issue_id 리스트. append-only — 기존 dependency 는 그대로 유지, 새 id 만 더해진다. 제거는 remove_dependencies. Linear blockedBy 패턴.',
    )
    remove_dependencies: list[str] | None = Field(
        default=None,
        description='제거할 dependency issue_id 리스트. Linear removeBlockedBy 패턴.',
    )
    hold: bool | None = Field(
        default=None,
        description='True=agent-loop 자동 픽업 차단, False=해제, None=유지. 개인 세션 수동 작업 보호용.',
    )
    initiative_id: str | None = Field(
        default=None,
        description='이 Issue 가 advance 하는 Initiative. None=유지. 변경 시 같은 cell 의 initiative_id 만 허용 (cross-cell 거부). project 있으면 effective 는 상위 Project 를 따라가고 이 값은 dormant.',
    )


class IssueSaveRequest(BaseModel):
    """Linear ``save_issue`` 패턴 — id 유무로 create/update 분기.

    ``issue_id`` 가 있으면 update 동작 (해당 필드만 부분 수정), 없으면 create
    (title 필수). MCP 호출자는 이 한 툴로 issue mutation 전부 가능. 기존
    issue.create / issue.update 도 alias 로 유지된다.
    """
    issue_id: str | None = Field(
        default=None,
        description='제공 시 update, 없으면 create. Linear save_issue.id 패턴.',
    )
    title: str | None = Field(
        default=None,
        description='create 시 필수. update 시 None=변경없음.',
    )
    project_id: str | None = Field(
        default=None,
        description='create 전용. update 에선 project 재배치 별도로.',
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
        description='create: 초기 dependency 리스트. update: 추가할 issue_id (append-only, 기존 유지). Linear blockedBy 패턴.',
    )
    remove_dependencies: list[str] | None = Field(
        default=None,
        description='update 전용. 제거할 dependency issue_id. Linear removeBlockedBy 패턴.',
    )
    capability: list[str] | None = None
    model: ModelName | None = Field(
        default=None,
        description='high | medium | low. running 전이 전 필수.',
    )
    priority: Priority | None = Field(
        default=None,
        description='value 1-5. 1=Backlog, 2=Low(create 기본), 3=Medium, 4=High, 5=Urgent.',
    )
    clear_priority: bool = Field(
        default=False,
        description='update 시 priority 를 None 으로 비움. create 에선 무시.',
    )
    resources: list[Resource] | None = None
    gates: Gates | None = Field(
        default=None,
        description='completion: skip | auto | require.',
    )
    metadata: dict | None = None
    source_signal_ids: list[str] | None = None
    labels: list[str] | None = None
    status: str | None = Field(
        default=None,
        description='backlog | todo | running | waiting | cleanup | done | cancelled | error. create 미지정 시 todo, update 미지정 시 유지.',
    )
    hold: bool | None = Field(
        default=None,
        description='True=agent-loop 자동 픽업 차단, False=해제, None=유지(create 시 False).',
    )
    initiative_id: str | None = Field(
        default=None,
        description='이 Issue 가 advance 하는 Initiative. 같은 cell 의 initiative_id 만 허용. project 있으면 effective 는 상위 Project 를 따라가고 이 값은 dormant.',
    )
    # update path 전용 — status 전이 시 활동 피드 코멘트.
    comment: str | None = Field(
        default=None,
        description='update 시 AI status 전이 필수.',
    )
    comment_subtype: CommentSubtype = Field(
        default="transition",
        description='discussion | progress | transition(기본) | handoff | halt.',
    )
    comment_payload: dict = Field(
        default={},
        description='subtype 별 권장 structured 필드. handoff/halt/done 에 options: [{label, key?, tone?, action: {type:"transition"|"reply"|"create", ...}}] 추가 시 ActivityFeed 원본 코멘트에 인라인 원클릭 버튼 렌더 (handoff_patterns 정본).',
    )


@router.post("/issue.create")
async def issue_create(req: IssueCreateRequest, request: Request) -> CapabilityResponse:
    """Issue 생성. project_id는 선택. status 미지정 시 'todo'."""
    cp = get_cell_paths(request)

    project = None
    if req.project_id:
        project = get_entity_by_id(cp.project_file, "project_id", req.project_id)
        if not project:
            return CapabilityResponse(status="error", error_code="not_found", message=f"project {req.project_id} not found")
        if project.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="project_deleted",
                message=f"cannot create issue: project {req.project_id} is deleted",
            )
        if project["status"] != "active":
            return CapabilityResponse(
                status="error", error_code="project_not_running",
                message=f"cannot create issue: project is '{project['status']}', must be 'active'",
            )

    owner = resolve_me_alias(req.owner, request)
    if not owner and project:
        owner = resolve_owner(
            project,
            "project",
            projects=read_entity_file(cp.project_file),
            project_file=cp.project_file,
        )
    if not owner:
        owner = getattr(request.state, "user_email", None)
    # owner 미해석 시 미할당(None)으로 둔다 — 자동화(워커·스케줄러)가 만든 entity 는
    # owner 없이 생성돼 사람이 직접 claim. console 사람 생성은 위 user_email fallback 으로
    # 자기할당이 유지된다 (자동화만 미할당).

    resources = None
    if req.resources is not None:
        resources = normalize_resources([r.model_dump() for r in req.resources])

    now = datetime.now(timezone.utc).isoformat()
    initial_status = req.status or "todo"
    if initial_status not in VALID_STATUSES:
        return CapabilityResponse(
            status="error", error_code="invalid_status",
            message=f"invalid status: {initial_status!r}. valid: {sorted(VALID_STATUSES)}",
        )
    priority_dict = req.priority.model_dump() if req.priority else DEFAULT_PRIORITY
    initiative_err = validate_initiative_ref(cp, req.initiative_id)
    if initiative_err:
        return initiative_err
    from .label import normalize_label_ids
    label_ids, label_err = normalize_label_ids(cp, req.labels)
    if label_err:
        return label_err
    issue_id, seq = new_entity_id(cp.cell_id, "issue")
    record = {
        "issue_id": issue_id,
        "seq": seq,
        "title": req.title,
        "description": req.description,
        "plan": req.plan,
        "owner": owner,
        "project_id": req.project_id,
        "initiative_id": req.initiative_id,
        "status": initial_status,
        "cell_id": cp.cell_id,
        "dependencies": req.dependencies or [],
        "capability": req.capability or [],
        "model": req.model,
        "priority": priority_dict,
        "priority_score": compute_priority_score(priority_dict),
        "resources": resources,
        "gates": req.gates.model_dump() if req.gates else None,
        "source_signal_ids": req.source_signal_ids or [],
        "labels": label_ids or [],
        "metadata": req.metadata or {},
        "hold": bool(req.hold),
        "created_at": now,
        "updated_at": now,
    }
    append_jsonl(cp.issue_file, record)
    # seq 는 issue_id 발급 시 entity_seq 에서 함께 받아 record 에 이미 포함.
    # push 알림:
    #   - 부모 project worker: 자식 생성 즉시 부모 cycle 재개
    #   - cell agent-loop: 새 actionable 등장 → 즉시 spawn (polling 우회)
    from .. import wake_bus
    if record.get("project_id"):
        wake_bus.notify(record["project_id"])
    wake_bus.notify(f"cell:{cp.cell_id}")
    return CapabilityResponse(status="ok", data=record)


def _filter_sort_paginate(issues, req, request, *, projects_by_id):
    """issue.list / issue.list_all 공유 — 동일 필터·정렬·페이지네이션.

    두 핸들러의 유일한 차이는 소스(단일 cell vs 전 cell 머지)와 페이지 backfill 뿐이라,
    그 사이 로직을 여기로 모아 drift(필터 누락 비대칭 등)를 막는다. effective initiative
    필터가 projects_by_id 를 쓰므로 인자로 받는다(list 는 단일 cell map, list_all 은 필터
    활성 시에만 cross-cell 적재). 반환 (page, total, next_cursor).
    """
    if req.project_id:
        issues = [t for t in issues if t.get("project_id") == req.project_id]
    if req.standalone is True:
        issues = [t for t in issues if not t.get("project_id")]
    elif req.standalone is False:
        issues = [t for t in issues if t.get("project_id")]
    if req.initiative_id != "__all__":
        issues = [t for t in issues if _effective_initiative_id(t, projects_by_id) == req.initiative_id]
    if req.status:
        issues = [t for t in issues if t["status"] == req.status]
    elif req.statuses:
        allowed = set(req.statuses)
        issues = [t for t in issues if t["status"] in allowed]
    if req.hold is not None:
        issues = [t for t in issues if bool(t.get("hold")) == req.hold]
    owner_filter = resolve_me_alias(req.owner, request)
    if owner_filter:
        issues = [t for t in issues if t.get("owner") == owner_filter]
    if req.q:
        needle = req.q.strip().lower()
        if needle:
            issues = [
                t for t in issues
                if needle in (t.get("title") or "").lower()
                or needle in (t.get("issue_id") or "").lower()
            ]
    if req.activity_since:
        issues = [t for t in issues if _effective_activity(t) >= req.activity_since]
    total = len(issues)
    if req.activity_since:
        issues.sort(key=_effective_activity, reverse=(req.sort_order == "desc"))
    else:
        issues.sort(
            key=lambda t: t.get(req.sort_by) or "",
            reverse=(req.sort_order == "desc"),
        )
    offset = resolve_offset(req.cursor, req.offset)
    page, next_cursor = offset_page(issues, offset=offset, limit=req.limit)
    return page, total, next_cursor


@router.post("/issue.list")
def issue_list(req: IssueListRequest, request: Request) -> CapabilityResponse:
    """Issue 목록 조회. project_id·status로 필터링. cursor 또는 offset 페이지네이션."""
    cp = get_cell_paths(request)
    issues = read_entity_file(cp.issue_file)  # deleted 는 storage 계층에서 이미 제외
    projects = read_entity_file(cp.project_file)
    projects_by_id = {p["project_id"]: p for p in projects}
    page, total, next_cursor = _filter_sort_paginate(issues, req, request, projects_by_id=projects_by_id)
    for t in page:
        t["resolved_owner"] = resolve_owner(t, "issue", projects=projects, project_file=cp.project_file)
        _ensure_initiative_id(t)
    view.attach_read_state(page, id_field="issue_id", entity_type="issue", request=request)
    return CapabilityResponse(status="ok", data={
        "issues": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/issue.list_all")
def issue_list_all(req: IssueListRequest, request: Request) -> CapabilityResponse:
    """User-scoped aggregate. 호출자가 접근 가능한 모든 cell 의 issue 를 머지.

    응답 envelope·필터·페이지네이션 의미론은 issue.list 와 동일. record 의 cell_id
    필드가 보존돼 UI 는 그 값으로 cell 뱃지·라우팅 결정.
    resolved_owner backfill 은 페이지 슬라이스 한정 — 항목 cell 의 project_file 만
    lazy 로드해 cross-cell 누설·중복 I/O 회피.
    """
    cell_ids = accessible_cell_ids(request)
    issues: list[dict] = []
    for cid in cell_ids:
        cp = CellPaths(cid)
        issues.extend(read_entity_file(cp.issue_file))  # deleted 는 storage 계층에서 이미 제외
    # effective initiative 필터만 projects_by_id 가 필요. 흔치 않은 경로라 필터 활성일
    # 때만 cross-cell project map 적재(없으면 helper 가 필터를 건너뜀). initiative id 는
    # cell-prefix 라 충돌 없음.
    projects_by_id: dict[str, dict] = {}
    if req.initiative_id != "__all__":
        for cid in cell_ids:
            for p in read_entity_file(CellPaths(cid).project_file):
                projects_by_id[p["project_id"]] = p
    page, total, next_cursor = _filter_sort_paginate(issues, req, request, projects_by_id=projects_by_id)
    cell_projects_cache: dict[str, list[dict]] = {}
    for t in page:
        _ensure_initiative_id(t)
        tcell = t.get("cell_id")
        if not tcell:
            continue
        if tcell not in cell_projects_cache:
            cell_projects_cache[tcell] = read_entity_file(CellPaths(tcell).project_file)
        cp_t = CellPaths(tcell)
        t["resolved_owner"] = resolve_owner(
            t, "issue", projects=cell_projects_cache[tcell], project_file=cp_t.project_file,
        )
    view.attach_read_state(page, id_field="issue_id", entity_type="issue", request=request)
    return CapabilityResponse(status="ok", data={
        "issues": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/issue.get")
def issue_get(req: IssueGetRequest, request: Request) -> CapabilityResponse:
    """단일 Issue 상세 조회."""
    cp = get_cell_paths(request)
    _, found = find_entity(cp.issue_file, "issue_id", req.issue_id)
    if not found:
        return CapabilityResponse(status="error", error_code="not_found", message=f"issue {req.issue_id} not found")
    found["resolved_owner"] = resolve_owner(found, "issue", project_file=cp.project_file)
    _ensure_initiative_id(found)
    projects_by_id = {p["project_id"]: p for p in read_entity_file(cp.project_file)}
    _ensure_initiative_summary(found, cp=cp, projects_by_id=projects_by_id)
    found["artifacts"] = scan_artifacts(cp.cell_id, "issue", req.issue_id)
    found["deployments"] = scan_deployments(cp.cell_id, issue_branch=f"issue/{req.issue_id}")
    return CapabilityResponse(status="ok", data=found)


class IssueDeleteRequest(BaseModel):
    issue_id: str


@router.post("/issue.delete")
async def issue_delete(req: IssueDeleteRequest, request: Request) -> CapabilityResponse:
    """Issue 소프트 삭제."""
    cp = get_cell_paths(request)

    def _mutate(found):
        if found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="already_deleted",
                message=f"issue {req.issue_id} is already deleted",
            )
        now = datetime.now(timezone.utc).isoformat()
        found["deleted"] = True
        found["deleted_at"] = now
        found["updated_at"] = now

    res = cas_entity(cp, "issue", req.issue_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"issue {req.issue_id} not found")
    if isinstance(res, CapabilityResponse):
        return res
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event("issue", req.issue_id, "deleted", {}, event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data=res)


class IssueRestoreRequest(BaseModel):
    issue_id: str


@router.post("/issue.restore")
async def issue_restore(req: IssueRestoreRequest, request: Request) -> CapabilityResponse:
    """삭제된 Issue 복원."""
    cp = get_cell_paths(request)

    def _mutate(found):
        if not found.get("deleted"):
            return CapabilityResponse(
                status="error", error_code="not_deleted",
                message=f"issue {req.issue_id} is not deleted",
            )
        found.pop("deleted", None)
        found.pop("deleted_at", None)
        found["updated_at"] = datetime.now(timezone.utc).isoformat()

    res = cas_entity(cp, "issue", req.issue_id, _mutate)
    if res is None:
        return CapabilityResponse(status="error", error_code="not_found", message=f"issue {req.issue_id} not found")
    if isinstance(res, CapabilityResponse):
        return res
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    emit_event("issue", req.issue_id, "restored", {}, event_dir=cp.event_dir, session_id=sid, principal=principal)
    return CapabilityResponse(status="ok", data=res)


@router.post("/issue.update")
async def issue_update(req: IssueUpdateRequest, request: Request) -> CapabilityResponse:
    """Issue 상태 전이 및 필드 수정.

    종결 전이 가드만 강제 (project_issue_model.md §2): done·cancelled 모두
    cleanup 에서만 (그 외 상태에서 직접 종결 거부). 그 외 전이 graph·
    description/model/comment/replies 검증은 spec 으로 위임 (AI 책임). 가드
    우회는 ``issue.force_update``.
    """
    cp = get_cell_paths(request)
    if req.owner == "me":
        req.owner = resolve_me_alias(req.owner, request)
    # preview_review 가드는 meta 로 동기 blocking HTTP(urlopen)를 친다 — flock 보유
    # 중 실행하면 그 네트워크 왕복 동안 이벤트 루프가 멈춘다(INFRA-ISSUE-277). 가드는
    # 엔티티 상태가 아니라 req 만 보므로 flock 밖에서 먼저 친다.
    guard = _preview_review_guard(req, cp)
    if guard:
        return guard
    with entity_lock(cp.issue_file):
        return apply_entity_fields_and_persist(
            req=req, request=request, cp=cp, entity_type="issue",
            validate_status=_issue_validate_status,
        )


@router.post("/issue.save")
async def issue_save(req: IssueSaveRequest, request: Request) -> CapabilityResponse:
    """Linear ``save_issue`` 패턴 — ``issue_id`` 유무로 create/update 디스패치.

    내부적으로 ``issue.create`` / ``issue.update`` 그대로 호출 — 동작/검증/event/inbox
    /signal 처리 100% 일치. 새 호출자 (MCP/LLM) 는 한 툴로 모든 issue mutation 수행 가능.
    기존 호출자 (worker python, UI) 는 ``issue.create``/``issue.update`` 계속 사용 — 둘 다 alias.
    """
    if req.issue_id:
        upd = IssueUpdateRequest(
            issue_id=req.issue_id,
            status=req.status,
            comment=req.comment,
            comment_subtype=req.comment_subtype,
            comment_payload=req.comment_payload,
            title=req.title,
            description=req.description,
            plan=req.plan,
            owner=req.owner,
            capability=req.capability,
            model=req.model,
            priority=req.priority,
            clear_priority=req.clear_priority,
            resources=req.resources,
            gates=req.gates,
            metadata=req.metadata,
            source_signal_ids=req.source_signal_ids,
            labels=req.labels,
            dependencies=req.dependencies,
            remove_dependencies=req.remove_dependencies,
            hold=req.hold,
            initiative_id=req.initiative_id,
        )
        return await issue_update(upd, request)
    if not (req.title or "").strip():
        return CapabilityResponse(
            status="error", error_code="title_required",
            message="title is required when creating a issue (no issue_id provided).",
        )
    create = IssueCreateRequest(
        title=req.title,
        project_id=req.project_id,
        description=req.description,
        plan=req.plan,
        owner=req.owner,
        dependencies=req.dependencies,
        capability=req.capability,
        model=req.model,
        priority=req.priority,
        resources=req.resources,
        gates=req.gates,
        metadata=req.metadata,
        source_signal_ids=req.source_signal_ids,
        labels=req.labels,
        status=req.status,
        hold=bool(req.hold),
        initiative_id=req.initiative_id,
    )
    return await issue_create(create, request)


@router.post("/issue.force_update")
async def issue_force_update(req: IssueUpdateRequest, request: Request) -> CapabilityResponse:
    """issue.update 와 동일 본문이되 종결 전이 가드를 우회.

    error 복구·운영자 콘솔 강제 전이 등 가드 우회 경로용으로 endpoint 를 유지.
    """
    cp = get_cell_paths(request)
    if req.owner == "me":
        req.owner = resolve_me_alias(req.owner, request)
    with entity_lock(cp.issue_file):
        return apply_entity_fields_and_persist(
            req=req, request=request, cp=cp, entity_type="issue",
            validate_status=_issue_validate_status, enforce_guard=False,
        )


def _preview_review_guard(req: IssueUpdateRequest, cp) -> CapabilityResponse | None:
    """preview_review 핸드오프(=`waiting` 전이) 시 미리보기 배포가 실제로 Ready 인지 강제.

    워커가 미리보기 헬스체크(gitops_app_spec §6.5 step-1)를 건너뛰고 깨진
    preview 를 사람 리뷰로 넘기는 것을 hub 가 코드로 막는다. ``preview_review``
    핸드오프에만 발동 — 다른 전이엔 영향 0. 차단이면 CapabilityResponse(error),
    통과면 None. meta 미응답은 fail-open(판정불가로 막지 않음). 강제 진행은
    ``issue.force_update`` (enforce_guard=False 라 이 가드 자체를 안 탄다).
    """
    if req.status != "waiting" or req.comment_subtype != "handoff":
        return None
    if (req.comment_payload or {}).get("reason") != "preview_review":
        return None
    state, matched = preview_readiness(cp.cell_id, f"issue/{req.issue_id}")
    if state in ("ready", "meta_unreachable"):
        return None
    if state == "not_ready":
        phases = ", ".join(f"{d['app']}/{d['env']}={d['phase'] or '?'}" for d in matched)
        msg = (
            f"미리보기가 아직 Ready 아닙니다 (phase: {phases}). 배포 완료까지 폴링 "
            "대기 후 lab 200 을 확인하고 preview_review 핸드오프하세요 "
            "(gitops_app_spec §6.5 step-1). 강제 진행은 issue.force_update."
        )
    else:  # absent
        msg = (
            "미리보기 배포가 아직 없습니다 (meta App 미생성). meta-sync 빌드가 "
            "실패했거나 아직 끝나지 않았을 수 있습니다 — Gitea Actions meta-sync "
            "job 로그로 빌드를 확인·수정하고 다시 push 한 뒤, lab 200 / meta App "
            "Ready 를 확인하고 preview_review 핸드오프하세요 (gitops_app_spec "
            "§6.5 step-1). 강제 진행은 issue.force_update."
        )
    return CapabilityResponse(status="error", error_code="preview_not_ready", message=msg)


def _issue_validate_status(old_status, new_status, req, found, enforce_guard) -> CapabilityResponse | None:
    """issue status 전이 검증 — apply_entity_fields_and_persist 의 CAS 루프 안에서 fresh
    entity 기준으로 매 시도 재실행된다. invalid_status 는 항상, 종결 전이 가드는 enforce_guard 만.
    """
    if new_status not in VALID_STATUSES:
        return CapabilityResponse(status="error", error_code="invalid_status", message=f"invalid status: {new_status}")
    if enforce_guard:
        denied = terminal_transition_denied(old_status, new_status)
        if denied:
            return CapabilityResponse(status="error", error_code="transition_denied", message=denied)
    return None


# ── session 영구화 + PR 누적 ──

class TaskSetSessionRequest(BaseModel):
    issue_id: str
    session_id: str | None = None
    last_prompt_at: str | None = None  # 마지막 prompt 빌드 시각 (ISO8601). 재진입 워커가
                                       # delta 컨텍스트 만 주입하도록 cursor 로 사용.


@router.post("/issue.set_session")
async def issue_set_session(req: TaskSetSessionRequest, request: Request) -> CapabilityResponse:
    return entity_set_session(
        cp=get_cell_paths(request), entity_type="issue", entity_id=req.issue_id,
        session_id=req.session_id, last_prompt_at=req.last_prompt_at,
    )


class TaskAddPrRequest(BaseModel):
    issue_id: str
    pr: dict  # url, repo, pr_number, head_branch, base, role, reported_at
              # merge_state 는 폐기 — UI 가 pr.status capability 로 derive-on-read


@router.post("/issue.add_pr")
async def issue_add_pr(req: TaskAddPrRequest, request: Request) -> CapabilityResponse:
    return entity_add_pr(cp=get_cell_paths(request), entity_type="issue", entity_id=req.issue_id, pr=req.pr)


