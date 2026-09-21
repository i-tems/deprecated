from datetime import date
from typing import Any
from fastapi import APIRouter, Query
from pydantic import BaseModel
from app.core.config import EVALUATIONS_DIR
from app.core.storage import read_json, write_json, list_date_files

router = APIRouter(prefix="/api", tags=["evaluations"])


class FlatEvaluation(BaseModel):
    date: str
    part_id: str
    strength: float = 0
    development: float = 0
    mmc: float = 0
    best_5rm: float | None = None


@router.get("/evaluations")
def get_evaluations(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    part: str | None = Query(None),
):
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date) if to_date else None
    files = list_date_files(EVALUATIONS_DIR, fd, td)

    results = []
    for f in files:
        data = read_json(f)
        if data is None:
            continue
        eval_date = data.get("date", f.stem)
        for part_id, part_data in data.get("parts", {}).items():
            if part and part_id != part:
                continue
            results.append({
                "date": eval_date,
                "part_id": part_id,
                "strength": part_data.get("strength", 0),
                "development": part_data.get("development", 0),
                "mmc": part_data.get("mmc", 0),
                "best_5rm": part_data.get("best_5rm"),
            })
    return results


@router.post("/evaluations")
def create_evaluation(body: list[FlatEvaluation]):
    """Accept array of flat evaluations from frontend, group by date and save."""
    by_date: dict[str, dict[str, Any]] = {}

    for item in body:
        if item.date not in by_date:
            by_date[item.date] = {
                "date": item.date,
                "parts": {},
            }
        part_payload: dict[str, Any] = {
            "strength": item.strength,
            "development": item.development,
            "mmc": item.mmc,
        }
        if item.best_5rm is not None:
            part_payload["best_5rm"] = item.best_5rm
        by_date[item.date]["parts"][item.part_id] = part_payload

    results = []
    for eval_date, data in by_date.items():
        file_path = EVALUATIONS_DIR / f"{eval_date}.json"
        existing = read_json(file_path)
        if existing:
            existing_parts = existing.get("parts", {})
            existing_parts.update(data["parts"])
            existing["parts"] = existing_parts
            write_json(file_path, existing)
            results.append(existing)
        else:
            write_json(file_path, data)
            results.append(data)

    return results
