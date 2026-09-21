from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.skill import Skill
from app.schemas.skill import SkillResponse

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
async def list_skills(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Skill)
    if category:
        query = query.where(Skill.category == category)
    result = await db.execute(query.order_by(Skill.category, Skill.name))
    return result.scalars().all()


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException

    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill
