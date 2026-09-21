"""X-Cell-Id 헤더에서 Cell을 식별하고 request.state.cell_paths를 주입하는 미들웨어."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import CellPaths
from .auth import is_admin_email, request_auth_payload
from .storage import cells_repo

# Cell 식별이 필요 없는 전역 경로
CELL_EXEMPT_PREFIXES = (
    "/cell.",
    "/auth.",
    "/capability.",
    "/user.settings",
    "/user.directory",
    "/argocd/",
    # MCP transport — outer 요청(initialize / tools.list / tools.call)은 cell-agnostic.
    # cell 결정은 mcp_server._invoke_internal 의 in-process dispatch 시 invoke 인자가
    # X-Cell-Id 헤더로 변환돼 inner request 에서 발생 (그 inner request 는 본 미들웨어
    # 다시 통과 — cell 결정·권한 enforcement 정상).
    "/mcp/",
)

CELL_EXEMPT_PATHS = {
    "/health",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/redoc",
    # User-scoped aggregate endpoints. 핸들러가 accessible_cell_ids(request) 로
    # JWT sub email 기준 접근 가능한 cell 들을 결정 — 미들웨어의 단일 cell 강제 우회.
    "/inbox.list_all",
    "/signal.list_all",
    "/issue.list_all",
    "/project.list_all",
    "/initiative.list_all",
    # SSE 스트림. EventSource 는 X-Cell-Id 헤더를 못 보내므로 미들웨어 우회 후
    # sse.py 핸들러가 query param cell_id + 쿠키로 in-handler 접근 검증
    # (CellMiddleware console 분기와 동일 규칙).
    "/sse.subscribe",
    # Gitea cell webhook callback. cell_id 는 payload 의 repository.html_url 로
    # _cell_id_for_repo_url 에서 도출 — 헤더로 받지 않음.
    "/deployment.notify_push",
    "/itemflow.notify",
    # GitHub→Gitea mirror-sync relay. cell_id 와 무관 (path 의 query param 으로
    # gitea owner/repo 받음).
    "/cell.github_push",
    # GitHub push → git_push_router 디스패치. cell_id 와 무관 (payload repo 로
    # 라우트 매칭). HMAC 은 핸들러 자체 검증.
    "/git.github_push",
}


class CellMiddleware(BaseHTTPMiddleware):
    """X-Cell-Id 헤더로 Cell을 식별, request.state에 cell_id·cell_paths 주입.

    Cell-exempt 경로(cell.*, auth.*, inbox.* 등)는 건너뛴다.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in CELL_EXEMPT_PATHS:
            return await call_next(request)
        for prefix in CELL_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # 인증 전 cell 존재 여부를 노출하지 않는다.
        source = request.headers.get("X-Source", "")
        if source == "console" and request_auth_payload(request) is None:
            return JSONResponse(
                status_code=401,
                content={
                    "status": "error",
                    "error_code": "unauthorized",
                    "message": "인증이 필요합니다.",
                },
            )

        # cell_id 결정 규칙:
        # - worker / cli: token claim에 cell_id가 박혀 있어야 한다. 헤더 무시(미스매치는 거부).
        # - system: 다중 셀 순회용(agent-loop 등). token에 cell_id 없을 때 X-Cell-Id 헤더 허용.
        # - user(console) / 미인증: console 경로에서만 X-Cell-Id 헤더 허용 (allowed_emails 검증은 아래).
        principal = getattr(request.state, "principal", None)
        header_cell = request.headers.get("X-Cell-Id")
        cell_id: str | None = None
        if principal and principal.cell_id:
            cell_id = principal.cell_id
            if header_cell and header_cell != principal.cell_id:
                return JSONResponse(
                    status_code=403,
                    content={
                        "status": "error",
                        "error_code": "cell_id_mismatch",
                        "message": "X-Cell-Id 헤더가 caller token의 cell_id와 다릅니다.",
                    },
                )
        elif principal and principal.type in ("system",):
            cell_id = header_cell
        elif source == "console":
            cell_id = header_cell
        elif principal and principal.type in ("worker", "cli"):
            return JSONResponse(
                status_code=403,
                content={
                    "status": "error",
                    "error_code": "cell_id_missing_in_token",
                    "message": f"{principal.type} caller token에 cell_id가 없습니다. token 발급 시 cell_id를 명시하세요.",
                },
            )

        if not cell_id:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "error_code": "cell_id_required",
                    "message": "cell_id가 필요합니다 (caller token claim 또는 console 경로의 X-Cell-Id 헤더).",
                },
            )

        # Cell 존재 확인
        cell = cells_repo.get(cell_id)
        if not cell:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "error_code": "cell_not_found",
                    "message": f"Cell '{cell_id}'을(를) 찾을 수 없습니다.",
                },
            )

        if cell.get("status") == "archived":
            return JSONResponse(
                status_code=403,
                content={
                    "status": "error",
                    "error_code": "cell_archived",
                    "message": f"Cell '{cell_id}'은(는) 아카이브 상태입니다.",
                },
            )

        if source == "console":
            payload = request_auth_payload(request) or {}
            user_email = str(payload.get("sub", "")).strip().lower()
            allowed_emails = {
                str(email).strip().lower()
                for email in (cell.get("allowed_emails") or [])
                if str(email).strip()
            }
            if not is_admin_email(user_email) and allowed_emails and user_email not in allowed_emails:
                return JSONResponse(
                    status_code=403,
                    content={
                        "status": "error",
                        "error_code": "cell_forbidden",
                        "message": f"Cell '{cell_id}'에 접근할 권한이 없습니다.",
                    },
                )

        # request.state에 주입
        paths = CellPaths(cell_id)
        paths.ensure_dirs()
        request.state.cell_id = cell_id
        request.state.cell = cell
        request.state.cell_paths = paths
        request.state.session_id = request.headers.get("X-Session-Id")

        return await call_next(request)
