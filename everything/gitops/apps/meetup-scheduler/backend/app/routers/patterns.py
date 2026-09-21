from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.core.day_off import is_day_off_title
from app.core.storage import storage
from app.schemas.pattern import ShiftPatternCreate, ShiftPatternResponse, ShiftPatternUpdate

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


@router.get("", response_model=list[ShiftPatternResponse])
async def get_my_patterns(
    user: dict = Depends(get_current_user),
):
    patterns = await storage.get_shift_patterns(user["id"])
    return [ShiftPatternResponse(**p) for p in patterns]


@router.post("", response_model=ShiftPatternResponse, status_code=201)
async def create_pattern(
    body: ShiftPatternCreate,
    user: dict = Depends(get_current_user),
):
    for u in body.units:
        if u.is_working and is_day_off_title(u.name):
            raise HTTPException(status_code=400, detail=f"근무 단위명 '{u.name}'은 휴무 키워드입니다. 이 단위를 '비번'으로 전환하거나 다른 이름을 쓰세요.")
    pattern_data = {
        "units": [u.model_dump() for u in body.units],
        "sequence": body.sequence,
    }
    pattern = await storage.create_shift_pattern(
        user_id=user["id"],
        name=body.name,
        pattern_data=pattern_data,
        start_date=str(body.start_date),
    )
    # Auto-generate schedule blocks from pattern (365 days ahead)
    await _generate_blocks_from_pattern(user["id"], pattern)
    return ShiftPatternResponse(**pattern)


@router.put("/{pattern_id}", response_model=ShiftPatternResponse)
async def update_pattern(
    pattern_id: str,
    body: ShiftPatternUpdate,
    user: dict = Depends(get_current_user),
):
    pattern = await storage.get_shift_pattern(pattern_id, user["id"])
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.start_date is not None:
        updates["start_date"] = str(body.start_date)
    if body.units is not None and body.sequence is not None:
        for u in body.units:
            if u.is_working and is_day_off_title(u.name):
                raise HTTPException(status_code=400, detail=f"근무 단위명 '{u.name}'은 휴무 키워드입니다. 이 단위를 '비번'으로 전환하거나 다른 이름을 쓰세요.")
        updates["pattern_data"] = {
            "units": [u.model_dump() for u in body.units],
            "sequence": body.sequence,
        }

    if updates:
        pattern = await storage.update_shift_pattern(pattern_id, user["id"], **updates)
        # Re-generate blocks: delete old ones for this pattern, create new
        await storage.delete_blocks_by_pattern(pattern_id, user["id"])
        await _generate_blocks_from_pattern(user["id"], pattern)

    return ShiftPatternResponse(**pattern)


@router.delete("/{pattern_id}", status_code=204)
async def delete_pattern(
    pattern_id: str,
    user: dict = Depends(get_current_user),
):
    # Delete generated blocks first
    await storage.delete_blocks_by_pattern(pattern_id, user["id"])
    deleted = await storage.delete_shift_pattern(pattern_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Pattern not found")


@router.post("/{pattern_id}/apply", response_model=dict)
async def apply_pattern(
    pattern_id: str,
    days_ahead: int = Query(365, ge=1, le=730),
    user: dict = Depends(get_current_user),
):
    """Re-generate schedule blocks from a pattern for the given number of days."""
    pattern = await storage.get_shift_pattern(pattern_id, user["id"])
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    await storage.delete_blocks_by_pattern(pattern_id, user["id"])
    count = await _generate_blocks_from_pattern(user["id"], pattern, days_ahead)
    return {"generated": count}


async def _generate_blocks_from_pattern(user_id: str, pattern: dict, days_ahead: int = 365) -> int:
    """Generate schedule blocks from a shift pattern.

    Each day gets its unit from the pattern sequence based on:
      (day_offset from start_date) % len(sequence) -> unit index
    """
    pd = pattern["pattern_data"]
    units = pd["units"]
    sequence = pd["sequence"]
    if not sequence or not units:
        return 0

    start = date.fromisoformat(str(pattern["start_date"]))
    today = date.today()
    end = today + timedelta(days=days_ahead)
    gen_start = max(start, today)

    count = 0
    current = gen_start
    cycle_len = len(sequence)

    while current <= end:
        day_offset = (current - start).days
        unit_idx = sequence[day_offset % cycle_len]
        if unit_idx < 0 or unit_idx >= len(units):
            current += timedelta(days=1)
            continue

        unit = units[unit_idx]
        # Support both old (start_hour/end_hour) and new (is_working) format
        is_working = unit.get("is_working", True)
        if "start_hour" in unit and "is_working" not in unit:
            is_working = unit["start_hour"] != unit["end_hour"]
        if not is_working or is_day_off_title(unit.get("name")):
            current += timedelta(days=1)
            continue

        # Check if a block already exists for this date
        existing = await storage.get_schedule_block_by_date(user_id, current.isoformat())
        if existing:
            current += timedelta(days=1)
            continue

        await storage.create_schedule_block(
            user_id=user_id,
            title=unit["name"],
            date=current.isoformat(),
            pattern_id=pattern["id"],
        )
        count += 1
        current += timedelta(days=1)

    return count
