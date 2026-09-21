from datetime import date, datetime

from pydantic import BaseModel


class ShiftUnit(BaseModel):
    name: str
    is_working: bool = True


class ShiftPatternCreate(BaseModel):
    name: str
    units: list[ShiftUnit]
    sequence: list[int]
    start_date: date


class ShiftPatternUpdate(BaseModel):
    name: str | None = None
    units: list[ShiftUnit] | None = None
    sequence: list[int] | None = None
    start_date: date | None = None


class ShiftPatternResponse(BaseModel):
    id: str
    user_id: str
    name: str
    pattern_data: dict
    start_date: date
    created_at: datetime

    class Config:
        from_attributes = True
