import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse
from ..registry import REGISTRY

router = APIRouter()

# app 참조는 __init__.py에서 주입
_app_ref = None


def set_app_ref(app):
    global _app_ref
    _app_ref = app


def _collect_local_capabilities() -> list[dict]:
    capabilities = []
    skip = {"/health", "/openapi.json", "/docs", "/redoc", "/capability.list", "/capability.describe"}
    for route in _app_ref.routes:
        path = getattr(route, "path", None)
        if not path or path in skip:
            continue
        methods = getattr(route, "methods", set())
        if "POST" not in methods:
            continue
        # proxy route 제외 (path parameter 포함)
        if "{" in path:
            continue
        # OpenAPI 확장 메타데이터 추출
        extra = getattr(route, "openapi_extra", None) or {}
        cap = {
            "id": path.lstrip("/"),
            "path": path,
            "service": "hub",
            "description": getattr(route, "description", None) or (route.endpoint.__doc__ or "").strip() if hasattr(route, "endpoint") else None,
            "side_effects": extra.get("x-side-effects", "mutates"),
            "requires_approval": extra.get("x-requires-approval", False),
            "usage": extra.get("x-usage"),
        }
        capabilities.append(cap)
    return capabilities


async def _fetch_remote_capabilities() -> list[dict]:
    caps = []
    async with httpx.AsyncClient(timeout=5) as client:
        for svc in REGISTRY.values():
            try:
                resp = await client.get(f"{svc.base_url}/openapi.json")
                spec = resp.json()
                for path, methods in spec.get("paths", {}).items():
                    if "post" not in methods:
                        continue
                    endpoint_id = path.lstrip("/")
                    if endpoint_id == "health":
                        continue
                    post = methods["post"]
                    summary = post.get("summary", "")
                    description = post.get("description", summary)
                    caps.append({
                        "id": endpoint_id,
                        "path": path,
                        "service": svc.service_id,
                        "description": description,
                        "side_effects": post.get("x-side-effects", "mutates"),
                        "requires_approval": post.get("x-requires-approval", False),
                        "usage": post.get("x-usage"),
                    })
                    # cache for registry
                svc.capabilities = caps
            except httpx.HTTPError:
                continue
    return caps


class CapabilityListRequest(BaseModel):
    domain: list[str] | None = None  # e.g. ["project", "issue", "sandbox"]


class CapabilityDescribeRequest(BaseModel):
    ids: list[str]  # e.g. ["sandbox.create", "project.create"]


def _filter_by_domain(caps: list[dict], domains: list[str]) -> list[dict]:
    return [c for c in caps if c["id"].split(".")[0] in domains]


def _resolve_ref(ref: str, schemas: dict) -> dict:
    """$ref 문자열을 실제 스키마로 해석. 1단계 중첩까지 인라인."""
    name = ref.rsplit("/", 1)[-1]
    schema = schemas.get(name, {})
    if "properties" not in schema:
        return schema
    resolved = dict(schema)
    props = {}
    for k, v in schema.get("properties", {}).items():
        if "$ref" in v:
            props[k] = _resolve_ref(v["$ref"], schemas)
        elif v.get("anyOf"):
            # nullable 패턴: [{"$ref": ...}, {"type": "null"}] 또는 [{"type": ...}, {"type": "null"}]
            non_null = [a for a in v["anyOf"] if a.get("type") != "null"]
            if len(non_null) == 1 and "$ref" in non_null[0]:
                inner = _resolve_ref(non_null[0]["$ref"], schemas)
                inner["nullable"] = True
                for field in ("title", "description"):
                    if field in v:
                        inner[field] = v[field]
                props[k] = inner
            else:
                props[k] = v
        elif v.get("items", {}).get("$ref"):
            items_resolved = _resolve_ref(v["items"]["$ref"], schemas)
            props[k] = {**v, "items": items_resolved}
        else:
            props[k] = v
    resolved["properties"] = props
    return resolved


def _extract_request_schema(path_item: dict, schemas: dict) -> dict | None:
    """OpenAPI path item에서 request body 스키마를 추출·해석."""
    post = path_item.get("post", {})
    ref = (
        post
        .get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref")
    )
    if not ref:
        return None
    return _resolve_ref(ref, schemas)


@router.post("/capability.list")
async def capability_list(
    request: Request,
    body: CapabilityListRequest = CapabilityListRequest(),
) -> CapabilityResponse:
    """등록된 capability(API 엔드포인트) 목록을 동적으로 반환. 로컬 + 리모트 집계.
    domain 파라미터로 필터링 가능 (미지정 시 전체 반환).

    """
    local = _collect_local_capabilities()
    remote = await _fetch_remote_capabilities()
    all_caps = local + remote
    if body.domain:
        all_caps = _filter_by_domain(all_caps, body.domain)
    all_caps.sort(key=lambda c: c["id"])
    return CapabilityResponse(status="ok", data={"capabilities": all_caps, "count": len(all_caps)})


@router.post("/capability.describe")
async def capability_describe(
    body: CapabilityDescribeRequest,
    request: Request,
) -> CapabilityResponse:
    """선택한 capability의 요청 파라미터 스키마를 반환. Planning 후 Execution 전에 호출."""
    # 로컬 OpenAPI spec
    local_spec = _app_ref.openapi()
    local_schemas = local_spec.get("components", {}).get("schemas", {})
    local_paths = local_spec.get("paths", {})

    # 리모트 spec 캐시 (서비스별 1회 fetch)
    remote_specs: dict[str, dict] = {}

    result = {}
    missing = []

    for cap_id in body.ids:
        path = f"/{cap_id}"

        # 로컬에서 찾기
        if path in local_paths:
            post = local_paths[path].get("post", {})
            schema = _extract_request_schema(local_paths[path], local_schemas)
            result[cap_id] = {
                "description": post.get("description", post.get("summary", "")),
                "parameters": schema,
            }
            continue

        # 리모트에서 찾기
        from ..registry import find_service_for
        svc = find_service_for(cap_id)
        if not svc:
            missing.append(cap_id)
            continue

        if svc.service_id not in remote_specs:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"{svc.base_url}/openapi.json")
                    remote_specs[svc.service_id] = resp.json()
            except httpx.HTTPError:
                missing.append(cap_id)
                continue

        spec = remote_specs[svc.service_id]
        r_schemas = spec.get("components", {}).get("schemas", {})
        r_paths = spec.get("paths", {})

        if path in r_paths:
            schema = _extract_request_schema(r_paths[path], r_schemas)
            post = r_paths[path].get("post", {})
            result[cap_id] = {
                "description": post.get("description", post.get("summary", "")),
                "parameters": schema,
            }
        else:
            missing.append(cap_id)

    data = {"capabilities": result}
    if missing:
        data["not_found"] = missing
    return CapabilityResponse(status="ok", data=data)
