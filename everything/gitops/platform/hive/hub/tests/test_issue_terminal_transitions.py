"""issue `terminal_transition_denied` 종결 전이 가드 회귀 테스트.

모든 종결(done·cancelled)은 cleanup 경유 강제 (project_issue_model.md §2):
  - done 은 cleanup 에서만 — 그 외 출발 상태는 거부.
  - cancelled 도 cleanup 에서만 — backlog/todo 의 cold-cancel 직행을 포함해 거부
    (옛 `_CANCEL_DIRECT_FROM = {backlog, todo, cleanup}` 허용을 제거, INFRA-ISSUE-166).
  - 운영자·error 복구 우회는 issue.force_update (가드 미적용) — 본 함수 범위 밖.

hub 테스트 규약상 app 패키지(capability_framework 런타임 의존)를 import 하지 않는다.
대신 순수 함수 `terminal_transition_denied` 소스를 ast 로 추출해 격리 exec 한 뒤
동작을 검증한다 (test_container_waiting_transitions 와 동일 패턴).
"""

import ast
import unittest
from pathlib import Path

_ENT_INIT = Path(__file__).resolve().parents[1] / "app" / "entities" / "__init__.py"


def _extract_func(path: Path, name: str, *, inject: dict | None = None):
    """모듈 소스에서 함수 def 한 개만 추출해 격리 namespace 에 exec, 콜러블 반환."""
    src = path.read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(src, node)
            ns: dict = dict(inject or {})
            exec(seg, ns)
            return ns[name]
    raise AssertionError(f"{name} not found in {path}")


# 모듈 상수 미참조 (가드가 self-contained) — inject 불필요.
terminal_transition_denied = _extract_func(_ENT_INIT, "terminal_transition_denied")


class IssueTerminalTransitionGuardTest(unittest.TestCase):
    """terminal_transition_denied — None=허용, str=거부 사유."""

    def test_cleanup_to_done_allowed(self):
        self.assertIsNone(terminal_transition_denied("cleanup", "done"))

    def test_cleanup_to_cancelled_allowed(self):
        self.assertIsNone(terminal_transition_denied("cleanup", "cancelled"))

    def test_done_blocked_from_non_cleanup(self):
        for old in ("backlog", "todo", "running", "waiting", "error"):
            self.assertIsNotNone(
                terminal_transition_denied(old, "done"),
                f"{old} → done 은 거부돼야 한다 (cleanup 경유)",
            )

    def test_cancelled_blocked_from_cold_states(self):
        # 핵심 회귀: backlog/todo 의 cancel 직행이 이제 거부된다.
        for old in ("backlog", "todo"):
            self.assertIsNotNone(
                terminal_transition_denied(old, "cancelled"),
                f"{old} → cancelled 직행은 거부돼야 한다 (cleanup 경유)",
            )

    def test_cancelled_blocked_from_active_states(self):
        for old in ("running", "waiting", "error"):
            self.assertIsNotNone(
                terminal_transition_denied(old, "cancelled"),
                f"{old} → cancelled 직행은 거부돼야 한다 (cleanup 경유)",
            )

    def test_noop_same_status_allowed(self):
        for s in ("todo", "cleanup", "done", "cancelled"):
            self.assertIsNone(terminal_transition_denied(s, s))

    def test_non_terminal_transitions_allowed(self):
        # 종결 전이가 아니면 가드 대상이 아니다 (자유 전이).
        self.assertIsNone(terminal_transition_denied("todo", "running"))
        self.assertIsNone(terminal_transition_denied("running", "cleanup"))
        self.assertIsNone(terminal_transition_denied("running", "waiting"))
        self.assertIsNone(terminal_transition_denied("todo", "cleanup"))


if __name__ == "__main__":
    unittest.main()
