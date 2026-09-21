from datetime import date
from typing import Any
from fastapi import APIRouter, Query
from pydantic import BaseModel
from app.core.config import SKILL_EVALUATIONS_DIR
from app.core.storage import read_json, write_json, list_date_files

router = APIRouter(prefix="/api", tags=["skill-evaluations"])


class FlatSkillEvaluation(BaseModel):
    date: str
    skill_id: str
    score: float = 0


@router.get("/skill-evaluations")
def get_skill_evaluations(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
):
    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date) if to_date else None
    files = list_date_files(SKILL_EVALUATIONS_DIR, fd, td)

    results = []
    for f in files:
        data = read_json(f)
        if data is None:
            continue
        eval_date = data.get("date", f.stem)
        for skill_id, skill_data in data.get("skills", {}).items():
            results.append({
                "date": eval_date,
                "skill_id": skill_id,
                "score": skill_data.get("level", 0),
            })
    return results


@router.post("/skill-evaluations")
def create_skill_evaluation(body: list[FlatSkillEvaluation]):
    """Accept array of flat skill evaluations, group by date and save."""
    by_date: dict[str, dict[str, Any]] = {}

    for item in body:
        if item.date not in by_date:
            by_date[item.date] = {"date": item.date, "skills": {}}
        by_date[item.date]["skills"][item.skill_id] = {
            "level": item.score,
        }

    results = []
    for eval_date, data in by_date.items():
        file_path = SKILL_EVALUATIONS_DIR / f"{eval_date}.json"
        existing = read_json(file_path)
        if existing:
            existing_skills = existing.get("skills", {})
            existing_skills.update(data["skills"])
            existing["skills"] = existing_skills
            write_json(file_path, existing)
            results.append(existing)
        else:
            write_json(file_path, data)
            results.append(data)

    return results
