from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


class AiScheduleAction(BaseModel):
    type: Literal["add", "update", "delete"]
    date: date
    title: Optional[str] = None


class AiScheduleResponse(BaseModel):
    actions: list[AiScheduleAction]
    summary: str
    pattern_detected: Optional[dict] = None


class AiScheduleApplyRequest(BaseModel):
    actions: list[AiScheduleAction]
