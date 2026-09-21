"""issue 의 initiative_id 직접 연결 + effective 파생 + list 필터 (INFRA-ISSUE-182).

회귀 표면:
- Issue mutation request (`IssueCreateRequest` / `IssueUpdateRequest` /
  `IssueSaveRequest`) 와 `IssueListRequest` 에 `initiative_id` 필드가 실제 정의돼
  있어야 한다 (없으면 Pydantic 이 unknown field 를 조용히 drop → 저장·필터 무력화).
- **effective 파생**: project 있는 Issue 는 상위 Project 의 initiative 를 따라가고,
  Issue 자체 initiative_id 는 standalone 일 때만 유효 (project 떼면 부활하도록 dormant
  보존). 이 파생이 standalone↔project 전이를 round-trip 으로 흡수한다.
- list 필터 의미론은 effective 기준 — ``__all__``=전부, ``None``=미연결, 특정 id=그
  initiative 에 effective 연결된 Issue 만.
- 응답 serialization 은 legacy 레코드 (initiative_id 키 누락) 에도 ``null`` 노출.

AST + 순수 함수 단위 — fastapi/db 의존성 없이 외부에서 단독 실행 가능
(test_project_list_initiative_filter.py 동형).
"""

import ast
import os
import unittest


HUB_APP = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "entities")
)
ISSUE_PY = os.path.join(HUB_APP, "issue.py")


def _classes_in(path: str) -> dict:
    with open(path) as fh:
        tree = ast.parse(fh.read())
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


def _annotated_fields(class_def: ast.ClassDef) -> set:
    out: set = set()
    for stmt in class_def.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            out.add(stmt.target.id)
    return out


def _effective_initiative_id(issue: dict, projects_by_id: dict):
    """issue.py `_effective_initiative_id` 와 동일 의미론 — project 있으면 상위
    Project 의 initiative, standalone 이면 자체 initiative_id."""
    pid = issue.get("project_id")
    if pid:
        proj = projects_by_id.get(pid)
        return proj.get("initiative_id") if proj else None
    return issue.get("initiative_id")


def _filter_by_initiative(issues: list, projects_by_id: dict, initiative_id):
    if initiative_id != "__all__":
        return [t for t in issues if _effective_initiative_id(t, projects_by_id) == initiative_id]
    return list(issues)


def _ensure_initiative_id(issue: dict) -> dict:
    issue.setdefault("initiative_id", None)
    return issue


class TestRequestFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classes = _classes_in(ISSUE_PY)

    def test_all_mutation_and_list_requests_have_initiative_id(self):
        # 필드 누락이 곧 저장/필터 무력화 (Pydantic unknown field drop).
        for name in (
            "IssueCreateRequest", "IssueUpdateRequest",
            "IssueSaveRequest", "IssueListRequest",
        ):
            with self.subTest(request=name):
                self.assertIn("initiative_id", _annotated_fields(self.classes[name]))


class TestEffectiveInitiative(unittest.TestCase):
    def setUp(self):
        self.projects_by_id = {
            "P1": {"project_id": "P1", "initiative_id": "I2"},
            "P2": {"project_id": "P2", "initiative_id": None},
        }

    def test_standalone_uses_own(self):
        issue = {"issue_id": "T1", "project_id": None, "initiative_id": "I1"}
        self.assertEqual(_effective_initiative_id(issue, self.projects_by_id), "I1")

    def test_project_overrides_own_dormant(self):
        # 핵심: project 가 있으면 상위 Project 의 initiative 가 이기고, Issue 자체
        # initiative_id(I1) 는 dormant — standalone 이었다가 project 에 붙은 경우.
        issue = {"issue_id": "T2", "project_id": "P1", "initiative_id": "I1"}
        self.assertEqual(_effective_initiative_id(issue, self.projects_by_id), "I2")

    def test_project_with_no_initiative(self):
        issue = {"issue_id": "T3", "project_id": "P2", "initiative_id": "I1"}
        self.assertIsNone(_effective_initiative_id(issue, self.projects_by_id))

    def test_missing_project_resolves_none(self):
        issue = {"issue_id": "T4", "project_id": "P_gone", "initiative_id": "I1"}
        self.assertIsNone(_effective_initiative_id(issue, self.projects_by_id))

    def test_standalone_no_initiative(self):
        issue = {"issue_id": "T5", "project_id": None}
        self.assertIsNone(_effective_initiative_id(issue, self.projects_by_id))


class TestInitiativeFilter(unittest.TestCase):
    def setUp(self):
        self.projects_by_id = {"P1": {"project_id": "P1", "initiative_id": "I2"}}
        self.issues = [
            {"issue_id": "T1", "project_id": None, "initiative_id": "I1"},   # standalone → I1
            {"issue_id": "T2", "project_id": None, "initiative_id": "I1"},   # standalone → I1
            {"issue_id": "T3", "project_id": "P1", "initiative_id": "I1"},   # project → I2 (own dormant)
            {"issue_id": "T4", "project_id": None, "initiative_id": None},   # 명시 미연결
            {"issue_id": "T5", "project_id": None},                            # legacy — 키 없음
        ]

    def test_all_sentinel_returns_everything(self):
        result = _filter_by_initiative(self.issues, self.projects_by_id, "__all__")
        self.assertEqual([t["issue_id"] for t in result], ["T1", "T2", "T3", "T4", "T5"])

    def test_specific_id_uses_effective(self):
        # I1 직접 anchor 한 standalone 만. project 경유(T3, effective I2)는 제외.
        result = _filter_by_initiative(self.issues, self.projects_by_id, "I1")
        self.assertEqual([t["issue_id"] for t in result], ["T1", "T2"])

    def test_project_inherited_matches_parent_initiative(self):
        # T3 는 자체 I1 이지만 project P1 의 I2 를 따라간다.
        result = _filter_by_initiative(self.issues, self.projects_by_id, "I2")
        self.assertEqual([t["issue_id"] for t in result], ["T3"])

    def test_none_returns_only_unlinked(self):
        result = _filter_by_initiative(self.issues, self.projects_by_id, None)
        self.assertEqual({t["issue_id"] for t in result}, {"T4", "T5"})


class TestEnsureInitiativeId(unittest.TestCase):
    def test_backfills_missing_key_as_null(self):
        issue = {"issue_id": "T5"}
        _ensure_initiative_id(issue)
        self.assertIn("initiative_id", issue)
        self.assertIsNone(issue["initiative_id"])

    def test_preserves_existing_value(self):
        issue = {"issue_id": "T1", "initiative_id": "I1"}
        _ensure_initiative_id(issue)
        self.assertEqual(issue["initiative_id"], "I1")


class TestProductionCallSites(unittest.TestCase):
    """issue.py 본체가 필터 패턴·검증·backfill 을 실제로 호출하는지 AST/소스 확인."""

    @classmethod
    def setUpClass(cls):
        with open(ISSUE_PY) as fh:
            cls.source = fh.read()

    def test_filter_applied_in_both_handlers(self):
        # 필터는 공유 _filter_sort_paginate helper 1곳에 모였고(드리프트 구조적 불가),
        # issue_list·issue_list_all 둘 다 그 helper 를 호출한다(정의 1 + 호출 2 = 3회 이상).
        self.assertIn('if req.initiative_id != "__all__":', self.source)
        self.assertGreaterEqual(
            self.source.count("_filter_sort_paginate("),
            3,
            "issue_list·issue_list_all 이 공유 _filter_sort_paginate 를 호출해야 한다",
        )

    def test_create_validates_initiative_ref(self):
        self.assertIn("validate_initiative_ref(cp, req.initiative_id)", self.source)

    def test_create_persists_initiative_id(self):
        self.assertIn('"initiative_id": req.initiative_id', self.source)

    def test_ensure_initiative_id_called(self):
        # 정의 1 + get/list/list_all 호출 3.
        self.assertGreaterEqual(self.source.count("_ensure_initiative_id("), 4)

    def test_get_attaches_summary(self):
        self.assertIn("_ensure_initiative_summary(", self.source)


if __name__ == "__main__":
    unittest.main()
