from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.database import get_db
from app.models.song import Song
from app.models.user import User
from app.schemas.song import SongCreate, SongResponse, SongUpdate

router = APIRouter(prefix="/api/admin/songs", tags=["admin"])


@router.post("", response_model=SongResponse, status_code=201)
async def create_song(body: SongCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    song = Song(**body.model_dump())
    db.add(song)
    await db.commit()
    await db.refresh(song)
    return song


@router.put("/{song_id}", response_model=SongResponse)
async def update_song(
    song_id: str, body: SongUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Song).where(Song.id == song_id))
    song = result.scalar_one_or_none()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(song, field, value)

    await db.commit()
    await db.refresh(song)
    return song


@router.delete("/{song_id}", status_code=204)
async def delete_song(song_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Song).where(Song.id == song_id))
    song = result.scalar_one_or_none()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    await db.delete(song)
    await db.commit()
