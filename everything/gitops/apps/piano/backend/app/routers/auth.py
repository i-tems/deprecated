from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    exchange_google_code,
    get_current_user,
)
from app.core.database import get_db
from app.models.skill import Skill
from app.models.user import User
from app.models.user_skill import UserSkill
from app.schemas.auth import GoogleAuthRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/google", response_model=TokenResponse)
async def google_auth(body: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    google_user = await exchange_google_code(body.code, body.redirect_uri)

    sub = google_user.get("sub")
    email = google_user.get("email")
    name = google_user.get("name", email)
    avatar = google_user.get("picture")

    result = await db.execute(select(User).where(User.google_sub == sub))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=email, name=name, avatar_url=avatar, google_sub=sub)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # 모든 스킬 자동 추가
        all_skills = (await db.execute(select(Skill))).scalars().all()
        for skill in all_skills:
            db.add(UserSkill(user_id=user.id, skill_id=skill.id))
        await db.commit()
    else:
        user.name = name
        user.avatar_url = avatar
        await db.commit()

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user
