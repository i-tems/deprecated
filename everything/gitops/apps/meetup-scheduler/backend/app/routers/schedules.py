from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.core.day_off import is_day_off_title
from app.core.events import emit, hash_user_id
from app.core.storage import storage
from app.schemas.schedule import ScheduleBlockCreate, ScheduleBlockResponse, ScheduleBlockUpdate

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleBlockResponse])
async def get_my_schedules(
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
    user: dict = Depends(get_current_user),
):
    blocks = await storage.get_schedule_blocks(user["id"], start.isoformat(), end.isoformat())
    return [ScheduleBlockResponse(**b) for b in blocks]


# Design spec → §2: schedule.first_recorded
# Route: POST /api/schedules (first block creation for this user — 0→1 transition)
@router.post("", response_model=ScheduleBlockResponse, status_code=201)
async def create_schedule(
    body: ScheduleBlockCreate,
    user: dict = Depends(get_current_user),
):
    if is_day_off_title(body.title):
        raise HTTPException(status_code=400, detail="휴무는 블록으로 등록하지 않습니다. 빈 날짜가 곧 휴무입니다.")

    existing = await storage.get_schedule_block_by_date(user["id"], body.date.isoformat())
    if existing:
        raise HTTPException(status_code=409, detail="이미 해당 날짜에 일정이 존재합니다")

    # Check before create to detect first-ever block (0→1 transition)
    prior_blocks = await storage.get_schedule_blocks(user["id"], "2000-01-01", "2099-12-31")
    is_first = len(prior_blocks) == 0

    block = await storage.create_schedule_block(
        user_id=user["id"],
        title=body.title,
        date=body.date.isoformat(),
    )

    if is_first:
        emit("schedule.first_recorded", {
            "days_recorded": 1,
            "method": "manual",
        }, user_id=user["id"])

    return ScheduleBlockResponse(**block)


# Design spec → §2: schedule.updated
# Route: PUT /api/schedules/{block_id} (title/date modification of existing block)
@router.put("/{block_id}", response_model=ScheduleBlockResponse)
async def update_schedule(
    block_id: str,
    body: ScheduleBlockUpdate,
    user: dict = Depends(get_current_user),
):
    block = await storage.get_schedule_block(block_id, user["id"])
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")

    updates = body.model_dump(exclude_unset=True)

    if "title" in updates and is_day_off_title(updates["title"]):
        raise HTTPException(status_code=400, detail="휴무는 블록으로 등록하지 않습니다. 빈 날짜가 곧 휴무입니다.")

    if "date" in updates and updates["date"] is not None:
        new_date = updates["date"].isoformat() if hasattr(updates["date"], "isoformat") else updates["date"]
        if new_date != block["date"]:
            existing = await storage.get_schedule_block_by_date(user["id"], new_date)
            if existing:
                raise HTTPException(status_code=409, detail="이미 해당 날짜에 일정이 존재합니다")
        updates["date"] = new_date

    if updates:
        block = await storage.update_schedule_block(block_id, user["id"], **updates)

    emit("schedule.updated", {
        "delta_added": 0,
        "delta_removed": 0,
        "method": "manual",
    }, user_id=user["id"])

    return ScheduleBlockResponse(**block)


# Design spec → §2: schedule.updated (bulk delete — delta_removed = count)
@router.delete("/all", status_code=200)
async def delete_all_schedules(
    user: dict = Depends(get_current_user),
):
    count = await storage.delete_all_schedule_blocks(user["id"])
    emit("schedule.updated", {
        "delta_added": 0,
        "delta_removed": count,
        "method": "manual",
    }, user_id=user["id"])
    return {"deleted": count}


# Design spec → §2: schedule.updated (single block delete)
@router.delete("/{block_id}", status_code=204)
async def delete_schedule(
    block_id: str,
    user: dict = Depends(get_current_user),
):
    deleted = await storage.delete_schedule_block(block_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Block not found")
    emit("schedule.updated", {
        "delta_added": 0,
        "delta_removed": 1,
        "method": "manual",
    }, user_id=user["id"])
