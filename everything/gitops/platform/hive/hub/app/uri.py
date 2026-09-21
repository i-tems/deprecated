"""Resource URI normalization."""

import logging
from datetime import datetime, timezone

from .config import DATA_DIR

log = logging.getLogger("hub.uri")

_DATA_PREFIX = f"{str(DATA_DIR).rstrip('/')}/"


def normalize_resource_uri(uri: str) -> str:
    """로컬 경로를 hive root 기준 상대경로(data/...)로 정규화."""
    if uri.startswith(_DATA_PREFIX):
        return "data/" + uri[len(_DATA_PREFIX):]
    return uri


def normalize_resources(resources: list[dict]) -> list[dict]:
    """resources 정규화 + 같은 uri 중복 제거 (처음 1건만 유지).

    `resources` 는 외부 리소스(URL, API endpoint, 외부 문서 링크) 전용.
    자기 space 내부 산출물은 `issue.get`/`project.get` 응답의 derived `artifacts`
    필드로 자동 노출되므로 resources 에 등록할 필요가 없다. space 내부 path /
    `blob/issue/*` 같은 entity-branch blob (PR 머지 후 stale) URI 가 들어오면
    경고 emit — 거부는 spec 머지 후 별도 PR.
    """
    now = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in resources:
        if "uri" in r:
            r["uri"] = normalize_resource_uri(r["uri"])
        if not r.get("created_at"):
            r["created_at"] = now
        uri = r.get("uri")
        if uri and uri in seen:
            log.warning("[normalize_resources] duplicate uri dropped: %s", uri)
            continue
        if uri:
            seen.add(uri)
            _maybe_warn_space_uri(uri)
        deduped.append(r)
    return deduped


def _maybe_warn_space_uri(uri: str) -> None:
    """space 내부 path 또는 entity-branch blob URI 면 경고."""
    if uri.startswith("data/"):
        log.warning("[normalize_resources] space-internal path in resources (use artifacts): %s", uri)
        return
    if "/blob/issue/" in uri or "/blob/project/" in uri:
        log.warning("[normalize_resources] entity-branch blob URL in resources (stale after merge): %s", uri)
