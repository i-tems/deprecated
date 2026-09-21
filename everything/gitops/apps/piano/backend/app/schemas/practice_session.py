from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# The 10 evaluation metrics (must match Evaluation columns and frontend ATTRIBUTES keys).
METRIC_KEYS = (
    "pitch_accuracy",
    "rhythm",
    "tempo_stability",
    "dynamics",
    "articulation",
    "pedaling",
    "phrasing",
    "expressiveness",
    "memorization",
    "technical_fluency",
)


class PracticeSessionStart(BaseModel):
    metrics: list[str] = Field(default_factory=list)
    measure_start: int | None = Field(default=None, ge=1)
    measure_end: int | None = Field(default=None, ge=1)
    audio_start_seconds: int | None = Field(default=None, ge=0)
    audio_end_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate(self):
        unknown = [m for m in self.metrics if m not in METRIC_KEYS]
        if unknown:
            raise ValueError(f"Unknown metrics: {unknown}")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("Duplicate metrics")
        if self.measure_start is not None and self.measure_end is not None:
            if self.measure_end < self.measure_start:
                raise ValueError("measure_end must be >= measure_start")
        if self.audio_start_seconds is not None and self.audio_end_seconds is not None:
            if self.audio_end_seconds < self.audio_start_seconds:
                raise ValueError("audio_end_seconds must be >= audio_start_seconds")
        return self


class PracticeSessionComplete(BaseModel):
    scores: dict[str, int] | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def _validate(self):
        if self.scores is not None:
            for key, value in self.scores.items():
                if key not in METRIC_KEYS:
                    raise ValueError(f"Unknown metric in scores: {key}")
                if not 1 <= value <= 5:
                    raise ValueError(f"Score for {key} must be 1-5")
        return self


class PracticeSessionUpdate(BaseModel):
    metrics: list[str] | None = Field(default=None)
    measure_start: int | None = Field(default=None, ge=1)
    measure_end: int | None = Field(default=None, ge=1)
    audio_start_seconds: int | None = Field(default=None, ge=0)
    audio_end_seconds: int | None = Field(default=None, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scores: dict[str, int] | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def _validate(self):
        if self.metrics is not None:
            unknown = [m for m in self.metrics if m not in METRIC_KEYS]
            if unknown:
                raise ValueError(f"Unknown metrics: {unknown}")
            if len(set(self.metrics)) != len(self.metrics):
                raise ValueError("Duplicate metrics")
        if self.scores is not None:
            for key, value in self.scores.items():
                if key not in METRIC_KEYS:
                    raise ValueError(f"Unknown metric in scores: {key}")
                if not 1 <= value <= 5:
                    raise ValueError(f"Score for {key} must be 1-5")
        if self.measure_start is not None and self.measure_end is not None:
            if self.measure_end < self.measure_start:
                raise ValueError("measure_end must be >= measure_start")
        if self.audio_start_seconds is not None and self.audio_end_seconds is not None:
            if self.audio_end_seconds < self.audio_start_seconds:
                raise ValueError("audio_end_seconds must be >= audio_start_seconds")
        if self.started_at is not None and self.completed_at is not None:
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must be >= started_at")
        return self


class PracticeSessionResponse(BaseModel):
    id: str
    user_song_id: str
    metrics: list[str]
    measure_start: int | None
    measure_end: int | None
    audio_start_seconds: int | None
    audio_end_seconds: int | None
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: int | None
    scores: dict[str, int] | None
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True
