"""project.list initiative_id 필터 + 응답 키 backfill (INFRA-ISSUE-95).

회귀 표면:
- `ProjectListRequest` 에 `initiative_id` 필드가 실제 정의돼 있어야 한다 (없으면
  Pydantic 이 unknown field 를 조용히 drop → 필터가 의미 없이 통과).
- filter 의미론은 Linear parent_id 패턴: ``__all__``=전부, ``None``=standalone
  (initiative 미attach), 특정 id=그 initiative attach 된 Project 만.
- 응답 serialization 은 legacy 레코드 (initiative_id 키 자체 누락) 에도
  ``"initiative_id": null`` 을 노출해야 curation 검증·UI 트리 렌더링 가능.

AST + 순수 함수 단위 — fastapi/db 의존성 없이 외부에서 단독 실행 가능.
"""

import ast
import os
import unittest


HUB_APP = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "entities")
)
GOAL_PY = os.path.join(HUB_APP, "project.py")


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


def _filter_by_initiative(projects: list, initiative_id):
    """goal_list / goal_list_all 안의 initiative_id 필터 로직 그대로 추출."""
    if initiative_id != "__all__":
        return [g for g in projects if g.get("initiative_id") == initiative_id]
    return list(projects)


def _ensure_initiative_id(project: dict) -> dict:
    """project.py `_ensure_initiative_id` 와 동일 의미론 — 누락 키만 null 채움."""
    project.setdefault("initiative_id", None)
    return project


class TestGoalListRequestField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classes = _classes_in(GOAL_PY)

    def test_goal_list_request_has_initiative_id(self):
        # 필드 누락이 곧 필터 무력화 (Pydantic unknown field drop).
        fields = _annotated_fields(self.classes["ProjectListRequest"])
        self.assertIn("initiative_id", fields)


class TestInitiativeFilter(unittest.TestCase):
    def setUp(self):
        self.projects = [
            {"project_id": "G1", "initiative_id": "I1"},
            {"project_id": "G2", "initiative_id": "I1"},
            {"project_id": "G3", "initiative_id": "I2"},
            {"project_id": "G4", "initiative_id": None},   # 명시 standalone
            {"project_id": "G5"},                            # legacy — 키 자체 없음
        ]

    def test_all_sentinel_returns_everything(self):
        result = _filter_by_initiative(self.projects, "__all__")
        self.assertEqual([g["project_id"] for g in result], ["G1", "G2", "G3", "G4", "G5"])

    def test_specific_id_returns_only_attached(self):
        # 재현 결함: ITEMS-INITIATIVE-1 호출 시 attach 안 된 Project 까지 반환됐다.
        result = _filter_by_initiative(self.projects, "I1")
        self.assertEqual([g["project_id"] for g in result], ["G1", "G2"])

    def test_none_returns_only_standalone(self):
        # 키 누락(legacy) 과 명시 None 둘 다 standalone 으로 묶인다 (dict.get default).
        result = _filter_by_initiative(self.projects, None)
        self.assertEqual({g["project_id"] for g in result}, {"G4", "G5"})


class TestEnsureInitiativeId(unittest.TestCase):
    def test_backfills_missing_key_as_null(self):
        # 재현 결함: legacy project 의 응답에 initiative_id 키 자체가 없었음.
        project = {"project_id": "G5"}
        _ensure_initiative_id(project)
        self.assertIn("initiative_id", project)
        self.assertIsNone(project["initiative_id"])

    def test_preserves_existing_value(self):
        project = {"project_id": "G1", "initiative_id": "I1"}
        _ensure_initiative_id(project)
        self.assertEqual(project["initiative_id"], "I1")

    def test_preserves_explicit_none(self):
        # 명시 standalone 도 그대로 유지.
        project = {"project_id": "G4", "initiative_id": None}
        _ensure_initiative_id(project)
        self.assertIsNone(project["initiative_id"])


class TestProductionCallSites(unittest.TestCase):
    """project.py 본체가 위 필터 패턴과 backfill 헬퍼를 실제로 호출하는지 AST 확인."""

    @classmethod
    def setUpClass(cls):
        with open(GOAL_PY) as fh:
            cls.source = fh.read()

    def test_filter_applied_in_handlers(self):
        # 필터는 공유 _filter_sort_paginate helper 1곳에 모였고, project_list·project_list_all
        # 둘 다 그 helper 를 호출한다(정의 1 + 호출 2 = 3회 이상) → 드리프트 구조적 불가.
        self.assertIn('if req.initiative_id != "__all__":', self.source)
        self.assertGreaterEqual(
            self.source.count("_filter_sort_paginate("),
            3,
            "project_list·project_list_all 이 공유 _filter_sort_paginate 를 호출해야 한다",
        )

    def test_ensure_initiative_id_called(self):
        # list / list_all / get 3개 호출 사이트.
        self.assertGreaterEqual(
            self.source.count("_ensure_initiative_id("),
            4,  # 정의 1 + 호출 3
            "_ensure_initiative_id 가 list/list_all/get 모두에서 호출되어야 한다",
        )


if __name__ == "__main__":
    unittest.main()
