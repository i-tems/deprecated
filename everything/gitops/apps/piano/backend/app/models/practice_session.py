import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_song_id: Mapped[str] = mapped_column(
        String, ForeignKey("user_songs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metrics: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    measure_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    measure_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_start_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_end_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scores: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user_song: Mapped["UserSong"] = relationship(back_populates="practice_sessions")

    @property
    def duration_seconds(self) -> int | None:
        if self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at).total_seconds())
