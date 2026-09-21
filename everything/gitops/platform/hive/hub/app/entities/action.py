from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse
from ..config import ACTION_DIR, get_cell_paths
from ..helpers import read_jsonl, date_range_paths, find_by_id

router = APIRouter()


class ActionListRequest(BaseModel):
    capability_id: str | None = None
    status: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 50


class ActionGetRequest(BaseModel):
    action_id: str


@router.post("/action.list")
def action_list(req: ActionListRequest, request: Request) -> CapabilityResponse:
    """Action 실행 로그 조회. 호출자의 X-Cell-Id 셀로만 필터링한다."""
    cp = get_cell_paths(request)
    paths = date_range_paths(ACTION_DIR, req.date_from, req.date_to)
    actions = []
    for p in paths:
        actions.extend(read_jsonl(p))
    actions = [a for a in actions if a.get("cell_id") == cp.cell_id]
    if req.capability_id:
        actions = [a for a in actions if a.get("capability_id") == req.capability_id]
    if req.status:
        actions = [a for a in actions if a.get("status") == req.status]
    actions = actions[-req.limit:]
    return CapabilityResponse(status="ok", data={"actions": actions, "count": len(actions)})


@router.post("/action.get")
def action_get(req: ActionGetRequest, request: Request) -> CapabilityResponse:
    """단일 Action 로그 상세 조회. 호출자 셀과 일치하는 경우만 반환."""
    cp = get_cell_paths(request)
    _, _, found = find_by_id(ACTION_DIR, "action_id", req.action_id)
    if not found or found.get("cell_id") != cp.cell_id:
        return CapabilityResponse(status="error", error_code="not_found", message=f"action {req.action_id} not found")
    return CapabilityResponse(status="ok", data=found)
