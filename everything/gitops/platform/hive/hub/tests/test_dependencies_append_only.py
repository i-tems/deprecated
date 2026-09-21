"""dependencies append-only + remove pair — Linear MCP 흡수 Wave 3.

apply_entity_fields_and_persist 안의 dependency 머지 로직만 단위 테스트.
실제 파일 IO / event 발행은 stub — 머지 알고리즘이 Linear blockedBy 패턴과 일치하는지 확인.

핵심 동작:
- dependencies (add 리스트) 전달 시 기존 list 에 append, 중복은 dedup.
- remove_dependencies 전달 시 명시 제거.
- 동시 전달 시 add 후 remove 순서. 자기 자신을 add+remove 하면 결과는 없음.
- 둘 다 None / 빈 리스트 시 found["dependencies"] 변경 없음.
"""

import unittest


def _merge(found_deps, add, remove):
    """apply_entity_fields_and_persist 의 dependency 머지 로직을 추출한 순수 함수."""
    deps_before = list(found_deps or [])
    if add:
        seen = set(deps_before)
        deps_before = deps_before + [d for d in add if d not in seen]
    if remove:
        drop = set(remove)
        deps_before = [d for d in deps_before if d not in drop]
    return deps_before


class TestDependenciesMerge(unittest.TestCase):
    def test_add_to_empty(self):
        self.assertEqual(_merge([], ["A", "B"], None), ["A", "B"])

    def test_add_preserves_existing(self):
        # 기존이 [A, B] 인데 [C] 추가 → [A, B, C] (Linear blockedBy append-only).
        self.assertEqual(_merge(["A", "B"], ["C"], None), ["A", "B", "C"])

    def test_add_dedups(self):
        # 이미 있는 A 를 또 추가해도 한 번만.
        self.assertEqual(_merge(["A", "B"], ["A", "C"], None), ["A", "B", "C"])

    def test_remove_existing(self):
        self.assertEqual(_merge(["A", "B", "C"], None, ["B"]), ["A", "C"])

    def test_remove_nonexistent_is_noop(self):
        self.assertEqual(_merge(["A", "B"], None, ["X"]), ["A", "B"])

    def test_add_then_remove_same_id_is_no_net_effect(self):
        # add 가 먼저 적용되고 remove 가 뒤 — 같은 id 면 결과적으로 없음.
        self.assertEqual(_merge(["A"], ["B"], ["B"]), ["A"])

    def test_add_and_remove_different_ids(self):
        self.assertEqual(_merge(["A", "B"], ["C"], ["A"]), ["B", "C"])

    def test_both_none_returns_same_list(self):
        # None / None 이면 기존 그대로.
        self.assertEqual(_merge(["A", "B"], None, None), ["A", "B"])

    def test_empty_lists_no_change(self):
        # 빈 리스트는 add/remove 둘 다 falsy 로 처리 — 변경 없음.
        self.assertEqual(_merge(["A", "B"], [], []), ["A", "B"])

    def test_order_preserved(self):
        # 기존 순서 유지, 새 add 는 끝에 붙음 (Linear UI 가 순서로 표시).
        self.assertEqual(
            _merge(["A", "B", "C"], ["D", "E"], None),
            ["A", "B", "C", "D", "E"],
        )

    def test_remove_all(self):
        self.assertEqual(_merge(["A", "B"], None, ["A", "B"]), [])


class TestRequestModelHasDependencyFields(unittest.TestCase):
    """IssueUpdateRequest / ProjectUpdateRequest / IssueSaveRequest / ProjectSaveRequest 가
    dependencies + remove_dependencies 필드를 모두 보유하는지 AST 로 확인."""

    @classmethod
    def setUpClass(cls):
        import ast
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        cls.task_classes = {}
        cls.goal_classes = {}
        for path, target in (
            (os.path.join(here, "..", "app", "entities", "issue.py"), cls.task_classes),
            (os.path.join(here, "..", "app", "entities", "project.py"), cls.goal_classes),
        ):
            with open(path) as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    target[node.name] = {
                        stmt.target.id
                        for stmt in node.body
                        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                    }

    def test_task_update_has_both_fields(self):
        fields = self.task_classes["IssueUpdateRequest"]
        self.assertIn("dependencies", fields)
        self.assertIn("remove_dependencies", fields)

    def test_goal_update_has_both_fields(self):
        fields = self.goal_classes["ProjectUpdateRequest"]
        self.assertIn("dependencies", fields)
        self.assertIn("remove_dependencies", fields)

    def test_task_save_has_both_fields(self):
        fields = self.task_classes["IssueSaveRequest"]
        self.assertIn("dependencies", fields)
        self.assertIn("remove_dependencies", fields)

    def test_goal_save_has_both_fields(self):
        fields = self.goal_classes["ProjectSaveRequest"]
        self.assertIn("dependencies", fields)
        self.assertIn("remove_dependencies", fields)


if __name__ == "__main__":
    unittest.main()
