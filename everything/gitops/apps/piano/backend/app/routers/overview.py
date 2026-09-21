from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.user_skill import UserSkill
from app.models.user_song import SongStatus, UserSong
from app.schemas.user_song import OverviewResponse

router = APIRouter(prefix="/api/my", tags=["overview"])

ATTRIBUTES = [
    "pitch_accuracy", "rhythm", "tempo_stability", "dynamics",
    "articulation", "pedaling", "phrasing", "expressiveness",
    "memorization", "technical_fluency",
]


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Songs
    result = await db.execute(
        select(UserSong)
        .where(UserSong.user_id == user.id)
        .options(selectinload(UserSong.evaluations))
    )
    user_songs = result.scalars().all()

    total = len(user_songs)
    completed = sum(1 for us in user_songs if us.status == SongStatus.COMPLETED)
    practicing = sum(1 for us in user_songs if us.status == SongStatus.PRACTICING)

    avg_scores = {attr: 0.0 for attr in ATTRIBUTES}
    count = 0

    for us in user_songs:
        if us.evaluations:
            latest = us.evaluations[0]
            count += 1
            for attr in ATTRIBUTES:
                avg_scores[attr] += getattr(latest, attr)

    if count > 0:
        for attr in ATTRIBUTES:
            avg_scores[attr] = round(avg_scores[attr] / count, 2)

    weakest = min(avg_scores, key=avg_scores.get) if count > 0 else None
    strongest = max(avg_scores, key=avg_scores.get) if count > 0 else None

    # Skills
    skill_result = await db.execute(
        select(UserSkill)
        .where(UserSkill.user_id == user.id)
        .options(selectinload(UserSkill.skill), selectinload(UserSkill.evaluations))
    )
    user_skills = skill_result.scalars().all()

    skill_levels: dict[str, float] = {}
    for us in user_skills:
        if us.evaluations:
            skill_levels[us.skill.name] = us.evaluations[0].level

    return OverviewResponse(
        total_songs=total,
        completed_songs=completed,
        practicing_songs=practicing,
        average_scores=avg_scores,
        weakest_attribute=weakest,
        strongest_attribute=strongest,
        skill_levels=skill_levels,
        total_skills=len(user_skills),
    )
