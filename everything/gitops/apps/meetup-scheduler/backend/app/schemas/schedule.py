from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class ScheduleBlockCreate(BaseModel):
    title: Optional[str] = None
    date: date


class ScheduleBlockUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[date] = None


class ScheduleBlockResponse(BaseModel):
    id: str
    user_id: str
    title: Optional[str]
    date: str
    pattern_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
