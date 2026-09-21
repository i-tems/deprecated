"""공유 Pydantic 모델 — Resource, Priority, Gates, priority score 계산."""

from typing import Literal

from pydantic import BaseModel, Field

GateValue = Literal["skip", "auto", "require"]


class Resource(BaseModel):
    label: str
    uri: str
    type: str = "url"  # repo | doc | api | url | undecided
    description: str | None = None
    created_at: str | None = None


class Priority(BaseModel):
    value: int = Field(
        default=3,
        ge=1,
        le=5,
        description='1=Backlog, 2=Low, 3=Medium(기본), 4=High, 5=Urgent.',
    )


class Gates(BaseModel):
    completion: GateValue = Field(
        default="auto",
        description='skip=가드없음 / auto=일반전이가드 / require=active→done 직접전이 금지.',
    )


def compute_priority_score(p: dict | None) -> int:
    """Priority → 0-100 score. 가치 1축 기준."""
    if not p:
        return 0
    v = p.get("value", 3)
    return round((v - 1) / 4 * 100)
