"""Cell 관리 — create·list·get·update."""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from capability_framework import CapabilityResponse
from pathlib import Path

from ..auth import _normalize_email_list, is_admin_email
from ..config import CellPaths
from ..storage import cells_repo
from ..storage.jsonl import entity_lock


def _cell_lock_path(cell_id: str) -> Path:
    """cells_repo가 SQL 백엔드라 파일 경로가 없지만 entity_lock의 sentinel은
    md5(str(path))로 키를 만들므로 임의 식별자로 충분하다."""
    return Path(f"cells/{cell_id}")

import logging

log = logging.getLogger("core.cell")

router = APIRouter()

VALID_CELL_STATUSES = {"active", "archived"}


# --- Models ---

class CellConfig(BaseModel):
    # extra='allow' — cell 운영 중 hub schema 에 명시되지 않은 field
    # (agent_url, exec_tier_default, exec_model_default, deploy_via_actions
    # 등) 가 cell record 에 누적되어 있다. extra 를 drop 하면 cell.update
    # 호출 시 그 field 들이 모두 사라져 agent_loop 등이 동작 불능.
    model_config = ConfigDict(extra="allow")

    allowed_capabilities: list[str] = ["*"]
    max_workers: int = 3
    poll_interval: int = 30
    max_hourly_cost_usd: float = 50.0
    max_daily_cost_usd: float = 500.0
    # FQDN 화이트리스트 — app meta 에서 networks[].host 로 박을 수 있는 public host.
    # admin 만 cell.update 로 갱신 가능 (다른 cell 도메인 squat 방지).
    allowed_public_hosts: list[str] = []
    # bus.publish 의 fan-out 대상 — 매칭되면 이 cell scope 로 signal.emit.
    # cell repo 의 cell.json 의 subscriptions 가 SoT. cell.github_push webhook
    # 시점에 hub 가 자동 sync. glob 패턴 (fnmatch) — 예: ["news.*", "market.kospi.*"]
    subscriptions: list[str] = []


class CellCreateRequest(BaseModel):
    cell_id: str | None = None  # None이면 name에서 자동 생성
    name: str
    description: str | None = None
    allowed_emails: list[str] | None = None
    config: CellConfig | None = None
    repo_url: str  # 필수. cell의 GitHub repo (knowledge·.claude·config 보관)


class CellListRequest(BaseModel):
    status: str | None = None  # None이면 전체


class CellGetRequest(BaseModel):
    cell_id: str


class CellUpdateRequest(BaseModel):
    cell_id: str
    name: str | None = None
    description: str | None = None
    status: str | None = None
    allowed_emails: list[str] | None = None
    config: CellConfig | None = None
    repo_url: str | None = None


def _to_kebab(name: str) -> str:
    """Name → kebab-case cell_id."""
    import re
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s


def _attach_home_path(cell: dict) -> dict:
    expected_home_path = f"data/cells/{cell['cell_id']}"
    current_home_path = cell.get("home_path")
    if (
        not current_home_path
        or current_home_path.startswith("~/share/")
    ):
        cell["home_path"] = expected_home_path
    cell["allowed_emails"] = _normalize_email_list(cell.get("allowed_emails") or [])
    return cell


def _request_user_email(request: Request) -> str | None:
    email = getattr(request.state, "user_email", None)
    if not email:
        return None
    return str(email).strip().lower()


def _is_console_request(request: Request) -> bool:
    return request.headers.get("X-Source", "") == "console"


def _require_admin(request: Request) -> CapabilityResponse | None:
    if not _is_console_request(request):
        return None
    email = _request_user_email(request)
    if is_admin_email(email):
        return None
    return CapabilityResponse(
        status="error",
        error_code="forbidden",
        message="관리자만 Cell을 생성하거나 변경할 수 있습니다.",
    )


def _can_access_cell(email: str | None, cell: dict) -> bool:
    if is_admin_email(email):
        return True
    allowed = set(_normalize_email_list(cell.get("allowed_emails") or []))
    return bool(email and email in allowed)


def _filter_cells_for_request(cells: list[dict], request: Request) -> list[dict]:
    if not _is_console_request(request):
        return cells
    email = _request_user_email(request)
    return [cell for cell in cells if _can_access_cell(email, cell)]


@router.post("/cell.create")
async def cell_create(req: CellCreateRequest, request: Request) -> CapabilityResponse:
    """Cell 생성. 데이터 디렉토리도 함께 생성."""
    forbidden = _require_admin(request)
    if forbidden:
        return forbidden
    cell_id = req.cell_id or _to_kebab(req.name)
    if not cell_id:
        return CapabilityResponse(
            status="error", error_code="invalid_cell_id",
            message="cell_id를 생성할 수 ��습니다. name을 확인하세요.",
        )

    if not req.repo_url or not req.repo_url.strip():
        return CapabilityResponse(
            status="error", error_code="invalid_repo_url",
            message="repo_url은 필수입니다. cell repo를 먼저 만들고 URL을 지정하세요.",
        )

    with entity_lock(_cell_lock_path(cell_id)):
        if cells_repo.get(cell_id):
            return CapabilityResponse(
                status="error", error_code="already_exists",
                message=f"cell '{cell_id}' already exists",
            )

        now = datetime.now(timezone.utc).isoformat()
        config = req.config or CellConfig()
        paths = CellPaths(cell_id)
        config_data = config.model_dump()
        record = {
            "cell_id": cell_id,
            "name": req.name,
            "description": req.description,
            "status": "active",
            "home_path": paths.home_path,
            "allowed_emails": _normalize_email_list(req.allowed_emails or []),
            "config": config_data,
            "repo_url": req.repo_url.strip(),
            "created_at": now,
            "updated_at": now,
        }

        cells_repo.upsert(record)

    # 데이터 디렉토리 생성 (락 밖)
    paths.ensure_dirs()

    return CapabilityResponse(status="ok", data=record)


@router.post("/cell.list")
def cell_list(req: CellListRequest, request: Request) -> CapabilityResponse:
    """Cell 목록 조회."""
    cells = cells_repo.list_all()
    if req.status:
        cells = [c for c in cells if c.get("status") == req.status]
    cells = _filter_cells_for_request(cells, request)
    for cell in cells:
        _attach_home_path(cell)
    return CapabilityResponse(status="ok", data={"cells": cells, "count": len(cells)})


@router.post("/cell.get")
def cell_get(req: CellGetRequest, request: Request) -> CapabilityResponse:
    """단일 Cell 상세 조회."""
    found = cells_repo.get(req.cell_id)
    if not found:
        return CapabilityResponse(
            status="error", error_code="not_found",
            message=f"cell '{req.cell_id}' not found",
        )
    if _is_console_request(request) and not _can_access_cell(_request_user_email(request), found):
        return CapabilityResponse(
            status="error",
            error_code="forbidden",
            message="이 Cell에 접근할 권한이 없습니다.",
        )
    _attach_home_path(found)
    return CapabilityResponse(status="ok", data=found)


@router.post("/cell.update")
async def cell_update(req: CellUpdateRequest, request: Request) -> CapabilityResponse:
    """Cell 설정 변경.

    [동시성] cells 는 단일-writer 설계 — admin 전용(_require_admin), 저빈도 레지스트리
    변경이다. in-pod entity_lock + 단일행 upsert(INSERT … ON DUPLICATE KEY UPDATE)로 쓰며
    엔티티와 달리 rev/CAS 가 없다. 워커 다중 동시 쓰기가 없어 cross-replica lost-update
    표면이 사실상 없고, 드문 동시 admin 편집의 RMW 경합만 허용한다(재편집으로 복구).
    엔티티(issue/project/initiative) 쓰기의 per-entity CAS 계약은 INFRA-ISSUE-319 /
    apply_entity_fields_and_persist 참조.
    """
    forbidden = _require_admin(request)
    if forbidden:
        return forbidden
    with entity_lock(_cell_lock_path(req.cell_id)):
        found = cells_repo.get(req.cell_id)
        if not found:
            return CapabilityResponse(
                status="error", error_code="not_found",
                message=f"cell '{req.cell_id}' not found",
            )

        if req.name is not None:
            found["name"] = req.name
        if req.description is not None:
            found["description"] = req.description
        if req.status is not None:
            if req.status not in VALID_CELL_STATUSES:
                return CapabilityResponse(
                    status="error", error_code="invalid_status",
                    message=f"invalid status: {req.status}. allowed: {VALID_CELL_STATUSES}",
                )
            found["status"] = req.status
        if req.allowed_emails is not None:
            found["allowed_emails"] = _normalize_email_list(req.allowed_emails)
        if req.config is not None:
            found["config"] = req.config.model_dump()
        if req.repo_url is not None:
            found["repo_url"] = req.repo_url
        merged_config = CellConfig(**(found.get("config") or {}))
        found["config"] = merged_config.model_dump()
        if found.get("status") != "archived":
            CellPaths(req.cell_id).ensure_dirs()
        found["updated_at"] = datetime.now(timezone.utc).isoformat()
        _attach_home_path(found)

        cells_repo.upsert(found)
    return CapabilityResponse(status="ok", data=found)
