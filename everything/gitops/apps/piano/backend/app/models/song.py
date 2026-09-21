import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String, nullable=False, index=True)
    composer: Mapped[str] = mapped_column(String, nullable=False, index=True)
    genre: Mapped[str | None] = mapped_column(String, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_skills: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    practice_tips: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sheet_snippets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    full_abc: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_breaks: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String, nullable=True)
    measure_timestamps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user_songs: Mapped[list["UserSong"]] = relationship(back_populates="song")
