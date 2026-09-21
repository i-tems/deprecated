from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.sight_reading import SightReadingAttempt, SightReadingSession
from app.models.user import User
from app.schemas.sight_reading import (
    SightReadingAttemptCreate,
    SightReadingAttemptResponse,
    SightReadingNoteStat,
    SightReadingSessionCreate,
    SightReadingSessionResponse,
    SightReadingStatsResponse,
)

router = APIRouter(prefix="/api/my/sight-reading", tags=["sight-reading"])


def average_score(sessions: list[SightReadingSession]) -> float:
    if not sessions:
        return 0.0
    return round(sum(session.score for session in sessions) / len(sessions), 1)


def build_note_stats(
    attempts: list[SightReadingAttempt],
) -> tuple[list[SightReadingNoteStat], list[SightReadingNoteStat], list[SightReadingNoteStat]]:
    notes: dict[str, dict[str, int | str]] = {}

    for attempt in attempts:
        stat = notes.setdefault(
            attempt.expected_note,
            {
                "note": attempt.expected_note,
                "midi": attempt.expected_midi,
                "correct_count": 0,
                "wrong_count": 0,
            },
        )
        if attempt.was_correct:
            stat["correct_count"] = int(stat["correct_count"]) + 1
        else:
            stat["wrong_count"] = int(stat["wrong_count"]) + 1

    note_stats = [
        SightReadingNoteStat(
            note=str(stat["note"]),
            midi=int(stat["midi"]),
            score=int(stat["correct_count"]) - int(stat["wrong_count"]),
            correct_count=int(stat["correct_count"]),
            wrong_count=int(stat["wrong_count"]),
            total_count=int(stat["correct_count"]) + int(stat["wrong_count"]),
        )
        for stat in notes.values()
    ]
    weakest = sorted(
        note_stats,
        key=lambda stat: (stat.score, -stat.wrong_count, stat.note),
    )[:8]
    strongest = sorted(
        note_stats,
        key=lambda stat: (-stat.score, -stat.correct_count, stat.note),
    )[:8]
    all_notes = sorted(note_stats, key=lambda stat: stat.midi)
    return weakest, strongest, all_notes


@router.post("/sessions", response_model=SightReadingSessionResponse)
async def create_session(
    body: SightReadingSessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = SightReadingSession(user_id=user.id, **body.model_dump())
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.post("/attempts", response_model=SightReadingAttemptResponse)
async def create_attempt(
    body: SightReadingAttemptCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    attempt = SightReadingAttempt(user_id=user.id, **body.model_dump())
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt


@router.get("/stats", response_model=SightReadingStatsResponse)
async def get_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SightReadingSession)
        .where(SightReadingSession.user_id == user.id)
        .order_by(SightReadingSession.created_at.desc())
    )
    sessions = list(result.scalars().all())
    attempts_result = await db.execute(
        select(SightReadingAttempt)
        .where(SightReadingAttempt.user_id == user.id)
        .order_by(SightReadingAttempt.created_at.desc())
    )
    attempts = list(attempts_result.scalars().all())
    weakest_notes, strongest_notes, all_notes = build_note_stats(attempts)
    reaction_times = [
        session.average_reaction_ms
        for session in sessions
        if session.average_reaction_ms is not None
    ]
    recent = sessions[:5]
    previous = sessions[5:10]
    recent_average = average_score(recent)
    previous_average = average_score(previous) if previous else None

    return SightReadingStatsResponse(
        total_sessions=len(sessions),
        best_score=max((session.score for session in sessions), default=0),
        average_score=average_score(sessions),
        average_reaction_ms=(
            round(sum(reaction_times) / len(reaction_times)) if reaction_times else None
        ),
        recent_average_score=recent_average,
        previous_average_score=previous_average,
        score_growth=round(recent_average - previous_average, 1)
        if previous_average is not None
        else 0.0,
        recent_sessions=sessions[:10],
        weakest_notes=weakest_notes,
        strongest_notes=strongest_notes,
        all_notes=all_notes,
    )
