"""리모트 capability 서비스 레지스트리.

환경변수에서 리모트 서비스를 등록하고, prefix 기반으로 라우팅을 결정한다.
어떤 capability를 활성화할지는 ConfigMap의 {SERVICE}_URL 환경변수로 선택.
"""

import os
from dataclasses import dataclass, field


@dataclass
class RemoteService:
    service_id: str
    base_url: str
    prefixes: list[str]  # 이 서비스가 담당하는 endpoint prefix (예: ["calendar"])
    timeout: int = 30  # 프록시 타임아웃 (초). {SERVICE}_TIMEOUT 환경변수로 설정
    capabilities: list[dict] = field(default_factory=list)


REGISTRY: dict[str, RemoteService] = {}


def load_registry():
    """환경변수에서 리모트 서비스 등록. 패턴: {SERVICE_ID}_URL + {SERVICE_ID}_PREFIXES."""
    # 잘 알려진 서비스들
    _register_from_env("GOOGLE", default_prefixes=["calendar"])
    _register_from_env("SLACK", default_prefixes=["slack"])
    _register_from_env("SCHEDULER", default_prefixes=["schedule"])
    _register_from_env("CONTAINER", default_prefixes=["sandbox"])
    _register_from_env("QUERY", default_prefixes=["query"])
    _register_from_env("WEB", default_prefixes=["web"])


def _register_from_env(env_key: str, default_prefixes: list[str]):
    url = os.environ.get(f"{env_key}_URL")
    if not url:
        return
    service_id = env_key.lower()
    prefixes_raw = os.environ.get(f"{env_key}_PREFIXES", "")
    prefixes = [p.strip() for p in prefixes_raw.split(",") if p.strip()] or default_prefixes
    timeout = int(os.environ.get(f"{env_key}_TIMEOUT", "30"))
    REGISTRY[service_id] = RemoteService(
        service_id=service_id,
        base_url=url,
        prefixes=prefixes,
        timeout=timeout,
    )


def find_service_for(endpoint: str) -> RemoteService | None:
    """endpoint (예: "calendar.fetch")에 매칭되는 리모트 서비스 반환."""
    prefix = endpoint.split(".")[0] if "." in endpoint else None
    if not prefix:
        return None
    for svc in REGISTRY.values():
        if prefix in svc.prefixes:
            return svc
    return None
