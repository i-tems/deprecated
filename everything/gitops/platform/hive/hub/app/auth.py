"""Google OAuth 인증 — login, logout, verify, config, login_history endpoints."""

import logging
import os
import time
from datetime import datetime, timezone

import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter()
log = logging.getLogger("hub.auth")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET or len(JWT_SECRET) < 32:
    raise RuntimeError(
        "JWT_SECRET must be set to a value of at least 32 characters. "
        "Refusing to start with insecure or missing secret."
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 7 * 24 * 3600  # 7일
CALLER_JWT_EXPIRY_SECONDS = 2 * 3600  # caller token: 2시간 (worker job timeout 1800s + 여유)
AUTH_COOKIE_NAME = os.environ.get("AUTH_COOKIE_NAME", "hive_auth")
AUTH_COOKIE_SAMESITE = os.environ.get("AUTH_COOKIE_SAMESITE", "strict")


def _normalize_email_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        email = str(value).strip().lower()
        if not email or email in seen:
            continue
        normalized.append(email)
        seen.add(email)
    return normalized


def _emails_from_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return _normalize_email_list([e for e in raw.split(",") if e.strip()])


def _load_whitelist() -> list[str]:
    """AUTH_WHITELIST_EMAILS env(콤마 구분) — ConfigMap이 정본."""
    return _emails_from_env("AUTH_WHITELIST_EMAILS")


def load_admins() -> list[str]:
    """AUTH_ADMIN_EMAILS env(콤마 구분) — ConfigMap이 정본."""
    return _emails_from_env("AUTH_ADMIN_EMAILS")


def _normalize_email(email: str | None) -> str:
    """단일 이메일 정규화 (strip+lower) — whitelist/admin 목록(_normalize_email_list)과
    principal email 비교를 대소문자 무관하게 일치시킨다. INFRA-ISSUE-322.
    """
    return str(email or "").strip().lower()


def is_admin_email(email: str | None) -> bool:
    if not email:
        return False
    return _normalize_email(email) in set(load_admins())


def _profile_override(email: str | None) -> dict[str, str | None]:
    """user_settings 의 표시용 override(display_name/avatar). 순환 import 회피용 지연 로드."""
    if not email:
        return {"display_name": None, "avatar": None}
    from .entities.user_settings import profile_override

    return profile_override(email)


def _make_jwt(email: str, name: str, picture: str) -> str:
    payload = {
        "sub": email,
        "name": name,
        "picture": picture,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _record_login(email: str, name: str, ip: str, user_agent: str, success: bool, reason: str | None = None):
    from .storage import auth_repo
    try:
        auth_repo.record_login(
            email=email, name=name, ip=ip, user_agent=user_agent,
            success=success, reason=reason,
            ts=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        # auth 흐름이 DB 실패로 막히지 않도록 best-effort. 로그인 자체는 그대로 진행한다.
        log.warning(
            "[auth] login audit insert 실패 email=%s success=%s: %s",
            email, success, exc,
        )


def verify_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def make_caller_jwt(principal, *, expiry_seconds: int = CALLER_JWT_EXPIRY_SECONDS) -> str:
    """Worker/system principal에 대한 단명 JWT 발급."""
    payload = principal.to_claims()
    payload.update({
        "iat": int(time.time()),
        "exp": int(time.time()) + expiry_seconds,
    })
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_caller_jwt(token: str):
    """Caller token 디코드. principal_type claim 없으면 caller token 아님 → None."""
    from .principal import Principal
    if not token:
        return None
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if "principal_type" not in claims:
        return None
    return Principal.from_claims(claims)


def _extract_bearer_token(header_value: str | None) -> str | None:
    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value[7:].strip()
    return token or None


def _request_token(request: Request) -> str | None:
    bearer = _extract_bearer_token(request.headers.get("Authorization"))
    if bearer:
        return bearer
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "").strip()
    return cookie_token or None


def request_auth_payload(request: Request) -> dict | None:
    return verify_jwt(_request_token(request))


def _cookie_secure(request: Request) -> bool:
    mode = os.environ.get("AUTH_COOKIE_SECURE_MODE", "auto").strip().lower()
    if mode == "always":
        return True
    if mode == "never":
        return False
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    cf_visitor = request.headers.get("CF-Visitor", "").strip()
    if '"scheme":"https"' in cf_visitor or '"scheme": "https"' in cf_visitor:
        return True
    return request.url.scheme == "https"


def _set_auth_cookie(response: Response, request: Request, token: str):
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite=AUTH_COOKIE_SAMESITE,
        max_age=JWT_EXPIRY_SECONDS,
        path="/",
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        samesite=AUTH_COOKIE_SAMESITE,
    )


# --- Endpoints ---


class LoginRequest(BaseModel):
    credential: str


@router.post("/auth.login")
async def auth_login(body: LoginRequest, request: Request, response: Response):
    ip = request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")
    ua = request.headers.get("User-Agent", "")

    # 1. Google ID Token 검증
    try:
        idinfo = id_token.verify_oauth2_token(
            body.credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except Exception as e:
        _record_login("unknown", "", ip, ua, False, reason=str(e))
        return {"status": "error", "error_code": "invalid_token", "message": str(e)}

    email = _normalize_email(idinfo.get("email"))
    name = idinfo.get("name", "")

    if not idinfo.get("email_verified"):
        _record_login(email, name, ip, ua, False, reason="email_not_verified")
        return {"status": "error", "error_code": "email_not_verified", "message": "이메일 인증이 필요합니다."}

    # 2. Whitelist 확인
    allowed = _load_whitelist()
    if email not in allowed:
        _record_login(email, name, ip, ua, False, reason="not_allowed")
        return {"status": "error", "error_code": "not_allowed", "message": "접근 권한이 없습니다."}

    # 3. JWT 발급
    token = _make_jwt(
        email=email,
        name=name,
        picture=idinfo.get("picture", ""),
    )

    _record_login(email, name, ip, ua, True)

    _set_auth_cookie(response, request, token)

    override = _profile_override(email)
    return {
        "status": "ok",
        "data": {
            "user": {
                "email": email,
                "name": override["display_name"] or name,
                "picture": override["avatar"] or idinfo.get("picture", ""),
                "is_admin": is_admin_email(email),
            },
        },
    }


@router.post("/auth.verify")
async def auth_verify(request: Request):
    payload = request_auth_payload(request)
    if payload is None:
        return {"status": "error", "error_code": "missing_token", "message": "토큰이 필요합니다."}

    override = _profile_override(payload["sub"])
    return {
        "status": "ok",
        "data": {
            "email": payload["sub"],
            "name": override["display_name"] or payload.get("name", ""),
            "picture": override["avatar"] or payload.get("picture", ""),
            "is_admin": is_admin_email(payload.get("sub")),
        },
    }


@router.post("/auth.refresh")
async def auth_refresh(request: Request, response: Response):
    """유효한 console JWT를 새 JWT로 갱신.

    sandbox bootstrap이나 갱신 daemon이 만료 전 호출해 .mcp.json 토큰을 fresh하게 유지한다.
    만료된 JWT는 재갱신 불가 — 사용자 재인증(/auth.login) 필요.
    """
    payload = request_auth_payload(request)
    if payload is None:
        return {"status": "error", "error_code": "unauthorized", "message": "유효한 토큰이 필요합니다."}

    email = _normalize_email(payload.get("sub"))
    if not email:
        return {"status": "error", "error_code": "invalid_token", "message": "토큰에서 이메일을 읽을 수 없습니다."}

    allowed = _load_whitelist()
    if email not in allowed:
        return {"status": "error", "error_code": "not_allowed", "message": "접근 권한이 없습니다."}

    name = payload.get("name", "")
    picture = payload.get("picture", "")
    token = _make_jwt(email=email, name=name, picture=picture)
    _set_auth_cookie(response, request, token)

    override = _profile_override(email)
    return {
        "status": "ok",
        "data": {
            "token": token,
            "expires_in": JWT_EXPIRY_SECONDS,
            "user": {
                "email": email,
                "name": override["display_name"] or name,
                "picture": override["avatar"] or picture,
                "is_admin": is_admin_email(email),
            },
        },
    }


@router.post("/auth.logout")
async def auth_logout(response: Response):
    clear_auth_cookie(response)
    return {"status": "ok", "data": {"logged_out": True}}


@router.post("/auth.login_history")
async def auth_login_history(request: Request):
    if request_auth_payload(request) is None:
        return {"status": "error", "error_code": "unauthorized", "message": "인증이 필요합니다."}
    from .storage import auth_repo
    entries = auth_repo.list_recent(limit=100)
    return {"status": "ok", "data": {"entries": entries, "count": len(entries)}}


@router.post("/auth.config")
async def auth_config():
    return {
        "status": "ok",
        "data": {"google_client_id": GOOGLE_CLIENT_ID},
    }


class CallerTokenRequest(BaseModel):
    principal_type: str           # worker | system | cli
    principal_id: str             # 예: "worker:w-019dfd6b"
    cell_id: str | None = None
    issue_id: str | None = None
    session_type: str | None = None  # issue_progress | project_progress
    expiry_seconds: int | None = None


@router.post("/auth.caller_token")
async def auth_caller_token(body: CallerTokenRequest, request: Request):
    """Internal token으로 호출. caller token (JWT) 발급.

    Agent-loop이 worker job을 spawn하기 직전 이 endpoint를 호출해 워커 신원을 박은
    단명 JWT를 받아 worker 환경변수 HUB_CALLER_TOKEN으로 전달한다. 사람 console
    JWT는 별도 흐름(/auth.login).

    호출자는 system principal이어야 한다 — agent-loop(_AGENT_LOOP_TOKEN, type=system)·
    bootstrap(X-Internal-Token → system:bootstrap)만. cell에 묶인 worker/cli caller가
    자기 Bearer로 이 endpoint를 호출해 cell 없는 system 토큰이나 타 cell worker 토큰을
    발급받아 cell 격리를 우회하는 것을 차단한다(권한 상승 방지).

    actor_email은 의도적으로 받지 않는다 — 사람 신원은 검증된 Google ID Token 기반
    console JWT 경로에서만 박힌다. 여기서 받으면 audit_actions 기록 위조가 가능해진다.
    type=user도 같은 이유로 거부한다(console 경로 전용).
    """
    from .principal import Principal, PRINCIPAL_TYPES
    caller = getattr(request.state, "principal", None)
    if caller is None or caller.type != "system":
        return {
            "status": "error",
            "error_code": "forbidden",
            "message": "caller token 발급은 system principal 만 가능합니다.",
        }
    if body.principal_type not in PRINCIPAL_TYPES:
        return {
            "status": "error",
            "error_code": "invalid_principal_type",
            "message": f"principal_type은 {sorted(PRINCIPAL_TYPES)} 중 하나여야 합니다.",
        }
    if body.principal_type == "user":
        return {
            "status": "error",
            "error_code": "user_principal_forbidden",
            "message": "type=user 토큰은 console JWT 경로에서만 발급됩니다 (/auth.login).",
        }
    if not body.principal_id:
        return {"status": "error", "error_code": "missing_principal_id", "message": "principal_id가 필요합니다."}
    p = Principal(
        type=body.principal_type,
        id=body.principal_id,
        cell_id=body.cell_id,
        issue_id=body.issue_id,
        session_type=body.session_type,
    )
    expiry = body.expiry_seconds or CALLER_JWT_EXPIRY_SECONDS
    token = make_caller_jwt(p, expiry_seconds=expiry)
    return {
        "status": "ok",
        "data": {"token": token, "principal": p.to_claims(), "expires_in": expiry},
    }
