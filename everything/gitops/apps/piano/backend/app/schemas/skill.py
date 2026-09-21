from datetime import datetime

from pydantic import BaseModel, Field


class SkillBase(BaseModel):
    name: str
    category: str
    description: str | None = None
    levels: dict | None = None


class SkillCreate(SkillBase):
    pass


class SkillUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    levels: dict | None = None


class SkillResponse(SkillBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SkillEvaluationCreate(BaseModel):
    level: int = Field(ge=1, le=5)
    comment: str | None = None


class SkillEvaluationResponse(BaseModel):
    id: str
    user_skill_id: str
    level: int
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserSkillCreate(BaseModel):
    skill_id: str


class UserSkillResponse(BaseModel):
    id: str
    skill: SkillResponse
    latest_evaluation: SkillEvaluationResponse | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
