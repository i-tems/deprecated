"""Inbox — 사람 확인용 알림 피드. Issue/Project 완료 시 자동 발행 + skill/AI 가 인사이트 적재."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse
from ..config import INBOX_DIR, get_cell_paths, accessible_cell_ids
from ..events import emit_inbox
from ..helpers import read_jsonl, write_jsonl, find_by_id, date_range_paths, all_partition_paths, entity_lock

router = APIRouter()


class InboxListRequest(BaseModel):
    status: str | None = None  # unread | read
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 50


class InboxAckRequest(BaseModel):
    inbox_id: str


class InboxAddRequest(BaseModel):
    type: str  # 'insight.observed' | 'consulting.note' 등. TYPE_META 미매칭 시 UI fallback.
    summary: str  # 한 줄 punch line (피드 행에 노출).
    body: str | None = None  # 옵션 markdown 본문 (상세 확장 시 표시).
    ref: str | None = None  # 옵션 관련 entity_id (e.g. ITEMS-SIGNAL-42, ITEMS-PROJECT-2).
    owner: str | None = None  # 옵션 owner. 미지정 시 호출자 cell default.


@router.post("/inbox.list")
def inbox_list(req: InboxListRequest, request: Request) -> CapabilityResponse:
    """Inbox 목록 조회. status·날짜·cell로 필터링."""
    cp = get_cell_paths(request)
    paths = date_range_paths(INBOX_DIR, req.date_from, req.date_to)
    items = []
    for p in paths:
        items.extend(read_jsonl(p))
    # Cell 필터: cell_id가 현재 Cell이거나 미지정(레거시)인 항목만
    items = [i for i in items if i.get("cell_id") in (cp.cell_id, None)]
    if req.status:
        items = [i for i in items if i.get("status") == req.status]
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = items[:req.limit]
    return CapabilityResponse(status="ok", data={"items": items, "count": len(items)})


@router.post("/inbox.list_all")
def inbox_list_all(req: InboxListRequest, request: Request) -> CapabilityResponse:
    """User-scoped aggregate. 호출자가 접근 가능한 모든 cell 의 inbox 를 머지.

    응답 항목에 cell_id 가 명시되며, UI 는 이 값으로 cell 뱃지·라우팅을 결정한다.
    cell_id 가 없는 레거시 레코드는 어느 cell 권한으로 노출할지 판정 불가라 제외.
    """
    allowed = set(accessible_cell_ids(request))
    paths = date_range_paths(INBOX_DIR, req.date_from, req.date_to)
    items = []
    for p in paths:
        items.extend(read_jsonl(p))
    items = [i for i in items if i.get("cell_id") in allowed]
    if req.status:
        items = [i for i in items if i.get("status") == req.status]
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items = items[:req.limit]
    return CapabilityResponse(status="ok", data={"items": items, "count": len(items)})


@router.post("/inbox.ack")
async def inbox_ack(req: InboxAckRequest, request: Request) -> CapabilityResponse:
    """단일 inbox 항목의 read/unread를 토글."""
    with entity_lock(INBOX_DIR):
        path, entries, found = find_by_id(INBOX_DIR, "inbox_id", req.inbox_id)
        if not found:
            return CapabilityResponse(
                status="error", error_code="not_found",
                message=f"inbox item {req.inbox_id} not found",
            )
        found["status"] = "unread" if found["status"] == "read" else "read"
        write_jsonl(path, entries)
    return CapabilityResponse(status="ok", data=found)


@router.post("/inbox.add")
async def inbox_add(req: InboxAddRequest, request: Request) -> CapabilityResponse:
    """Skill/AI 가 사람 확인용 인사이트·노트를 적재. cell-scoped. Slack mirror 자동."""
    cp = get_cell_paths(request)
    record = emit_inbox(
        req.type,
        req.ref or "",
        req.summary,
        cell_id=cp.cell_id,
        owner=req.owner,
        body=req.body,
    )
    return CapabilityResponse(status="ok", data=record)


@router.post("/inbox.ack_all")
async def inbox_ack_all(request: Request) -> CapabilityResponse:
    """모든 unread inbox 항목을 read로 일괄 전환. 날짜 무관 전수 스캔."""
    with entity_lock(INBOX_DIR):
        paths = all_partition_paths(INBOX_DIR)
        total = 0
        for p in paths:
            entries = read_jsonl(p)
            modified = False
            for e in entries:
                if e.get("status") == "unread":
                    e["status"] = "read"
                    modified = True
                    total += 1
            if modified:
                write_jsonl(p, entries)
    return CapabilityResponse(status="ok", data={"acked": total})
