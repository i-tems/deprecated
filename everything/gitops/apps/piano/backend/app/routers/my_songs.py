from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.evaluation import Evaluation
from app.models.practice_session import PracticeSession
from app.models.song import Song
from app.models.user import User
from app.models.user_song import UserSong
from app.schemas.evaluation import EvaluationCreate, EvaluationResponse
from app.schemas.practice_session import (
    PracticeSessionComplete,
    PracticeSessionResponse,
    PracticeSessionStart,
    PracticeSessionUpdate,
)
from app.schemas.user_song import UserSongCreate, UserSongResponse, UserSongUpdate

router = APIRouter(prefix="/api/my/songs", tags=["my-songs"])


def _build_user_song_response(us: UserSong) -> dict:
    latest = us.evaluations[0] if us.evaluations else None
    return {
        "id": us.id,
        "song": us.song,
        "status": us.status,
        "notes": us.notes,
        "latest_evaluation": latest,
        "created_at": us.created_at,
        "updated_at": us.updated_at,
    }


@router.get("", response_model=list[UserSongResponse])
async def list_my_songs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserSong)
        .where(UserSong.user_id == user.id)
        .options(selectinload(UserSong.song), selectinload(UserSong.evaluations))
        .order_by(UserSong.updated_at.desc())
    )
    return [_build_user_song_response(us) for us in result.scalars().all()]


@router.post("", response_model=UserSongResponse, status_code=201)
async def add_my_song(
    body: UserSongCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    song = (await db.execute(select(Song).where(Song.id == body.song_id))).scalar_one_or_none()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    exists = (
        await db.execute(
            select(UserSong).where(UserSong.user_id == user.id, UserSong.song_id == body.song_id)
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Song already added")

    us = UserSong(user_id=user.id, song_id=body.song_id)
    db.add(us)
    await db.commit()

    result = await db.execute(
        select(UserSong)
        .where(UserSong.id == us.id)
        .options(selectinload(UserSong.song), selectinload(UserSong.evaluations))
    )
    return _build_user_song_response(result.scalar_one())


@router.get("/{user_song_id}", response_model=UserSongResponse)
async def get_my_song(user_song_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserSong)
        .where(UserSong.id == user_song_id, UserSong.user_id == user.id)
        .options(selectinload(UserSong.song), selectinload(UserSong.evaluations))
    )
    us = result.scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Song not found in your list")
    return _build_user_song_response(us)


@router.patch("/{user_song_id}", response_model=UserSongResponse)
async def update_my_song(
    user_song_id: str,
    body: UserSongUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserSong)
        .where(UserSong.id == user_song_id, UserSong.user_id == user.id)
        .options(selectinload(UserSong.song), selectinload(UserSong.evaluations))
    )
    us = result.scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Song not found in your list")

    if body.status is not None:
        us.status = body.status
    if body.notes is not None:
        us.notes = body.notes
    await db.commit()
    await db.refresh(us)

    result = await db.execute(
        select(UserSong)
        .where(UserSong.id == us.id)
        .options(selectinload(UserSong.song), selectinload(UserSong.evaluations))
    )
    return _build_user_song_response(result.scalar_one())


@router.delete("/{user_song_id}", status_code=204)
async def delete_my_song(
    user_song_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserSong).where(UserSong.id == user_song_id, UserSong.user_id == user.id))
    us = result.scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Song not found in your list")
    await db.delete(us)
    await db.commit()


@router.post("/{user_song_id}/evaluations", response_model=EvaluationResponse, status_code=201)
async def create_evaluation(
    user_song_id: str,
    body: EvaluationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    us = (
        await db.execute(select(UserSong).where(UserSong.id == user_song_id, UserSong.user_id == user.id))
    ).scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Song not found in your list")

    evaluation = Evaluation(user_song_id=user_song_id, **body.model_dump())
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)
    return evaluation


@router.get("/{user_song_id}/evaluations", response_model=list[EvaluationResponse])
async def list_evaluations(
    user_song_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    us = (
        await db.execute(select(UserSong).where(UserSong.id == user_song_id, UserSong.user_id == user.id))
    ).scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Song not found in your list")

    result = await db.execute(
        select(Evaluation).where(Evaluation.user_song_id == user_song_id).order_by(Evaluation.created_at.desc())
    )
    return result.scalars().all()


async def _own_song_or_404(user_song_id: str, user: User, db: AsyncSession) -> UserSong:
    us = (
        await db.execute(select(UserSong).where(UserSong.id == user_song_id, UserSong.user_id == user.id))
    ).scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Song not found in your list")
    return us


@router.post(
    "/{user_song_id}/practice-sessions", response_model=PracticeSessionResponse, status_code=201
)
async def start_practice_session(
    user_song_id: str,
    body: PracticeSessionStart,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _own_song_or_404(user_song_id, user, db)
    session = PracticeSession(
        user_song_id=user_song_id,
        metrics=body.metrics,
        measure_start=body.measure_start,
        measure_end=body.measure_end,
        audio_start_seconds=body.audio_start_seconds,
        audio_end_seconds=body.audio_end_seconds,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.post(
    "/{user_song_id}/practice-sessions/{session_id}/complete",
    response_model=PracticeSessionResponse,
)
async def complete_practice_session(
    user_song_id: str,
    session_id: str,
    body: PracticeSessionComplete,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _own_song_or_404(user_song_id, user, db)
    session = (
        await db.execute(
            select(PracticeSession).where(
                PracticeSession.id == session_id, PracticeSession.user_song_id == user_song_id
            )
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Practice session not found")
    if session.completed_at is not None:
        raise HTTPException(status_code=409, detail="Practice session already completed")
    if body.scores is not None:
        unknown = [k for k in body.scores if k not in session.metrics]
        if unknown:
            raise HTTPException(
                status_code=422, detail=f"Scores contain metrics not in this session: {unknown}"
            )

    session.completed_at = datetime.now(timezone.utc)
    session.scores = body.scores
    session.comment = body.comment
    await db.commit()
    await db.refresh(session)
    return session


@router.get(
    "/{user_song_id}/practice-sessions", response_model=list[PracticeSessionResponse]
)
async def list_practice_sessions(
    user_song_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _own_song_or_404(user_song_id, user, db)
    result = await db.execute(
        select(PracticeSession)
        .where(PracticeSession.user_song_id == user_song_id)
        .order_by(PracticeSession.started_at.desc())
    )
    return result.scalars().all()


@router.patch(
    "/{user_song_id}/practice-sessions/{session_id}", response_model=PracticeSessionResponse
)
async def update_practice_session(
    user_song_id: str,
    session_id: str,
    body: PracticeSessionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _own_song_or_404(user_song_id, user, db)
    session = (
        await db.execute(
            select(PracticeSession).where(
                PracticeSession.id == session_id, PracticeSession.user_song_id == user_song_id
            )
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Practice session not found")

    changes = body.model_dump(exclude_unset=True)

    new_metrics = changes.get("metrics", session.metrics)
    new_scores = changes["scores"] if "scores" in changes else session.scores
    if new_scores is not None and new_metrics is not None:
        unknown = [k for k in new_scores if k not in new_metrics]
        if unknown:
            raise HTTPException(
                status_code=422, detail=f"Scores contain metrics not in this session: {unknown}"
            )

    new_started = changes.get("started_at", session.started_at)
    new_completed = changes["completed_at"] if "completed_at" in changes else session.completed_at
    if new_started is not None and new_completed is not None and new_completed < new_started:
        raise HTTPException(status_code=422, detail="completed_at must be >= started_at")

    for field, value in changes.items():
        setattr(session, field, value)

    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/{user_song_id}/practice-sessions/{session_id}", status_code=204)
async def delete_practice_session(
    user_song_id: str,
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _own_song_or_404(user_song_id, user, db)
    session = (
        await db.execute(
            select(PracticeSession).where(
                PracticeSession.id == session_id, PracticeSession.user_song_id == user_song_id
            )
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Practice session not found")
    await db.delete(session)
    await db.commit()
