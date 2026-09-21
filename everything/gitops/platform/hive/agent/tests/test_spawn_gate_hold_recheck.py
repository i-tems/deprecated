"""spawn 직전 가드(_still_actionable)가 fresh hold 를 재검사하는지 (TOCTOU).

work_finder 의 find_all_work snapshot 은 hold=true entity 를 제외하지만, snapshot 이후
사람이 hold 를 걸면 그 사이 worker spawn 이 진행될 수 있다 (예: 개인 --direct 세션이
대상 entity 를 hold 로 잡는 순간). _still_actionable 은 spawn 직전 fresh entity 를 다시
읽어 status 와 hold 를 재검사해 held 면 skip 해야 한다 — work_finder spawn 게이트·worker
cycle 게이트와 동일 hold 계약 (INFRA-ISSUE-187 / INFRA-ISSUE-322).

AST 단위 — loop.py 는 kubernetes import 때문에 로컬 import 불가(test_pickup_status_guards
주석 참조)라 소스 수준으로 검증한다.
"""

import ast
import os
import unittest


LOOP_PY = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "loop.py")
)


def _func(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {LOOP_PY}")


def _gets_key(node: ast.AST, key: str) -> bool:
    """node 본문에 <expr>.get("<key>") 호출이 있는가."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "get"
            and sub.args
            and isinstance(sub.args[0], ast.Constant)
            and sub.args[0].value == key
        ):
            return True
    return False


class TestSpawnGateHoldRecheck(unittest.TestCase):
    def setUp(self):
        with open(LOOP_PY) as fh:
            self.fn = _func(ast.parse(fh.read()), "_still_actionable")

    def test_rechecks_hold(self):
        self.assertTrue(
            _gets_key(self.fn, "hold"),
            "_still_actionable 은 spawn 직전 fresh hold 를 재검사해야 한다 (TOCTOU — held spawn 차단)",
        )

    def test_still_rechecks_status(self):
        # 기존 status 가드가 함께 유지되는지 — 회귀 방지 + 우리가 맞는 함수를 보는지 확인.
        self.assertTrue(
            _gets_key(self.fn, "status"),
            "_still_actionable 은 fresh status 도 재검사해야 한다",
        )


if __name__ == "__main__":
    unittest.main()
