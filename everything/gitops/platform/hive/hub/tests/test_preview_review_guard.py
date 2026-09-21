"""issue `_preview_review_guard` 회귀 테스트 — preview_review 핸드오프 readiness 강제.

워커가 미리보기 헬스체크(gitops_app_spec §6.5 step-1)를 건너뛰고 깨진 preview 를
`waiting`+preview_review 로 사람 리뷰에 넘기는 것을 hub 가 막는지 검증한다.

hub 테스트 규약: app 패키지(런타임 의존)를 import 하지 않는다 — 가드 함수 소스를
ast 로 추출해 stub 주입 namespace 에서 exec (test_issue_terminal_transitions 동일 패턴).
"""

import ast
import types
import unittest
from pathlib import Path

_ISSUE = Path(__file__).resolve().parents[1] / "app" / "entities" / "issue.py"


class _Resp:
    """CapabilityResponse stub — status/error_code/message 만 포착."""
    def __init__(self, status=None, error_code=None, message=None, data=None):
        self.status = status
        self.error_code = error_code
        self.message = message


def _extract_func(name: str, inject: dict):
    src = _ISSUE.read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns = dict(inject)
            exec(ast.get_source_segment(src, node), ns)
            return ns[name]
    raise AssertionError(f"{name} not found in {_ISSUE}")


def _make_guard(readiness_result):
    return _extract_func("_preview_review_guard", {
        "CapabilityResponse": _Resp,
        "preview_readiness": lambda cell_id, branch: readiness_result,
        "IssueUpdateRequest": object,
    })


def _req(status="waiting", subtype="handoff", reason="preview_review", issue_id="ITEMS-ISSUE-48"):
    return types.SimpleNamespace(
        status=status, comment_subtype=subtype,
        comment_payload={"reason": reason} if reason is not None else {},
        issue_id=issue_id,
    )


_CP = types.SimpleNamespace(cell_id="items")


class PreviewReviewGuardTest(unittest.TestCase):
    def test_absent_blocks(self):
        guard = _make_guard(("absent", []))
        r = guard(_req(), _CP)
        self.assertIsNotNone(r)
        self.assertEqual(r.error_code, "preview_not_ready")

    def test_not_ready_blocks_and_reports_phase(self):
        guard = _make_guard(("not_ready", [{"app": "lucky-defense", "env": "preview", "phase": "Progressing", "host": "x"}]))
        r = guard(_req(), _CP)
        self.assertIsNotNone(r)
        self.assertEqual(r.error_code, "preview_not_ready")
        self.assertIn("Progressing", r.message)

    def test_ready_allows(self):
        guard = _make_guard(("ready", [{"app": "a", "env": "preview", "phase": "Ready", "host": "x"}]))
        self.assertIsNone(guard(_req(), _CP))

    def test_meta_unreachable_fails_open(self):
        guard = _make_guard(("meta_unreachable", []))
        self.assertIsNone(guard(_req(), _CP))

    def test_non_preview_handoff_untouched(self):
        # reason != preview_review → 가드 미발동 (readiness 가 absent 여도 통과)
        guard = _make_guard(("absent", []))
        self.assertIsNone(guard(_req(reason="merge_review"), _CP))
        self.assertIsNone(guard(_req(reason=None), _CP))

    def test_non_handoff_subtype_untouched(self):
        guard = _make_guard(("absent", []))
        self.assertIsNone(guard(_req(subtype="transition"), _CP))

    def test_non_waiting_status_untouched(self):
        guard = _make_guard(("absent", []))
        self.assertIsNone(guard(_req(status="running"), _CP))


if __name__ == "__main__":
    unittest.main()
