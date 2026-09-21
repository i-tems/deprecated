import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.core.events import emit, hash_group_id, hash_user_id
from app.core.storage import storage
from app.schemas.group import (
    AvailabilitySlot,
    GroupCreate,
    GroupDetailResponse,
    GroupResponse,
    GroupUpdate,
    MemberResponse,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])

_NEW_USER_WINDOW_SEC = 3600  # user created within 1h counts as "new" at join time


@router.get("", response_model=list[GroupResponse])
async def get_my_groups(user: dict = Depends(get_current_user)):
    groups = await storage.get_groups_for_user(user["id"])
    return [GroupResponse(**g) for g in groups]


# Design spec → §2: group.created
# Route: POST /api/groups (group record + invite_code created)
@router.post("", response_model=GroupDetailResponse, status_code=201)
async def create_group(body: GroupCreate, user: dict = Depends(get_current_user)):
    invite_code = secrets.token_urlsafe(8)
    group = await storage.create_group(name=body.name, created_by=user["id"], invite_code=invite_code)
    member = await storage.add_group_member(group_id=group["id"], user_id=user["id"], role="ADMIN")

    emit("group.created", {
        "group_id_hash": hash_group_id(group["id"]),
        "initial_member_count": 1,
    }, user_id=user["id"])

    return GroupDetailResponse(
        id=group["id"],
        name=group["name"],
        invite_code=group["invite_code"],
        created_by=group["created_by"],
        created_at=group["created_at"],
        members=[
            MemberResponse(
                id=member["id"],
                user_id=user["id"],
                role=member["role"],
                joined_at=member["joined_at"],
                user_name=user["name"],
                user_email=user["email"],
                user_avatar_url=user.get("avatar_url"),
            )
        ],
    )


@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group(group_id: str, user: dict = Depends(get_current_user)):
    await _require_member(group_id, user["id"])

    group = await storage.get_group_by_id(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    members = await storage.get_group_members(group_id)
    return _build_group_detail(group, members)


@router.put("/{group_id}", response_model=GroupDetailResponse)
async def update_group(group_id: str, body: GroupUpdate, user: dict = Depends(get_current_user)):
    await _require_admin(group_id, user["id"])

    group = await storage.update_group(group_id, name=body.name)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    members = await storage.get_group_members(group_id)
    return _build_group_detail(group, members)


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: str, user: dict = Depends(get_current_user)):
    await _require_admin(group_id, user["id"])

    group = await storage.get_group_by_id(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    await storage.delete_group(group_id)


# Design spec → §2: group.joined (via_invite=True — invite link path)
# Route: POST /api/groups/join/{invite_code}
@router.post("/join/{invite_code}", response_model=GroupDetailResponse)
async def join_group(invite_code: str, user: dict = Depends(get_current_user)):
    group = await storage.get_group_by_invite_code(invite_code)
    if group is None:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    existing = await storage.get_group_member(group["id"], user["id"])
    if existing is not None:
        raise HTTPException(status_code=400, detail="Already a member")

    await storage.add_group_member(group_id=group["id"], user_id=user["id"], role="MEMBER")

    # Detect new user: account created within the last hour
    try:
        created_at_str = user.get("created_at", "")
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")) if created_at_str else None
        is_new_user = (
            created_at is not None
            and (datetime.now(timezone.utc) - created_at).total_seconds() < _NEW_USER_WINDOW_SEC
        )
    except (ValueError, TypeError):
        is_new_user = False

    emit("group.joined", {
        "group_id_hash": hash_group_id(group["id"]),
        "via_invite": True,
        "is_new_user": is_new_user,
    }, user_id=user["id"])

    members = await storage.get_group_members(group["id"])
    return _build_group_detail(group, members)


@router.delete("/{group_id}/members/{member_user_id}", status_code=204)
async def remove_member(group_id: str, member_user_id: str, user: dict = Depends(get_current_user)):
    is_self = member_user_id == user["id"]
    if not is_self:
        await _require_admin(group_id, user["id"])

    existing = await storage.get_group_member(group_id, member_user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Member not found")

    await storage.remove_group_member(group_id, member_user_id)


@router.post("/{group_id}/invite-link")
async def regenerate_invite(group_id: str, user: dict = Depends(get_current_user)):
    await _require_admin(group_id, user["id"])

    group = await storage.get_group_by_id(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    new_code = secrets.token_urlsafe(8)
    await storage.update_group(group_id, invite_code=new_code)
    return {"invite_code": new_code}


@router.get("/{group_id}/schedules")
async def get_group_schedules(
    group_id: str,
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
    user: dict = Depends(get_current_user),
):
    await _require_member(group_id, user["id"])

    members = await storage.get_group_members(group_id)
    member_user_ids = [m["user_id"] for m in members]

    blocks = await storage.get_schedule_blocks_for_users(member_user_ids, start.isoformat(), end.isoformat())

    blocks_by_user: dict[str, list] = {}
    for b in blocks:
        blocks_by_user.setdefault(b["user_id"], []).append({
            "id": b["id"],
            "title": b["title"],
            "date": b["date"],
        })

    return {
        "members": [
            {
                "user_id": m["user_id"],
                "user_name": m["user_name"],
                "user_avatar_url": m.get("user_avatar_url"),
                "blocks": blocks_by_user.get(m["user_id"], []),
            }
            for m in members
        ]
    }


# Design spec → §2: availability.viewed
# Route: GET /api/groups/{group_id}/availability (after computing available slots)
@router.get("/{group_id}/availability", response_model=list[AvailabilitySlot])
async def get_availability(
    group_id: str,
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
    min_members: int = Query(0),
    user: dict = Depends(get_current_user),
):
    await _require_member(group_id, user["id"])

    member_user_ids = await storage.get_member_user_ids(group_id)
    total = len(member_user_ids)

    if min_members <= 0:
        min_members = total

    blocks = await storage.get_schedule_blocks_for_users(member_user_ids, start.isoformat(), end.isoformat())

    busy_set: set[tuple[str, str]] = set()
    for b in blocks:
        busy_set.add((b["user_id"], b["date"]))

    # Count members with at least one schedule block in the window
    members_with_schedules = len({b["user_id"] for b in blocks})

    slots = []
    current = start
    while current <= end:
        date_str = current.isoformat()
        available = [uid for uid in member_user_ids if (uid, date_str) not in busy_set]
        if len(available) >= min_members:
            slots.append(
                AvailabilitySlot(
                    date=date_str,
                    available_members=available,
                    available_count=len(available),
                    total_members=total,
                )
            )
        current += timedelta(days=1)

    window_days = (end - start).days + 1
    emit("availability.viewed", {
        "group_id_hash": hash_group_id(group_id),
        "window_days": window_days,
        "members_with_schedules": members_with_schedules,
        "available_days_found": len(slots),
    }, user_id=user["id"])

    return slots


def _build_group_detail(group: dict, members: list[dict]) -> GroupDetailResponse:
    return GroupDetailResponse(
        id=group["id"],
        name=group["name"],
        invite_code=group["invite_code"],
        created_by=group["created_by"],
        created_at=group["created_at"],
        members=[
            MemberResponse(
                id=m["id"],
                user_id=m["user_id"],
                role=m["role"],
                joined_at=m["joined_at"],
                user_name=m["user_name"],
                user_email=m["user_email"],
                user_avatar_url=m.get("user_avatar_url"),
            )
            for m in members
        ],
    )


async def _require_member(group_id: str, user_id: str):
    member = await storage.get_group_member(group_id, user_id)
    if member is None:
        raise HTTPException(status_code=403, detail="Not a member of this group")


async def _require_admin(group_id: str, user_id: str):
    member = await storage.get_group_member(group_id, user_id)
    if member is None or member["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
