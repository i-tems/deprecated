"""Shared data structures for the agent execution loop."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .hub_client import HubClient
    from .session_store import SessionStore


@dataclass
class Action:
    type: str  # progress (issue / project 공용 단일 phase)
    entity: dict | None = None
    priority: int = 99


@dataclass
class EntitySession:
    entity_id: str
    session_id: str | None = None
    use_count: int = 0
    provider: str | None = None
    last_prompt_at: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)


@dataclass
class WorkItem:
    """Coordinator -> Worker 전달 단위."""
    action: Action
    prompt: str
    session: EntitySession
    model: str | None = None
    provider: str = "claude"
    context: dict = field(default_factory=dict)


@dataclass
class WorkResult:
    """Worker -> Coordinator 결과."""
    work_item: WorkItem
    claude_result: dict


def action_entity_id(action: Action) -> str | None:
    if not action.entity:
        return None
    return (
        action.entity.get("issue_id")
        or action.entity.get("project_id")
        or action.entity.get("initiative_id")
    )


def id_field_for(entity_type: str) -> str:
    if entity_type == "issue":
        return "issue_id"
    if entity_type == "initiative":
        return "initiative_id"
    return "project_id"


def entity_type_of(entity: dict | None) -> str | None:
    """entity dict 에서 type 추론 — issue_id 우선, project_id, 아니면 initiative_id.

    순서 중요: Project 레코드는 부모 참조용 `initiative_id` 필드를 가지므로
    initiative 보다 project_id 를 먼저 본다 (오분류 방지). Initiative 레코드는
    issue_id/project_id 가 없고 initiative_id 만 있다.
    """
    if not entity:
        return None
    if "issue_id" in entity:
        return "issue"
    if "project_id" in entity:
        return "project"
    if "initiative_id" in entity:
        return "initiative"
    return None


def session_type_of(entity: dict | None) -> str | None:
    """단일 progress phase 의 session_type — 'issue_progress'/'project_progress'/'initiative_progress'."""
    et = entity_type_of(entity)
    return f"{et}_progress" if et else None


def is_api_ok(resp: dict | None) -> bool:
    return resp is not None and resp.get("status") == "ok"


# hub 재시작/롤아웃으로 MCP streamable-HTTP 세션이 무효화되면 worker 의 영구 MCP
# 클라이언트는 재핸드셰이크하지 않아 이후 모든 mcp__* 툴 호출이 아래 시그니처로
# 영구 실패한다 (in-process 복구 불가). LLM 의 유일한 시스템 반영 경로(capability
# 호출)가 죽으므로 worker 가 non-zero exit → K8s Job(restartPolicy=Never,
# backoffLimit=3) 이 fresh pod 를 재기동, resume_session_id 로 같은 claude 대화를
# 이어가되 새 MCP 세션으로 자동 복구한다.
# 실측 시그니처(2026-05-17 NESS-ISSUE-4):
#   Streamable HTTP error: ... {"jsonrpc":"2.0",...,"error":{"code":-32600,
#   "message":"Session not found"}}
# 실측 시그니처(2026-05-23 INFRA-ISSUE-83):
#   MCP server "hive-beauty" is not connected
_MCP_TRANSPORT_DEAD_MARKERS = ("Session not found", "-32600", "Streamable HTTP error",
                               "is not connected")


def mcp_transport_dead(content: Any) -> bool:
    """MCP tool result content 가 '세션 영구 무효' 시그니처를 담고 있는지.

    content 는 SDK ToolResultBlock.content — str 이거나 {"text": ...} block
    리스트일 수 있다. 둘 다 평탄화해 마커 부분일치로 판정한다.
    """
    if content is None:
        return False
    if isinstance(content, str):
        text = content
    elif isinstance(content, (list, tuple)):
        text = " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    else:
        text = str(content)
    return any(marker in text for marker in _MCP_TRANSPORT_DEAD_MARKERS)


@dataclass
class LoopContext:
    """phase_handlers가 사용하는 공유 의존성."""
    client: HubClient
    session_store: SessionStore
    prompt_factory: Any
    resolve_model: Callable[[str], str]
    log: Any
    exec_tier_default: str
    log_usage: Callable
