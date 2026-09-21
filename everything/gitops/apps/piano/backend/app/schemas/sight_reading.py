from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


EndedReason = Literal["wrong", "timeout"]


class SightReadingSessionCreate(BaseModel):
    score: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    average_reaction_ms: int | None = Field(default=None, ge=0)
    fastest_limit_ms: int = Field(ge=0)
    duration_seconds: int = Field(ge=0)
    ended_reason: EndedReason
    expected_note: str | None = None
    actual_note: str | None = None


class SightReadingSessionResponse(BaseModel):
    id: str
    score: int
    correct_count: int
    average_reaction_ms: int | None
    fastest_limit_ms: int
    duration_seconds: int
    ended_reason: EndedReason
    expected_note: str | None
    actual_note: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class SightReadingAttemptCreate(BaseModel):
    expected_note: str
    expected_midi: int
    actual_note: str | None = None
    actual_midi: int | None = None
    was_correct: bool
    reaction_ms: int | None = Field(default=None, ge=0)


class SightReadingAttemptResponse(BaseModel):
    id: str
    expected_note: str
    expected_midi: int
    actual_note: str | None
    actual_midi: int | None
    was_correct: bool
    reaction_ms: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class SightReadingNoteStat(BaseModel):
    note: str
    midi: int
    score: int
    correct_count: int
    wrong_count: int
    total_count: int


class SightReadingStatsResponse(BaseModel):
    total_sessions: int
    best_score: int
    average_score: float
    average_reaction_ms: int | None
    recent_average_score: float
    previous_average_score: float | None
    score_growth: float
    recent_sessions: list[SightReadingSessionResponse]
    weakest_notes: list[SightReadingNoteStat]
    strongest_notes: list[SightReadingNoteStat]
    all_notes: list[SightReadingNoteStat]
