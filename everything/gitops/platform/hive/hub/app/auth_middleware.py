"""인증 미들웨어 — caller token 강제, bootstrap path만 예외.

인증 흐름:
1. `Authorization: Bearer <jwt>` — caller token이면 디코드해 principal 설정.
   console JWT(`X-Source=console`)면 사람 사용자로 처리.
2. **Bootstrap path** (`/auth.caller_token`) 한정: X-Internal-Token으로 인증 가능.
   첫 caller token을 발급받기 위한 chicken-and-egg 해결용. principal은
   system:bootstrap으로 합성. 다른 endpoint에서는 Bearer 필수.

토큰 미설정 시 시작 단계에서 RuntimeError.
"""

import os
import secrets as _secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .principal import Principal


SKIP_PATHS = {
    "/health",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/auth.login",
    "/auth.logout",
    "/auth.verify",
    "/auth.refresh",
    "/auth.config",
    "/auth.login_history",
    # SSE 스트림. EventSource 는 Authorization 헤더를 못 보내므로 미들웨어
    # 우회 후 sse.py 핸들러가 쿠키(AUTH_COOKIE_NAME)로 in-handler 인증.
    "/sse.subscribe",
    # Gitea cell repo webhook callback. HMAC-SHA256 으로 자체 검증 — caller-JWT 와 분리.
    "/deployment.notify_push",
    # itemflow(Airflow DAG)→cell slack. X-Itemflow-Token 자체 검증.
    "/itemflow.notify",
    # GitHub canonical repo 의 push webhook → Gitea mirror-sync 즉시 트리거 relay.
    # X-Hub-Signature-256 (HMAC-SHA256) 으로 자체 검증.
    "/cell.github_push",
    # GitHub push webhook → git_push_router 디스패치 (Gitea 미러 없는 repo,
    # 예: 하네스 i-tems/hive). X-Hub-Signature-256 으로 핸들러 자체 검증.
    "/git.github_push",
}

# Bootstrap 전용: caller token 발급. X-Internal-Token으로만 호출 가능.
BOOTSTRAP_PATHS = {"/auth.caller_token"}

HUB_INTERNAL_TOKEN = os.environ.get("HUB_INTERNAL_TOKEN", "").strip()
if not HUB_INTERNAL_TOKEN:
    raise RuntimeError(
        "HUB_INTERNAL_TOKEN is required. Set it in the hive-hub Secret to enable "
        "bootstrap caller_token issuance."
    )


_BOOTSTRAP_PRINCIPAL = Principal(type="system", id="system:bootstrap")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in SKIP_PATHS:
            return await call_next(request)

        # 1. Authorization: Bearer (caller token / console JWT)
        authz = request.headers.get("Authorization", "")
        if authz.startswith("Bearer "):
            token = authz[7:].strip()
            from .auth import verify_caller_jwt
            principal = verify_caller_jwt(token)
            if principal is not None:
                request.state.principal = principal
                if principal.actor_email:
                    request.state.user_email = principal.actor_email
                return await call_next(request)
            # principal_type 없는 JWT면 console JWT일 수 있음 → console 분기로

        # 2. Console JWT
        source = request.headers.get("X-Source", "")
        if source == "console":
            from .auth import request_auth_payload, _request_token

            payload = request_auth_payload(request)
            if payload is None:
                return JSONResponse(
                    status_code=401,
                    content={
                        "status": "error",
                        "error_code": "unauthorized",
                        "message": "인증이 필요합니다.",
                    },
                )
            email = payload["sub"]
            request.state.user_email = email
            request.state.auth_token = _request_token(request)
            request.state.principal = Principal(
                type="user",
                id=f"user:{email}",
                actor_email=email,
            )
            return await call_next(request)

        # 3. Bootstrap path 한정 X-Internal-Token (constant-time compare)
        if path in BOOTSTRAP_PATHS:
            provided = request.headers.get("X-Internal-Token", "")
            if provided and _secrets.compare_digest(provided, HUB_INTERNAL_TOKEN):
                request.state.principal = _BOOTSTRAP_PRINCIPAL
                return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={
                "status": "error",
                "error_code": "unauthorized",
                "message": "Authorization: Bearer <caller_token> 필요. /auth.caller_token에서 발급받으세요.",
            },
        )
