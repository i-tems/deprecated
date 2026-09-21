from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.skill import Skill
from app.models.skill_evaluation import SkillEvaluation
from app.models.user import User
from app.models.user_skill import UserSkill
from app.schemas.skill import (
    SkillEvaluationCreate,
    SkillEvaluationResponse,
    UserSkillCreate,
    UserSkillResponse,
)

router = APIRouter(prefix="/api/my/skills", tags=["my-skills"])


def _build_response(us: UserSkill) -> dict:
    latest = us.evaluations[0] if us.evaluations else None
    return {
        "id": us.id,
        "skill": us.skill,
        "latest_evaluation": latest,
        "created_at": us.created_at,
        "updated_at": us.updated_at,
    }


@router.get("", response_model=list[UserSkillResponse])
async def list_my_skills(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserSkill)
        .where(UserSkill.user_id == user.id)
        .options(selectinload(UserSkill.skill), selectinload(UserSkill.evaluations))
        .order_by(UserSkill.created_at.desc())
    )
    return [_build_response(us) for us in result.scalars().all()]


@router.post("", response_model=UserSkillResponse, status_code=201)
async def add_my_skill(
    body: UserSkillCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    skill = (await db.execute(select(Skill).where(Skill.id == body.skill_id))).scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    exists = (
        await db.execute(
            select(UserSkill).where(UserSkill.user_id == user.id, UserSkill.skill_id == body.skill_id)
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Skill already added")

    us = UserSkill(user_id=user.id, skill_id=body.skill_id)
    db.add(us)
    await db.commit()

    result = await db.execute(
        select(UserSkill)
        .where(UserSkill.id == us.id)
        .options(selectinload(UserSkill.skill), selectinload(UserSkill.evaluations))
    )
    return _build_response(result.scalar_one())


@router.get("/{user_skill_id}", response_model=UserSkillResponse)
async def get_my_skill(user_skill_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserSkill)
        .where(UserSkill.id == user_skill_id, UserSkill.user_id == user.id)
        .options(selectinload(UserSkill.skill), selectinload(UserSkill.evaluations))
    )
    us = result.scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Skill not found in your list")
    return _build_response(us)


@router.delete("/{user_skill_id}", status_code=204)
async def delete_my_skill(
    user_skill_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserSkill).where(UserSkill.id == user_skill_id, UserSkill.user_id == user.id))
    us = result.scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Skill not found in your list")
    await db.delete(us)
    await db.commit()


@router.post("/{user_skill_id}/evaluations", response_model=SkillEvaluationResponse, status_code=201)
async def create_skill_evaluation(
    user_skill_id: str,
    body: SkillEvaluationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    us = (
        await db.execute(select(UserSkill).where(UserSkill.id == user_skill_id, UserSkill.user_id == user.id))
    ).scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Skill not found in your list")

    evaluation = SkillEvaluation(user_skill_id=user_skill_id, level=body.level, comment=body.comment)
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)
    return evaluation


@router.get("/{user_skill_id}/evaluations", response_model=list[SkillEvaluationResponse])
async def list_skill_evaluations(
    user_skill_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    us = (
        await db.execute(select(UserSkill).where(UserSkill.id == user_skill_id, UserSkill.user_id == user.id))
    ).scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Skill not found in your list")

    result = await db.execute(
        select(SkillEvaluation).where(SkillEvaluation.user_skill_id == user_skill_id).order_by(SkillEvaluation.created_at.desc())
    )
    return result.scalars().all()
