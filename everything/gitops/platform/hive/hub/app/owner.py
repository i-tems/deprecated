"""Owner resolution through entity inheritance chains."""

from pathlib import Path

from fastapi import Request

from .storage import find_entity


def resolve_me_alias(owner: str | None, request: Request) -> str | None:
    """``owner="me"`` 단축형을 호출자 이메일로 치환. Linear MCP `assignee: "me"` 패턴.

    JWT principal 의 email (request.state.user_email) 로 풀어준다. agent worker /
    LLM 이 자기 이메일을 모를 때 owner 를 직접 지정 가능. ``"me"`` 가 아닌 입력은
    그대로 통과.

    호출자 이메일이 없으면(actor_email 없는 system principal 등) ``"me"`` 는
    해석 불가이므로 ``None`` 을 돌려준다 — 리터럴 ``"me"`` 를 흘려보내면 truthy
    문자열이 그대로 owner 로 저장되기 때문. ``None`` 이면 create 경로가 미할당으로
    둔다 (자동화 생성은 미할당, console 사람 생성은 user_email fallback 으로 자기할당).
    """
    if owner != "me":
        return owner
    return getattr(request.state, "user_email", None)


def resolve_owner(entity: dict, entity_type: str,
                  projects: list[dict] | None = None,
                  *, project_file: Path) -> str | None:
    """owner 상속. Issue 는 자기 Project 의 owner 까지 한 단 추적.

    list 호출 시 미리 로드한 projects 를 전달하면 N+1 방지.
    """
    if entity.get("owner"):
        return entity["owner"]
    if entity_type != "issue":
        return None
    project_id = entity.get("project_id")
    if not project_id:
        return None
    if projects is not None:
        project = next((g for g in projects if g.get("project_id") == project_id), None)
    else:
        _, project = find_entity(project_file, "project_id", project_id)
    if project and project.get("owner"):
        return project["owner"]
    return None
