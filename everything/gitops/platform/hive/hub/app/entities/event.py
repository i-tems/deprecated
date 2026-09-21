"""Activity Feed — 엔티티별 이벤트 피드."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse
from ..config import get_cell_paths
from ..cursor import offset_page, resolve_offset
from ..helpers import read_jsonl, iter_partitions_for_query, emit_event

router = APIRouter()


# comment 내부 의도 분류. status_change/field_change 같은 자동 이벤트와 별개로,
# comment 이벤트 내부에서 "왜 작성했나"를 schema로 강제한다.
#   discussion — 자유 토론·일반 코멘트 (기본)
#   progress   — 같은 상태 내 진척 보고
#   transition — 상태 전이 사유 (status_change와 페어로 작성, "왜 옮겼나")
#   handoff    — waiting/review 진입 핸드오프 (payload: pr_url, summary 권장)
#   halt       — 실패·중단 (payload: reason, recovery_options 권장)
CommentSubtype = Literal["discussion", "progress", "transition", "handoff", "halt"]


class EventListRequest(BaseModel):
    entity_type: str = Field(description='"project" | "issue" | "initiative".')
    entity_id: str
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 200
    offset: int = 0
    cursor: str | None = Field(
        default=None,
        description='이전 응답의 next_cursor. 제공되면 offset 무시. 미지정 시 기존처럼 tail (최근 limit 개) 반환.',
    )


class EventAddRequest(BaseModel):
    entity_type: str = Field(description='"project" | "issue" | "initiative".')
    entity_id: str
    text: str
    parent_event_id: str | None = Field(
        default=None,
        description='comment 답글이면 parent comment 의 event_id.',
    )
    subtype: CommentSubtype = Field(
        default="discussion",
        description='discussion=일반토론(기본) | progress=같은상태내진척 | transition=상태전이사유 | handoff=핸드오프 (payload: pr_url, summary 권장) | halt=실패중단 (payload: reason, recovery_options 권장).',
    )
    payload: dict = Field(
        default={},
        description='subtype 별 structured 필드 (freeform, 강제 X). handoff/halt 에 options: [{label, key?, tone?, action: {type:"transition", status, comment?} | {type:"reply", text, subtype?}}] 추가 시 ActivityFeed 원본 코멘트에 인라인 원클릭 버튼 렌더 (handoff_patterns 정본).',
    )


class EventUpdateCommentRequest(BaseModel):
    entity_type: str
    entity_id: str
    target_event_id: str       # 수정할 comment event_id
    text: str | None = None    # None이면 텍스트 변경 없음
    subtype: CommentSubtype | None = Field(
        default=None,
        description='discussion | progress | transition | handoff | halt. None=변경없음.',
    )
    payload: dict | None = None            # None이면 payload 변경 없음


class EventDeleteCommentRequest(BaseModel):
    entity_type: str
    entity_id: str
    target_event_id: str       # 삭제할 comment event_id


def _principal_key(record: dict) -> tuple[str | None, str | None]:
    """본인 확인용 principal_id/type 튜플."""
    return (record.get("principal_id"), record.get("principal_type"))


@router.post("/event.list")
def event_list(req: EventListRequest, request: Request) -> CapabilityResponse:
    """엔티티의 활동 이벤트를 시간순으로 반환.

    comment_edit / comment_delete 이벤트는 read 시점에 원본 comment에 머지되어
    feed 응답에서는 노출되지 않는다. 본인 principal이 만든 mutation만 적용된다.
    """
    cp = get_cell_paths(request)

    event_paths = iter_partitions_for_query(
        cp.event_dir, req.date_from, req.date_to, entity_scoped=True
    )
    raw_events = []
    for p in event_paths:
        raw_events.extend(read_jsonl(p))
    raw_events = [
        e for e in raw_events
        if e.get("entity_type") == req.entity_type and e.get("entity_id") == req.entity_id
    ]

    # 1. comment 이벤트 매핑 + edit/delete 적용
    comment_index: dict[str, dict] = {
        e["event_id"]: e for e in raw_events if e.get("type") == "comment"
    }

    for e in sorted(raw_events, key=lambda x: x.get("ts", "")):
        etype = e.get("type")
        if etype not in ("comment_edit", "comment_delete"):
            continue
        target_id = (e.get("data") or {}).get("target_event_id")
        if not target_id or target_id not in comment_index:
            continue
        origin = comment_index[target_id]
        if _principal_key(origin) != _principal_key(e):
            continue  # 권한 없음 — defensive (write에서도 막힘)
        if etype == "comment_edit":
            edit_data = e.get("data") or {}
            origin_data = origin.setdefault("data", {})
            if "text" in edit_data:
                origin_data["text"] = edit_data["text"]
            if "subtype" in edit_data:
                origin_data["subtype"] = edit_data["subtype"]
            if "payload" in edit_data:
                origin_data["payload"] = edit_data["payload"]
            origin["edited_at"] = e.get("ts")
        else:  # comment_delete
            origin["deleted"] = True

    # 2. feed 빌드 (mutation 이벤트는 제외, 삭제된 comment는 placeholder)
    feed = []
    for e in raw_events:
        etype = e.get("type")
        if etype in ("comment_edit", "comment_delete"):
            continue
        if etype == "comment" and e.get("deleted"):
            # 삭제된 comment는 답글이 없으면 숨기고, 있으면 자리표시자 유지.
            # 단순화를 위해 우선 숨김 — 나중에 필요시 placeholder 도입.
            continue
        item = {
            "kind": etype,
            "ts": e["ts"],
            "data": e.get("data", {}),
            "event_id": e["event_id"],
        }
        if e.get("session_id"):
            item["session_id"] = e["session_id"]
        if e.get("principal_id"):
            item["principal_id"] = e["principal_id"]
        if e.get("principal_type"):
            item["principal_type"] = e["principal_type"]
        if e.get("edited_at"):
            item["edited_at"] = e["edited_at"]
        feed.append(item)

    # 3. 시간순 정렬 + 페이지네이션
    feed.sort(key=lambda x: x["ts"])
    total = len(feed)
    # 호환 유지: cursor/offset 미지정 시 기존처럼 tail (최근 limit 개) 반환.
    if req.cursor or req.offset:
        offset = resolve_offset(req.cursor, req.offset)
        page, next_cursor = offset_page(feed, offset=offset, limit=req.limit)
    else:
        page = feed[-req.limit:]
        next_cursor = None

    return CapabilityResponse(status="ok", data={
        "feed": page,
        "count": len(page),
        "total": total,
        "next_cursor": next_cursor,
    })


@router.post("/event.add")
async def event_add(req: EventAddRequest, request: Request) -> CapabilityResponse:
    """코멘트 이벤트를 추가. parent_event_id가 있으면 답글.

    subtype은 comment 내부 의도 분류 (discussion/progress/transition/handoff/halt).
    payload는 subtype별 권장 structured 필드 — freeform, 강제 X.

    event 적재 후 해당 entity 의 pending user comment chain head event_id 들을
    entity record 의 `pending_user_comment_event_ids` 필드에 갱신 (한 entity 만
    events 재계산 — N+1 회피). pending 있음 + user actor 면 cell wake 발사하되,
    오직 replyable status(컨테이너 `waiting`)만 — issue 와 terminal(done/cancelled/
    archive)은 wake·픽업 안 함 (INFRA-ISSUE-263, `_replyable_statuses` 참조).
    """
    cp = get_cell_paths(request)
    sid = getattr(request.state, "session_id", None)
    principal = getattr(request.state, "principal", None)
    data: dict = {"text": req.text, "subtype": req.subtype}
    if req.parent_event_id:
        data["parent_event_id"] = req.parent_event_id
    if req.payload:
        data["payload"] = req.payload
    record = emit_event(
        req.entity_type, req.entity_id, "comment", data,
        event_dir=cp.event_dir, session_id=sid, principal=principal,
    )

    if req.entity_type in ("issue", "project", "initiative"):
        _recompute_pending_and_wake(cp, req.entity_type, req.entity_id, principal)

    return CapabilityResponse(status="ok", data=record)


def _recompute_pending_and_wake(cp, entity_type: str, entity_id: str, principal) -> None:
    """한 entity 의 pending user comment 재계산 + record flag 갱신 + 필요 시 cell wake.

    cost = 한 entity 의 events 1회 read (N+1 X — 모든 entity 가 아니라 *방금 comment
    이 도착한* entity 만).
    """
    events = list_entity_events(cp, entity_type, entity_id)
    heads = find_pending_user_comments(events)
    head_ids = [h.get("event_id") for h in heads if h.get("event_id")]

    # 단일 entity 의 pending 필드만 per-entity CAS 로 갱신 (INFRA-ISSUE-319).
    # 옛 경로는 entity_lock + write_entity_file(셀 전체 재기록)이라, 다른 replica 가 같은
    # 셀의 *형제* 엔티티를 CAS 로 쓴 것을 stale 스냅샷으로 덮어 lost-update 가 났다 (in-pod
    # entity_lock 은 cross-pod 직렬화를 못 한다). cas_entity 는 대상 행만 rev-guard UPDATE 해
    # 형제 쓰기와 충돌하지 않는다.
    from . import cas_entity  # 지역 import — entities __init__ 과의 순환 회피

    box: dict = {}

    def _set_pending(found):
        box["status"] = found.get("status")
        old = list(found.get("pending_user_comment_event_ids") or [])
        if head_ids == old:
            return CapabilityResponse(status="ok", data=None)  # 변경 없음 — 쓰기·rev bump 생략
        found["pending_user_comment_event_ids"] = head_ids
        return None

    res = cas_entity(cp, entity_type, entity_id, _set_pending)
    if res is None:
        return  # entity 행 없음

    # wake 대상 status + pending 있음 + user actor → cell wake (즉시 픽업 cycle).
    # 컨테이너 waiting 만 — parked 라 새 사용자 댓글이 오면 깨워 reply 시킨다. issue 와
    # terminal 은 wake 안 함 (`_replyable_statuses` 참조: waiting issue 는 poll 경로,
    # terminal 은 INFRA-ISSUE-263 이후 미픽업).
    replyable = _replyable_statuses(entity_type)
    if (
        head_ids
        and box.get("status") in replyable
        and principal is not None
        and getattr(principal, "type", None) == "user"
    ):
        from .. import wake_bus
        wake_bus.notify(f"cell:{cp.cell_id}")


def list_entity_events(cp, entity_type: str, entity_id: str) -> list[dict]:
    """엔티티의 모든 raw events 시간순. server side helper (event_list 응답 변환 전)."""
    events: list[dict] = []
    for p in iter_partitions_for_query(cp.event_dir, None, None, entity_scoped=True):
        events.extend(read_jsonl(p))
    events = [
        e for e in events
        if e.get("entity_type") == entity_type and e.get("entity_id") == entity_id
    ]
    events.sort(key=lambda e: e.get("ts") or "")
    return events


def find_pending_user_comments(events: list[dict]) -> list[dict]:
    """raw events 에서 AI/worker reply 가 매칭되지 않은 user comment chain head 반환.

    work_finder.py 의 `_find_pending_user_comments` 와 동일 logic (raw events 의
    `type` 필드 사용). 자기-reply 는 부모 replied 로 마킹 안 함 (ITEMS-ISSUE-15 회귀).

    삭제된 comment(`comment_delete` 대상)는 없는 것으로 본다 — user comment 로도,
    reply 로도 집계 제외. raw events 에는 원본 comment 이벤트가 그대로 남아 있어
    (delete 마커는 `event.list` 응답 빌드 때만 in-memory 적용) 여기서 직접 걸러내야
    삭제 후 pending 에 재적재되지 않는다 (INFRA-ISSUE-213).
    """
    deleted_ids = {
        (e.get("data") or {}).get("target_event_id")
        for e in events
        if e.get("type") == "comment_delete"
    }
    deleted_ids.discard(None)
    user_comments = [
        e for e in events
        if e.get("type") == "comment" and e.get("principal_type") == "user"
        and e.get("event_id") not in deleted_ids
    ]
    replied_to: set[str] = set()
    for e in events:
        if e.get("type") != "comment":
            continue
        if e.get("principal_type") == "user":
            continue
        if e.get("event_id") in deleted_ids:
            continue
        pid = (e.get("data") or {}).get("parent_event_id")
        if pid:
            replied_to.add(pid)
    pending_ids = {
        c.get("event_id") for c in user_comments
        if c.get("event_id") and c.get("event_id") not in replied_to
    }
    by_event = {
        e.get("event_id"): e for e in events
        if e.get("type") == "comment" and e.get("event_id")
        and e.get("event_id") not in deleted_ids
    }

    def _has_pending_ancestor(c: dict) -> bool:
        pid = (c.get("data") or {}).get("parent_event_id")
        while pid:
            if pid in pending_ids:
                return True
            parent = by_event.get(pid)
            if not parent:
                break
            pid = (parent.get("data") or {}).get("parent_event_id")
        return False

    heads = [
        c for c in user_comments
        if c.get("event_id") in pending_ids and not _has_pending_ancestor(c)
    ]
    heads.sort(key=lambda c: c.get("ts") or "")
    return heads


def _replyable_statuses(entity_type: str) -> set[str]:
    """새 user comment 가 와서 cell-wake(즉시 픽업 cycle)할 가치가 있는 status 집합.

    work_finder 가 실제로 reply 픽업하는 status 와 일치해야 한다 (불일치 시 wake 가
    빈 cycle 만 깨운다):
    - container(project/initiative): waiting 만. parked 상태라 새 댓글이 오면 깨워
      reply 시킨다.
    - issue: 없음. waiting issue 는 8-status 워커 모델의 _PICKUP_STATES poll 경로가
      처리하므로 event-driven wake 가 불필요.

    terminal(done/cancelled·done/archive)은 INFRA-ISSUE-263 이후 자동 픽업 대상이
    아니므로 wake 대상에서도 빠진다 (terminal+pending reply 무한 재dispatch 차단).
    """
    if entity_type == "issue":
        return set()
    return {"waiting"}


def _find_comment(cp, entity_type: str, entity_id: str, event_id: str) -> dict | None:
    """전 파티션에서 entity 범위의 comment event를 찾는다."""
    for p in iter_partitions_for_query(cp.event_dir, None, None, entity_scoped=True):
        for rec in read_jsonl(p):
            if (
                rec.get("event_id") == event_id
                and rec.get("type") == "comment"
                and rec.get("entity_type") == entity_type
                and rec.get("entity_id") == entity_id
            ):
                return rec
    return None


@router.post("/event.update_comment")
async def event_update_comment(req: EventUpdateCommentRequest, request: Request) -> CapabilityResponse:
    """본인이 작성한 comment를 수정. comment_edit 이벤트로 append.

    text / subtype / payload 중 제공된 필드만 변경된다 (None은 변경 없음).
    셋 다 None이면 no-op으로 거절.
    """
    if req.text is None and req.subtype is None and req.payload is None:
        return CapabilityResponse(
            status="error", error_code="invalid_request",
            message="text·subtype·payload 중 최소 1개는 제공해야 합니다",
        )
    cp = get_cell_paths(request)
    principal = getattr(request.state, "principal", None)
    origin = _find_comment(cp, req.entity_type, req.entity_id, req.target_event_id)
    if not origin:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"comment {req.target_event_id} not found",
        )
    if not principal or origin.get("principal_id") != principal.id or origin.get("principal_type") != principal.type:
        return CapabilityResponse(
            status="error", error_code="forbidden",
            message="자신이 작성한 comment만 수정할 수 있습니다",
        )
    sid = getattr(request.state, "session_id", None)
    edit_data: dict = {"target_event_id": req.target_event_id}
    if req.text is not None:
        edit_data["text"] = req.text
    if req.subtype is not None:
        edit_data["subtype"] = req.subtype
    if req.payload is not None:
        edit_data["payload"] = req.payload
    record = emit_event(
        req.entity_type, req.entity_id, "comment_edit",
        edit_data,
        event_dir=cp.event_dir, session_id=sid, principal=principal,
    )
    return CapabilityResponse(status="ok", data=record)


@router.post("/event.delete_comment")
async def event_delete_comment(req: EventDeleteCommentRequest, request: Request) -> CapabilityResponse:
    """본인이 작성한 comment를 삭제. comment_delete 이벤트로 append (soft delete)."""
    cp = get_cell_paths(request)
    principal = getattr(request.state, "principal", None)
    origin = _find_comment(cp, req.entity_type, req.entity_id, req.target_event_id)
    if not origin:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"comment {req.target_event_id} not found",
        )
    if not principal or origin.get("principal_id") != principal.id or origin.get("principal_type") != principal.type:
        return CapabilityResponse(
            status="error", error_code="forbidden",
            message="자신이 작성한 comment만 삭제할 수 있습니다",
        )
    sid = getattr(request.state, "session_id", None)
    record = emit_event(
        req.entity_type, req.entity_id, "comment_delete",
        {"target_event_id": req.target_event_id},
        event_dir=cp.event_dir, session_id=sid, principal=principal,
    )

    # 삭제로 pending user comment 집합이 바뀔 수 있어 entity flag 재계산 (INFRA-ISSUE-213).
    # 미호출 시 삭제된 댓글 id 가 pending_user_comment_event_ids 에 남아 done/archive
    # entity 가 reply-pickup 으로 헛픽업된다.
    if req.entity_type in ("issue", "project", "initiative"):
        _recompute_pending_and_wake(cp, req.entity_type, req.entity_id, principal)

    return CapabilityResponse(status="ok", data=record)


