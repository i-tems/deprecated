from datetime import datetime

from pydantic import BaseModel, Field


class EvaluationCreate(BaseModel):
    pitch_accuracy: int = Field(ge=1, le=5)
    rhythm: int = Field(ge=1, le=5)
    tempo_stability: int = Field(ge=1, le=5)
    dynamics: int = Field(ge=1, le=5)
    articulation: int = Field(ge=1, le=5)
    pedaling: int = Field(ge=1, le=5)
    phrasing: int = Field(ge=1, le=5)
    expressiveness: int = Field(ge=1, le=5)
    memorization: int = Field(ge=1, le=5)
    technical_fluency: int = Field(ge=1, le=5)
    comment: str | None = None


class EvaluationResponse(EvaluationCreate):
    id: str
    user_song_id: str
    created_at: datetime

    class Config:
        from_attributes = True
