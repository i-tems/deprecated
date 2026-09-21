"""Google OAuth + JWT session cookie + email whitelist."""
import os
import time
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse

router = APIRouter()

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
JWT_SECRET = os.environ["JWT_SECRET"]
BASE_URL = os.getenv("BASE_URL", "https://ai.i-tems.com").rstrip("/")
ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}

COOKIE_NAME = "ai_session"
STATE_COOKIE = "ai_oauth_state"
REDIRECT_URI = f"{BASE_URL}/auth/callback"
SESSION_SECONDS = 7 * 24 * 3600  # 1 week


def _sign(email: str) -> str:
    payload = {"email": email, "exp": int(time.time()) + SESSION_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _verify(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def get_claims(request: Request):
    """Return {'email': ...} if the request carries a valid, whitelisted session.
    None otherwise. Does not raise."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    claims = _verify(token)
    if not claims:
        return None
    email = (claims.get("email") or "").lower()
    if email not in ALLOWED_EMAILS:
        return None
    return {"email": email}


async def require_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "not logged in")
    claims = _verify(token)
    if not claims:
        raise HTTPException(401, "invalid session")
    email = (claims.get("email") or "").lower()
    if email not in ALLOWED_EMAILS:
        raise HTTPException(403, "not allowed")
    return {"email": email}


@router.get("/auth/login")
async def login():
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    resp = RedirectResponse(url)
    resp.set_cookie(
        STATE_COOKIE, state,
        max_age=600, httponly=True, secure=True, samesite="lax",
    )
    return resp


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    stored_state = request.cookies.get(STATE_COOKIE)
    if not stored_state or stored_state != state:
        raise HTTPException(400, "state mismatch")
    if not code:
        raise HTTPException(400, "missing code")

    async with httpx.AsyncClient(timeout=15) as cli:
        tok = await cli.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        tok.raise_for_status()
        access_token = tok.json()["access_token"]
        info = await cli.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        info.raise_for_status()
        user = info.json()

    email = (user.get("email") or "").lower()
    if not email or not user.get("email_verified"):
        raise HTTPException(403, "email not verified")
    if email not in ALLOWED_EMAILS:
        raise HTTPException(403, f"{email} is not allowed")

    resp = RedirectResponse("/")
    resp.delete_cookie(STATE_COOKIE)
    resp.set_cookie(
        COOKIE_NAME, _sign(email),
        max_age=SESSION_SECONDS, httponly=True, secure=True, samesite="lax",
    )
    return resp


@router.post("/auth/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    # 쿠키 삭제는 설정 당시와 동일한 속성을 지정해야 모든 브라우저에서 확실히 지워짐
    resp.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, secure=True, samesite="lax",
    )
    return resp


@router.get("/api/me")
async def me(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return {"authenticated": False}
    claims = _verify(token)
    if not claims:
        return {"authenticated": False}
    email = (claims.get("email") or "").lower()
    return {"authenticated": email in ALLOWED_EMAILS, "email": email}
