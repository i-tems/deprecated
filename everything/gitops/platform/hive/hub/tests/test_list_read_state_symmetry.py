"""list 와 list_all 핸들러의 read-state 부착 대칭성 (read-state 배지 정합).

attach_read_state 는 per-user "내가 본 이후 변화" 배지의 소스다. 같은 엔티티의
list 와 list_all 중 한쪽만 부착하면 어느 화면(셀 단일 뷰 vs user-scoped aggregate)에서
보느냐에 따라 배지가 달라진다 — INFRA-ISSUE-322: issue.list·project.list 가
attach_read_state 를 누락해 각자의 list_all 짝과 불일치했다.

read-state 를 갖는 엔티티(issue/project/initiative = view._ENTITY_TYPES)는 list·list_all
양쪽이 모두 부착해야 하고, signal 은 read-state 개념이 없어(둘 다 미부착) 대칭으로 둔다.

AST 단위 — fastapi/db 의존 없이 단독 실행 (test_list_hold_filter 동형).
"""

import ast
import os
import unittest


HUB_APP = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "entities")
)


def _calls_attach_read_state(path: str, func_name: str) -> bool:
    """func_name 함수 본문이 *.attach_read_state(...) 호출을 포함하는가."""
    with open(path) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "attach_read_state"
                ):
                    return True
            return False
    raise AssertionError(f"{func_name} not found in {path}")


class TestReadStateSymmetry(unittest.TestCase):
    def test_read_state_entities_attach_in_both_handlers(self):
        # read-state 를 갖는 엔티티 — list·list_all 양쪽 부착 필수.
        for module, base in (("issue.py", "issue"), ("project.py", "project"), ("initiative.py", "initiative")):
            path = os.path.join(HUB_APP, module)
            for func in (f"{base}_list", f"{base}_list_all"):
                with self.subTest(func=func):
                    self.assertTrue(
                        _calls_attach_read_state(path, func),
                        f"{func}: read-state 엔티티는 attach_read_state 를 호출해야 한다 (list↔list_all 배지 정합)",
                    )

    def test_signal_handlers_symmetric_without_read_state(self):
        # signal 은 read-state 개념이 없다(view._ENTITY_TYPES 제외) — 양쪽 미부착 대칭.
        path = os.path.join(HUB_APP, "signal.py")
        for func in ("signal_list", "signal_list_all"):
            with self.subTest(func=func):
                self.assertFalse(
                    _calls_attach_read_state(path, func),
                    f"{func}: signal 은 read-state 가 없어 attach_read_state 를 부르지 않아야 한다",
                )


if __name__ == "__main__":
    unittest.main()
