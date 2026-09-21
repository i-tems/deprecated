from pydantic import BaseModel


class SkillConfig(BaseModel):
    id: str
    name: str
    description: str


class SkillEvaluationEntry(BaseModel):
    level: float
    note: str = ""


class SkillEvaluationRequest(BaseModel):
    date: str
    skills: dict[str, SkillEvaluationEntry]
