"""Per-cycle 컨텍스트 조립.

지시·절차·계약은 코드가 아니라 claude CLI 가 자동 로드한다 (runtime.py 의
claude_code preset + setting_sources=["user","project"] + skills="all"):

- `~/.claude/CLAUDE.md` (HOME=/data/shared, hive sync) — 비협상 계약 + 항상 적용 규칙 (ruler 가 rules 를 concatenate; 별도 rules/*.md 없음)
- `~/.claude/skills/{processing-issues,processing-projects}/SKILL.md` — 절차 (native 자동탐색·자동호출)
- `<cwd>/.claude/` (cell repo) — cell 지시 (project-level)

이 모듈은 그 자동 로드로 표현 불가능한 **런타임 데이터만** 담당한다:

- `build_runtime_append`: entity 수명 동안 불변인 런타임 사실 (hub URL 등).
  system_prompt preset 의 append 로 들어가 prompt cache prefix 로 쓰인다.
- `build_issue_progress` / `build_project_progress`: 매 cycle 의 entity slim JSON
  (+ project/자식) user prompt — 동적 부분.
"""

from __future__ import annotations

import json
import os

from .config import SPECS_ROOT


_GOAL_SLIM_FIELDS = (
    "project_id", "title", "intent", "description", "plan",
    "status", "priority",
    "dependencies", "resources",
    "initiative_id", "initiative",
)
_TASK_SLIM_FIELDS = (
    "issue_id", "title", "intent", "description", "plan", "status",
    "project_id", "priority", "capability", "dependencies", "model",
)
_INITIATIVE_SLIM_FIELDS = (
    "initiative_id", "name", "description", "status",
    "priority", "resources", "parent_initiative_id",
)

_SLIM_NOTE = (
    "아래 entity JSON 은 자주 쓰는 필드만 추린 slim 형태입니다. "
    "`pr_urls` 등 상세 필드가 필요하면 `issue.get` / `project.get` capability 로 drilldown 하세요."
)


def _slim(entity: dict, fields: tuple[str, ...]) -> dict:
    return {k: entity[k] for k in fields if entity.get(k) is not None}


class PromptFactory:
    def __init__(self, *, hub_url: str, specs_dir: str | None = None, runtime_specs_dir: str | None = None):
        # specs_dir / runtime_specs_dir 인자는 호출부 호환을 위해 남겨둔다 (미사용 —
        # 지시는 claude CLI 자동 로드).
        self.hub_url = hub_url

    # ── system_prompt append (entity 수명 동안 불변, cache prefix) ──

    def build_runtime_append(self, entity_type: str) -> str:
        """claude_code preset 에 append 될 런타임 사실. 계약·절차는 CLAUDE.md/rules/skill."""
        return (
            f"## Runtime\n"
            f"- Hub API Base URL: `{self.hub_url}`\n"
            f"- Execution Context: hive-loop\n"
            f"- Entity Type: {entity_type}\n"
            # cwd 는 cell repo. 하네스 정본(skill·계약이 가리키는 `specs/…`·`schemas/…`)은
            # HOME 직하에 sync 된다 — cwd 기준이 아니라 아래 절대경로로 읽어라.
            f"- 하네스 정본 경로: `specs/…` → `{SPECS_ROOT}/…`, "
            f"`schemas/…` → `{os.path.dirname(SPECS_ROOT)}/schemas/…` (cwd=cell repo 아님, HOME 직하).\n"
        )

    # ── 단일 progress user prompt (per-cycle 동적) ──

    def build_issue_progress(self, issue: dict, project: dict | None = None) -> str:
        """Issue user prompt — entity slim. 지시·계약은 CLAUDE.md/rules/SKILL 이 담당."""
        return self._entity_context(issue, "Issue", project=project if project else None)

    def build_project_progress(self, project: dict, *, issues: list[dict] | None = None) -> str:
        """Project user prompt — entity slim + 자식 Issue 상태."""
        slim_tasks = [_slim(t, _TASK_SLIM_FIELDS) for t in (issues or [])]
        children_block = f"## Issues\n```json\n{self._dump(slim_tasks)}\n```\n\n"
        return f"{self._entity_context(project, 'Project')}{children_block}"

    def build_initiative_progress(self, initiative: dict, *, projects: list[dict] | None = None) -> str:
        """Initiative user prompt — entity slim + 자식 Project 상태 (한 tier 위)."""
        slim_projects = [_slim(p, _GOAL_SLIM_FIELDS) for p in (projects or [])]
        children_block = f"## Projects\n```json\n{self._dump(slim_projects)}\n```\n\n"
        return f"{self._entity_context(initiative, 'Initiative')}{children_block}"

    # ── private ──

    def _entity_context(self, entity: dict, entity_type: str, project: dict | None = None) -> str:
        if entity_type == "Issue":
            slim = _slim(entity, _TASK_SLIM_FIELDS)
        elif entity_type == "Project":
            slim = _slim(entity, _GOAL_SLIM_FIELDS)
        elif entity_type == "Initiative":
            slim = _slim(entity, _INITIATIVE_SLIM_FIELDS)
        else:
            slim = {k: v for k, v in entity.items() if not k.startswith("_") and v is not None}
        sections = [f"{_SLIM_NOTE}\n", f"## {entity_type}\n```json\n{self._dump(slim)}\n```\n"]
        if project:
            sections.append(f"## Project\n```json\n{self._dump(_slim(project, _GOAL_SLIM_FIELDS))}\n```\n")
        return "\n".join(sections) + "\n"

    @staticmethod
    def _dump(obj) -> str:
        if not obj:
            return "(없음)"
        return json.dumps(obj, ensure_ascii=False, indent=2)
