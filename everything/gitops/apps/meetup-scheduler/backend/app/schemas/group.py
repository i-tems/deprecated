from datetime import datetime

from pydantic import BaseModel


class GroupCreate(BaseModel):
    name: str


class GroupUpdate(BaseModel):
    name: str


class MemberResponse(BaseModel):
    id: str
    user_id: str
    role: str
    joined_at: datetime
    user_name: str
    user_email: str
    user_avatar_url: str | None

    class Config:
        from_attributes = True


class GroupResponse(BaseModel):
    id: str
    name: str
    invite_code: str
    created_by: str
    created_at: datetime
    member_count: int

    class Config:
        from_attributes = True


class GroupDetailResponse(BaseModel):
    id: str
    name: str
    invite_code: str
    created_by: str
    created_at: datetime
    members: list[MemberResponse]

    class Config:
        from_attributes = True


class AvailabilitySlot(BaseModel):
    date: str
    available_members: list[str]
    available_count: int
    total_members: int
