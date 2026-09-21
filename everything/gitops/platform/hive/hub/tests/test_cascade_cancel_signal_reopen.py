"""cascade-cancel 이 자식 issue 의 source_signal_ids 를 signal reopen 에 전달하는지.

project/initiative 를 사람이 강제 terminal 로 잡으면 _cascade_cancel_active_children
가 active 자식 issue 를 일괄 cancel 한다. 이때 각 자식의 source_signal_ids 링크 signal 을
reopen(consumed→emitted) 해야 한다 — 단일 취소 경로(update_entity terminal, __init__.py
의 두 번째 transition_linked_signals 호출)와 동일.

transition_linked_signals 는 두 방향으로 매칭한다:
  - forward: signal.issue_id == entity_id
  - reverse: signal.signal_id ∈ source_signal_ids
issue.create 는 issue.source_signal_ids(reverse 링크)만 기록하고 signal.issue_id(forward)는
세팅하지 않으므로, reverse 가 권위 링크다. cascade 가 source_signal_ids=None 을 넘기면
reverse-only signal 이 reopen 되지 않아 취소된 작업의 signal 이 triage 큐로 돌아오지
못한다 (INFRA-ISSUE-322).

AST 단위 — fastapi/db/capability_framework 의존 없이 단독 실행 (storage primitive 가
SQL dispatch 라 behavioral 테스트는 DB 필요. test_list_hold_filter 동형).
"""

import ast
import os
import unittest


INIT_PY = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "entities", "__init__.py")
)


def _module() -> ast.Module:
    with open(INIT_PY) as fh:
        return ast.parse(fh.read())


def _func(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {INIT_PY}")


def _transition_calls(node: ast.AST) -> list:
    calls = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name == "transition_linked_signals":
                calls.append(sub)
    return calls


def _kw(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_none(value) -> bool:
    return isinstance(value, ast.Constant) and value.value is None


class TestCascadeCancelForwardsSourceSignalIds(unittest.TestCase):
    def test_cascade_reopens_with_non_none_source_signal_ids(self):
        fn = _func(_module(), "_cascade_cancel_active_children")
        calls = _transition_calls(fn)
        self.assertTrue(calls, "_cascade_cancel_active_children 는 자식의 링크 signal 을 reopen 해야 한다")
        for c in calls:
            val = _kw(c, "source_signal_ids")
            self.assertIsNotNone(val, "source_signal_ids 인자를 명시해야 한다")
            self.assertFalse(
                _is_none(val),
                "cascade-cancel 은 자식별 source_signal_ids 를 전달해야 한다(None 금지) — "
                "reverse-only signal 이 reopen 되도록",
            )

    def test_all_terminal_reopen_sites_forward_source_signal_ids(self):
        # __init__.py 의 모든 transition_linked_signals 호출(cascade + 단일 취소)이 reverse
        # 링크를 전달해야 정합. 한쪽만 None 이면 같은 버그가 재발한다.
        calls = _transition_calls(_module())
        self.assertGreaterEqual(len(calls), 2, "cascade·단일 취소 양쪽 호출이 있어야 한다")
        for c in calls:
            val = _kw(c, "source_signal_ids")
            self.assertFalse(
                val is None or _is_none(val),
                "모든 transition_linked_signals 호출은 source_signal_ids 를 전달해야 한다(None 금지)",
            )


if __name__ == "__main__":
    unittest.main()
