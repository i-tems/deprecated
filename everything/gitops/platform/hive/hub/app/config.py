"""경로·상수·상태 전이 규칙."""

import os
from pathlib import Path
from starlette.exceptions import HTTPException

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SHARED_DIR = Path(os.environ.get("SHARED_DIR", str(DATA_DIR / "shared")))

# --- Cell-independent (전역) ---
# action·inbox 는 셀 무관 글로벌 테이블이라 path 도 cells/{cell}/... 가 아닌 글로벌.
# storage.sql 의 글로벌 dispatch regex (`/data/(actions|inbox)/...`) 와 짝.
INBOX_DIR = DATA_DIR / "inbox"
ACTION_DIR = DATA_DIR / "actions"


# --- Cell-specific paths ---

class CellPaths:
    """Cell별 데이터 경로. request.state.cell_paths로 주입."""

    def __init__(self, cell_id: str):
        base = DATA_DIR / "cells" / cell_id
        self.cell_id = cell_id
        self.base = base
        self.home_dir = DATA_DIR / "cells" / cell_id
        self.home_path = f"data/cells/{cell_id}"
        self.project_file = base / "projects.jsonl"
        self.issue_file = base / "issues.jsonl"
        self.label_file = base / "labels.jsonl"
        self.initiative_file = base / "initiatives.jsonl"
        self.signal_dir = base / "signals"
        self.action_dir = base / "actions"
        self.event_dir = base / "events"

    def ensure_dirs(self):
        """Cell 데이터 디렉토리 생성."""
        self.base.mkdir(parents=True, exist_ok=True)
        self.home_dir.mkdir(parents=True, exist_ok=True)


def get_cell_paths(request) -> 'CellPaths':
    """request.state에서 CellPaths를 꺼냄. 없으면 에러."""
    paths = getattr(request.state, 'cell_paths', None)
    if paths is None:
        raise RuntimeError("cell_paths not set — X-Cell-Id header missing?")
    ensure_cell_access(request)
    return paths


def ensure_cell_access(request):
    """Console 요청의 Cell 접근 권한을 재검증한다."""
    if request.headers.get("X-Source", "") != "console":
        return

    from .auth import is_admin_email, request_auth_payload

    cell = getattr(request.state, "cell", None)
    if not cell:
        return

    payload = request_auth_payload(request) or {}
    user_email = str(payload.get("sub") or getattr(request.state, "user_email", "")).strip().lower()
    allowed_emails = {
        str(email).strip().lower()
        for email in (cell.get("allowed_emails") or [])
        if str(email).strip()
    }
    if is_admin_email(user_email) or user_email in allowed_emails:
        return

    raise HTTPException(status_code=403, detail=f"Cell '{cell.get('cell_id')}' access denied")


def accessible_cell_ids(request) -> list[str]:
    """호출자가 접근 가능한 cell_id 목록. user-scoped aggregate endpoint 용.

    Console (JWT) 호출자만 허용. admin email → 비-archived 전체, 그 외 → cell 의
    allowed_emails 매치. archived cell 은 항상 제외 (cell-scoped 미들웨어와 동일).
    """
    from .auth import is_admin_email, request_auth_payload
    from .storage import cells_repo

    if request.headers.get("X-Source", "") != "console":
        raise HTTPException(status_code=403, detail="aggregate endpoint requires console source")

    payload = request_auth_payload(request)
    if payload is None:
        raise HTTPException(status_code=401, detail="authentication required")
    user_email = str(payload.get("sub") or "").strip().lower()
    if not user_email:
        raise HTTPException(status_code=401, detail="authentication required")

    admin = is_admin_email(user_email)
    out: list[str] = []
    for cell in cells_repo.list_all():
        if cell.get("status") == "archived":
            continue
        cid = cell.get("cell_id")
        if not cid:
            continue
        if admin:
            out.append(cid)
            continue
        allowed = {
            str(e).strip().lower()
            for e in (cell.get("allowed_emails") or [])
            if str(e).strip()
        }
        if user_email in allowed:
            out.append(cid)
    return out


VALID_STATUSES = {"backlog", "todo", "running", "waiting", "cleanup", "done", "cancelled", "error"}

# Container (Project + Initiative) 5-status 모델. Issue 의 8-status worker 모델과 분리.
# backlog=parked(미픽업) / active=오케스트레이션(워커 픽업) / waiting=사람 대기로 parked
# (self-action 미픽업, pending 댓글 reply 만 픽업) / done=완료(terminal) / archive=폐기(terminal).
# waiting 은 active 워커가 사람에 막혔을 때(decompose 게이트 needs_human, 중간 방향 결정,
# auto-confirm 불가한 완료 추천) 진입 — agent-loop 의 self-progress 재invoke 루프를 끊는다.
VALID_CONTAINER_STATUSES = {"backlog", "active", "waiting", "done", "archive"}

