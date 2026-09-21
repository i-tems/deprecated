from fastapi import APIRouter, Depends

from app.core.auth import create_access_token, exchange_google_code, get_current_user
from app.core.events import emit, hash_user_id
from app.core.storage import storage
from app.schemas.auth import AuthResponse, GoogleAuthRequest, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


# Design spec → §2: user.signed_up
# Route: POST /api/auth/google (Google OAuth callback — new user branch only)
@router.post("/google", response_model=AuthResponse)
async def google_login(body: GoogleAuthRequest):
    userinfo = await exchange_google_code(body.code, body.redirect_uri)

    google_sub = userinfo["sub"]
    user = await storage.get_user_by_google_sub(google_sub)

    is_new_user = user is None
    if is_new_user:
        user = await storage.create_user(
            email=userinfo["email"],
            name=userinfo.get("name", userinfo["email"]),
            avatar_url=userinfo.get("picture"),
            google_sub=google_sub,
        )
        # Emit after persistence, before response. invite_origin not available at auth step.
        emit("user.signed_up", {
            "signup_source": "direct",
            "invite_origin_group_id_hash": None,
        }, user_id=user["id"])
    else:
        user = await storage.update_user(
            user["id"],
            name=userinfo.get("name", user["name"]),
            avatar_url=userinfo.get("picture", user["avatar_url"]),
        )

    token = create_access_token(user["id"])
    return AuthResponse(token=token, user=UserResponse(**user))


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    return UserResponse(**user)
