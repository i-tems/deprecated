"""list/list_all 의 hold 필터 (Triage 가 hold 항목을 수집하기 위한 계약).

Triage 는 사람이 처리해야 할 큐로 waiting/error 뿐 아니라 hold=true(사람이 agent-loop
픽업을 막아둔 parked 항목)도 모은다. list 엔드포인트엔 OR 필터가 없어 hold 를 별 축으로
조회하므로, Issue·Project·Initiative 의 List request 에 `hold` 필드가 실제 정의돼 있고
(없으면 Pydantic 이 unknown field 를 조용히 drop → 필터 무력화) 양쪽 핸들러(list·list_all)가
필터를 적용해야 한다.

AST + 순수 함수 단위 — fastapi/db 의존성 없이 단독 실행 (test_issue_list_initiative_filter 동형).
"""

import ast
import os
import unittest


HUB_APP = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "entities")
)
ISSUE_PY = os.path.join(HUB_APP, "issue.py")
PROJECT_PY = os.path.join(HUB_APP, "project.py")
INITIATIVE_PY = os.path.join(HUB_APP, "initiative.py")


def _annotated_fields(path: str, class_name: str) -> set:
    with open(path) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    raise AssertionError(f"{class_name} not found in {path}")


def _filter_by_hold(items: list, hold, key: str = "hold") -> list:
    """issue/project/initiative.py 의 hold 필터와 동일 의미론 — None 이면 무필터,
    아니면 bool(record[key]) == hold (누락 키는 falsy)."""
    if hold is not None:
        return [x for x in items if bool(x.get(key)) == hold]
    return list(items)


class TestRequestFields(unittest.TestCase):
    def test_list_requests_have_hold(self):
        # 필드 누락이 곧 필터 무력화 (Pydantic unknown field drop).
        for path, cls in (
            (ISSUE_PY, "IssueListRequest"),
            (PROJECT_PY, "ProjectListRequest"),
            (INITIATIVE_PY, "InitiativeListRequest"),
        ):
            with self.subTest(request=cls):
                self.assertIn("hold", _annotated_fields(path, cls))


class TestHoldFilter(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"id": "A", "hold": True},
            {"id": "B", "hold": False},
            {"id": "C"},  # legacy — 키 없음 → falsy
        ]

    def test_none_returns_everything(self):
        self.assertEqual([x["id"] for x in _filter_by_hold(self.items, None)], ["A", "B", "C"])

    def test_true_returns_only_held(self):
        self.assertEqual([x["id"] for x in _filter_by_hold(self.items, True)], ["A"])

    def test_false_returns_unheld_including_missing(self):
        self.assertEqual([x["id"] for x in _filter_by_hold(self.items, False)], ["B", "C"])


class TestProductionCallSites(unittest.TestCase):
    """본체가 hold 필터를 list·list_all 양쪽에 적용하는지 소스 확인."""

    def test_filter_applied_in_both_handlers(self):
        for path, loop_var in (
            (ISSUE_PY, "t"),
            (PROJECT_PY, "g"),
            (INITIATIVE_PY, "i"),
        ):
            with self.subTest(path=os.path.basename(path)):
                source = open(path).read()
                # hold 필터는 공유 _filter_sort_paginate helper 1곳에 모였고, list·list_all
                # 둘 다 그 helper 를 호출한다(정의 1 + 호출 2 = 3회 이상) → 드리프트 불가.
                self.assertIn("if req.hold is not None:", source,
                              f"{os.path.basename(path)}: hold 필터가 있어야 한다")
                self.assertIn(f'bool({loop_var}.get("hold")) == req.hold', source)
                self.assertGreaterEqual(
                    source.count("_filter_sort_paginate("),
                    3,
                    f"{os.path.basename(path)}: list·list_all 이 공유 _filter_sort_paginate 를 호출해야 한다",
                )


if __name__ == "__main__":
    unittest.main()
