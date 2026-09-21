from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.song import Song
from app.schemas.song import SongListResponse, SongResponse

router = APIRouter(prefix="/api/songs", tags=["songs"])


@router.get("", response_model=SongListResponse)
async def list_songs(
    search: str | None = None,
    composer: str | None = None,
    genre: str | None = None,
    difficulty_min: int | None = Query(None, ge=1, le=10),
    difficulty_max: int | None = Query(None, ge=1, le=10),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Song)
    count_query = select(func.count(Song.id))

    if search:
        query = query.where(Song.title.ilike(f"%{search}%") | Song.composer.ilike(f"%{search}%"))
        count_query = count_query.where(Song.title.ilike(f"%{search}%") | Song.composer.ilike(f"%{search}%"))
    if composer:
        query = query.where(Song.composer.ilike(f"%{composer}%"))
        count_query = count_query.where(Song.composer.ilike(f"%{composer}%"))
    if genre:
        query = query.where(Song.genre == genre)
        count_query = count_query.where(Song.genre == genre)
    if difficulty_min:
        query = query.where(Song.difficulty >= difficulty_min)
        count_query = count_query.where(Song.difficulty >= difficulty_min)
    if difficulty_max:
        query = query.where(Song.difficulty <= difficulty_max)
        count_query = count_query.where(Song.difficulty <= difficulty_max)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(query.order_by(Song.composer, Song.title).offset((page - 1) * size).limit(size))

    return SongListResponse(items=result.scalars().all(), total=total)


@router.get("/{song_id}", response_model=SongResponse)
async def get_song(song_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Song).where(Song.id == song_id))
    song = result.scalar_one_or_none()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song
