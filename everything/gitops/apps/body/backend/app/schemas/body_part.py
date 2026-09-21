from pydantic import BaseModel


class StrengthStandards(BaseModel):
    model_config = {"extra": "allow"}


class BodyPartConfig(BaseModel):
    id: str
    name: str
    group: str
    representative_exercise: str
    strength_standards: dict[str, str] = {}


class AttributeConfig(BaseModel):
    id: str
    name: str
    description: str


class PartEvaluation(BaseModel):
    strength: float | None = None
    development: float | None = None
    mmc: float | None = None
    best_5rm: float | None = None  # kg — 5RM of the body part's representative exercise
