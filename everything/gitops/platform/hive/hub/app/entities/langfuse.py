"""Langfuse 트레이스 deep-link 헬퍼.

cell repo `cell.json` 의 `langfuse` 섹션에서 host/public_key/secret_key/project_id 를
읽고 deep-link URL 을 만든다. project_id 가 없으면 Langfuse `/api/public/projects` 로
1회 조회만 하고 메모리 캐시에 두며, cell.json 에 다시 쓰지 않는다 (cell repo 가 정본).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse
from .. import cell_config

router = APIRouter()

# (host, public_key, secret_key) → project_id
_PROJECT_ID_CACHE: dict[tuple[str, str, str], str] = {}


def _fetch_project_id(host: str, public_key: str, secret_key: str) -> str | None:
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/public/projects",
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    projects = data.get("data") or []
    if not projects:
        return None
    return str(projects[0].get("id") or "") or None


class LangfuseUrlRequest(BaseModel):
    session_id: str | None = None  # 단일 세션 트레이스 deep-link
    entity_id: str | None = None   # entity 전체 traces deep-link (metadata.entity_id 필터)
    # entity_type 은 metadata 에 들어 있으나 entity_id 만으로 충분히 unique (uuid7).


@router.post("/langfuse.url")
async def langfuse_url(req: LangfuseUrlRequest, request: Request) -> CapabilityResponse:
    """셀의 Langfuse 프로젝트 / 세션 deep-link URL 반환."""
    cell_id = (request.headers.get("X-Cell-Id") or "").strip()
    if not cell_id:
        return CapabilityResponse(status="error", error_code="cell_id_required", message="X-Cell-Id 헤더 필요")
    config = cell_config.get(cell_id, "langfuse")
    if not config:
        return CapabilityResponse(status="error", error_code="not_configured", message="Langfuse 설정 없음")
    host = str(config.get("host") or "").strip().rstrip("/")
    public_key = str(config.get("public_key") or "").strip()
    secret_key = str(config.get("secret_key") or "").strip()
    if not (host and public_key and secret_key):
        return CapabilityResponse(status="error", error_code="not_configured", message="host/public_key/secret_key 누락")

    project_id = str(config.get("project_id") or "").strip()
    if not project_id:
        cache_key = (host, public_key, secret_key)
        project_id = _PROJECT_ID_CACHE.get(cache_key) or _fetch_project_id(host, public_key, secret_key) or ""
        if project_id:
            _PROJECT_ID_CACHE[cache_key] = project_id

    if not project_id:
        return CapabilityResponse(status="ok", data={"url": host})

    if req.session_id:
        url = f"{host}/project/{project_id}/sessions/{req.session_id}"
    elif req.entity_id:
        # Langfuse traces 필터 deep-link: column;type;key;operator;value
        # agent runtime 이 모든 generation 에 metadata.entity_id 를 박는다.
        encoded_value = urllib.parse.quote(req.entity_id, safe="")
        filter_str = f"metadata;stringObject;entity_id;contains;{encoded_value}"
        filter_param = urllib.parse.quote(filter_str, safe="")
        url = f"{host}/project/{project_id}/traces?filter={filter_param}"
    else:
        url = f"{host}/project/{project_id}"
    return CapabilityResponse(status="ok", data={"url": url, "host": host, "project_id": project_id})
