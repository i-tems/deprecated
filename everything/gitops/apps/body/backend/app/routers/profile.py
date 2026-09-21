from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import PROFILE_FILE
from app.core.storage import read_json, write_json

router = APIRouter(prefix="/api", tags=["profile"])


class ProfileUpdate(BaseModel):
    weight: float | None = None
    height: float | None = None
    unit: str | None = None


@router.get("/profile")
def get_profile():
    data = read_json(PROFILE_FILE)
    if data is None:
        return {"weight": 0, "height": 0, "unit": "kg"}
    return data


@router.put("/profile")
def update_profile(body: ProfileUpdate):
    current = read_json(PROFILE_FILE) or {"weight": 0, "height": 0, "unit": "kg"}
    if body.weight is not None:
        current["weight"] = body.weight
    if body.height is not None:
        current["height"] = body.height
    if body.unit is not None:
        current["unit"] = body.unit
    write_json(PROFILE_FILE, current)
    return current
