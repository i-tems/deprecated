from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.models.base import Base
from app.models.evaluation import Evaluation  # noqa: F401
from app.models.practice_session import PracticeSession  # noqa: F401
from app.models.skill import Skill  # noqa: F401
from app.models.skill_evaluation import SkillEvaluation  # noqa: F401
from app.models.sight_reading import SightReadingAttempt, SightReadingSession  # noqa: F401
from app.models.song import Song  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.user_skill import UserSkill  # noqa: F401
from app.models.user_song import UserSong  # noqa: F401
from app.routers import admin, admin_skills, auth, my_skills, my_songs, overview, sight_reading, skills, songs


# Additive column migrations applied at startup.
# Alembic 미설정 상태에서 create_all 은 신규 컬럼을 기존 테이블에 추가하지 못한다.
_ADDITIVE_MIGRATIONS = (
    "ALTER TABLE songs ADD COLUMN IF NOT EXISTS youtube_url VARCHAR",
    "ALTER TABLE songs ADD COLUMN IF NOT EXISTS measure_timestamps JSON",
    "ALTER TABLE songs ADD COLUMN IF NOT EXISTS full_abc TEXT",
    "ALTER TABLE songs ADD COLUMN IF NOT EXISTS page_breaks INTEGER[]",
    "ALTER TABLE practice_sessions ADD COLUMN IF NOT EXISTS audio_start_seconds INTEGER",
    "ALTER TABLE practice_sessions ADD COLUMN IF NOT EXISTS audio_end_seconds INTEGER",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _ADDITIVE_MIGRATIONS:
            await conn.execute(text(stmt))
    yield
    await engine.dispose()


app = FastAPI(title="Piano Practice Tracker", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:3003"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(songs.router)
app.include_router(skills.router)
app.include_router(my_songs.router)
app.include_router(my_skills.router)
app.include_router(overview.router)
app.include_router(sight_reading.router)
app.include_router(admin.router)
app.include_router(admin_skills.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
