"""container `waiting` status 전이 가드 + reply-pickup 필터 회귀 테스트.

waiting 도입 (5-status: backlog/active/waiting/done/archive):
  - waiting 은 NON-terminal — active↔waiting, waiting→done/archive 자유.
  - terminal {done, archive} 에서 나가는 전이는 금지 (force_update 우회).
  - completion=require 면 active→done 직접 금지(워커가 active→waiting 핸드오프, 사람이
    waiting→done 확정) — 단 waiting→done 은 require 라도 허용.
  - reply-pickup: 컨테이너는 terminal(done/archive)에 더해 waiting 도 pending 댓글
    있으면 픽업 대상. issue 는 terminal(done/cancelled)만.

hub 테스트 규약상 app 패키지(capability_framework 런타임 의존)를 import 하지 않는다.
대신 두 순수 함수(`container_transition_denied`, `_replyable_statuses`)의 소스를 ast
로 추출해 격리 exec 한 뒤 동작을 검증한다 (test_field_change_audit 와 동일 패턴).
"""

import ast
import unittest
from pathlib import Path

_ENT_INIT = Path(__file__).resolve().parents[1] / "app" / "entities" / "__init__.py"
_EVENT = Path(__file__).resolve().parents[1] / "app" / "entities" / "event.py"


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


# _CONTAINER_TERMINAL 은 container_transition_denied 가 참조하는 모듈 상수 — 주입.
container_transition_denied = _extract_func(
    _ENT_INIT, "container_transition_denied",
    inject={"_CONTAINER_TERMINAL": {"done", "archive"}},
)
_replyable_statuses = _extract_func(_EVENT, "_replyable_statuses")


class ContainerTransitionGuardTest(unittest.TestCase):
    """container_transition_denied — None=허용, str=거부 사유."""

    def test_active_to_waiting_allowed(self):
        self.assertIsNone(container_transition_denied("active", "waiting", "auto"))
        self.assertIsNone(container_transition_denied("active", "waiting", "require"))

    def test_waiting_to_active_allowed(self):
        self.assertIsNone(container_transition_denied("waiting", "active", "auto"))

    def test_waiting_to_done_allowed_even_under_require(self):
        # waiting→done 은 사람 확정 경로 — require 라도 허용.
        self.assertIsNone(container_transition_denied("waiting", "done", "require"))
        self.assertIsNone(container_transition_denied("waiting", "done", "auto"))

    def test_waiting_to_archive_allowed(self):
        self.assertIsNone(container_transition_denied("waiting", "archive", "require"))

    def test_active_to_done_denied_under_require(self):
        # active→done 직접 전이만 require 에서 차단.
        self.assertIsNotNone(container_transition_denied("active", "done", "require"))

    def test_active_to_done_allowed_under_auto(self):
        self.assertIsNone(container_transition_denied("active", "done", "auto"))

    def test_active_to_archive_allowed(self):
        self.assertIsNone(container_transition_denied("active", "archive", "require"))

    def test_backlog_to_active_allowed(self):
        self.assertIsNone(container_transition_denied("backlog", "active", "auto"))

    def test_terminal_done_cannot_leave(self):
        # done/archive 는 terminal — 어떤 전이도 거부 (force_update 우회).
        self.assertIsNotNone(container_transition_denied("done", "active", "auto"))
        self.assertIsNotNone(container_transition_denied("done", "waiting", "auto"))

    def test_terminal_archive_cannot_leave(self):
        self.assertIsNotNone(container_transition_denied("archive", "active", "auto"))
        self.assertIsNotNone(container_transition_denied("archive", "done", "auto"))

    def test_noop_same_status_allowed(self):
        self.assertIsNone(container_transition_denied("waiting", "waiting", "require"))
        self.assertIsNone(container_transition_denied("done", "done", "auto"))


class ReplyableStatusesTest(unittest.TestCase):
    """_replyable_statuses — cell-wake(즉시 픽업) 대상 status 집합.

    INFRA-ISSUE-263 이후 terminal 은 자동 픽업 대상이 아니라 wake 대상에서도 빠진다 —
    work_finder 의 실제 reply 픽업 status (컨테이너 waiting) 와만 일치.
    """

    def test_container_waiting_only(self):
        for et in ("project", "initiative"):
            self.assertEqual(_replyable_statuses(et), {"waiting"})

    def test_issue_no_wake(self):
        # waiting issue 는 _PICKUP_STATES poll 경로, terminal 은 미픽업 → wake 없음.
        self.assertEqual(_replyable_statuses("issue"), set())


if __name__ == "__main__":
    unittest.main()
