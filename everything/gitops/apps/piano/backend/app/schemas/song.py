from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ReferenceUrl(BaseModel):
    label: str
    url: str


class MeasureAnchor(BaseModel):
    measure: int = Field(ge=1)
    seconds: float = Field(ge=0)


def _validate_anchors(v: list[MeasureAnchor] | None) -> list[MeasureAnchor] | None:
    if v is None:
        return v
    measures = [a.measure for a in v]
    if len(set(measures)) != len(measures):
        raise ValueError("Duplicate measure in measure_timestamps")
    return v


def _validate_page_breaks(v: list[int] | None) -> list[int] | None:
    # 페이지별 system 개수. 예: [6,7,7,6] = 4 페이지 (6+7+7+6=26 systems).
    # 비어 있거나 None 이면 페이지 분할 없음(단일 SVG).
    if v is None:
        return v
    if any(n < 1 for n in v):
        raise ValueError("page_breaks entries must be >= 1")
    return v


class SongBase(BaseModel):
    title: str
    composer: str
    genre: str | None = None
    difficulty: int = Field(ge=1, le=10)
    estimated_weeks: int | None = None
    analysis_text: str | None = None
    required_skills: dict | None = None
    practice_tips: str | None = None
    reference_urls: list[ReferenceUrl] | None = None
    sheet_snippets: list[dict] | None = None
    full_abc: str | None = None
    page_breaks: list[int] | None = None
    youtube_url: str | None = None
    measure_timestamps: list[MeasureAnchor] | None = None

    @model_validator(mode="after")
    def _check_anchors(self):
        _validate_anchors(self.measure_timestamps)
        _validate_page_breaks(self.page_breaks)
        return self


class SongCreate(SongBase):
    pass


class SongUpdate(BaseModel):
    title: str | None = None
    composer: str | None = None
    genre: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=10)
    estimated_weeks: int | None = None
    analysis_text: str | None = None
    required_skills: dict | None = None
    practice_tips: str | None = None
    reference_urls: list[ReferenceUrl] | None = None
    sheet_snippets: list[dict] | None = None
    full_abc: str | None = None
    page_breaks: list[int] | None = None
    youtube_url: str | None = None
    measure_timestamps: list[MeasureAnchor] | None = None

    @model_validator(mode="after")
    def _check_anchors(self):
        _validate_anchors(self.measure_timestamps)
        _validate_page_breaks(self.page_breaks)
        return self


class SongResponse(SongBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SongListResponse(BaseModel):
    items: list[SongResponse]
    total: int
