from pydantic import BaseModel
from .body_part import PartEvaluation


class EvaluationRequest(BaseModel):
    date: str
    parts: dict[str, PartEvaluation]


class EvaluationResponse(BaseModel):
    date: str
    parts: dict[str, PartEvaluation]
