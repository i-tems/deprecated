from datetime import datetime

from pydantic import BaseModel

from app.models.user_song import SongStatus
from app.schemas.evaluation import EvaluationResponse
from app.schemas.song import SongResponse


class UserSongCreate(BaseModel):
    song_id: str


class UserSongUpdate(BaseModel):
    status: SongStatus | None = None
    notes: str | None = None


class UserSongResponse(BaseModel):
    id: str
    song: SongResponse
    status: SongStatus
    notes: str | None
    latest_evaluation: EvaluationResponse | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OverviewResponse(BaseModel):
    total_songs: int
    completed_songs: int
    practicing_songs: int
    average_scores: dict[str, float]
    weakest_attribute: str | None
    strongest_attribute: str | None
    skill_levels: dict[str, float] = {}
    total_skills: int = 0
