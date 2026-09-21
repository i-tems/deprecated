import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SongStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    PRACTICING = "PRACTICING"
    POLISHING = "POLISHING"
    COMPLETED = "COMPLETED"


class UserSong(Base):
    __tablename__ = "user_songs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    song_id: Mapped[str] = mapped_column(String, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[SongStatus] = mapped_column(Enum(SongStatus), default=SongStatus.NOT_STARTED)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship(back_populates="user_songs")
    song: Mapped["Song"] = relationship(back_populates="user_songs")
    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="user_song", cascade="all, delete-orphan", order_by="Evaluation.created_at.desc()"
    )
    practice_sessions: Mapped[list["PracticeSession"]] = relationship(
        back_populates="user_song",
        cascade="all, delete-orphan",
        order_by="PracticeSession.started_at.desc()",
    )
