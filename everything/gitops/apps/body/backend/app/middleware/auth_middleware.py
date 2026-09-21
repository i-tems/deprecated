from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth import decode_token

# Paths that don't require authentication
PUBLIC_PATHS = {"/api/health", "/api/auth/google", "/docs", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always pass OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for public paths and non-API routes
        if path in PUBLIC_PATHS or not path.startswith("/api/"):
            return await call_next(request)

        # /api/auth/me needs token
        # All /api/* except PUBLIC_PATHS need token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401, content={"detail": "Not authenticated"}
            )

        token = auth_header[7:]
        try:
            user_id = decode_token(token)
            request.state.user_id = user_id
        except Exception:
            return JSONResponse(
                status_code=401, content={"detail": "Invalid or expired token"}
            )

        return await call_next(request)
