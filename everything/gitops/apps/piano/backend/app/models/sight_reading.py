import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SightReadingSession(Base):
    __tablename__ = "sight_reading_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    average_reaction_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fastest_limit_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    ended_reason: Mapped[str] = mapped_column(String, nullable=False)
    expected_note: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship(back_populates="sight_reading_sessions")


class SightReadingAttempt(Base):
    __tablename__ = "sight_reading_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expected_note: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expected_midi: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_note: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_midi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    was_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    reaction_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship(back_populates="sight_reading_attempts")
