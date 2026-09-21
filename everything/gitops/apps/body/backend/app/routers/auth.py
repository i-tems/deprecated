from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import create_access_token, exchange_google_code, get_current_user
from app.core.config import USERS_FILE
from app.core.storage import read_json, write_json

router = APIRouter(prefix="/api/auth", tags=["auth"])


class GoogleAuthRequest(BaseModel):
    code: str
    redirect_uri: str


class TokenResponse(BaseModel):
    access_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    avatar_url: str | None = None


@router.post("/google", response_model=TokenResponse)
async def google_auth(body: GoogleAuthRequest):
    google_user = await exchange_google_code(body.code, body.redirect_uri)

    sub = google_user.get("sub")
    email = google_user.get("email")
    name = google_user.get("name", email)
    avatar = google_user.get("picture")

    # Load or create users file
    users = read_json(USERS_FILE) or {}

    users[sub] = {
        "email": email,
        "name": name,
        "avatar_url": avatar,
    }
    write_json(USERS_FILE, users)

    token = create_access_token(sub)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        avatar_url=user.get("avatar_url"),
    )
