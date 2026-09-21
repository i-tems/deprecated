import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_song_id: Mapped[str] = mapped_column(
        String, ForeignKey("user_songs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pitch_accuracy: Mapped[int] = mapped_column(Integer, nullable=False)
    rhythm: Mapped[int] = mapped_column(Integer, nullable=False)
    tempo_stability: Mapped[int] = mapped_column(Integer, nullable=False)
    dynamics: Mapped[int] = mapped_column(Integer, nullable=False)
    articulation: Mapped[int] = mapped_column(Integer, nullable=False)
    pedaling: Mapped[int] = mapped_column(Integer, nullable=False)
    phrasing: Mapped[int] = mapped_column(Integer, nullable=False)
    expressiveness: Mapped[int] = mapped_column(Integer, nullable=False)
    memorization: Mapped[int] = mapped_column(Integer, nullable=False)
    technical_fluency: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user_song: Mapped["UserSong"] = relationship(back_populates="evaluations")
