"""issue.save / project.save 요청 모델 필드 커버리지 — Linear MCP 흡수 Wave 2.

IssueSaveRequest 는 IssueCreateRequest ∪ IssueUpdateRequest 의 모든 필드를 (id 빼고)
포함해야 한다 — dispatcher 가 어느 쪽 path 로 가더라도 필드 누락 없어야 함.
ProjectSaveRequest 도 동일.

AST 만으로 검사 — pydantic / fastapi 의존성 없이 hub 외부에서도 실행 가능.
"""

import ast
import os
import unittest


HUB_APP = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "entities")
)


def _fields_of(class_def: ast.ClassDef) -> set[str]:
    """Pydantic BaseModel 클래스의 필드명 집합을 추출."""
    names: set[str] = set()
    for stmt in class_def.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
    return names


def _classes_in(path: str) -> dict[str, ast.ClassDef]:
    with open(path) as fh:
        tree = ast.parse(fh.read())
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


# update path 에만 의미 있어 create 에 없는 필드 (save 에 포함되어야 함).
_UPDATE_ONLY_FIELDS_TASK = {"comment", "comment_subtype", "comment_payload", "clear_priority"}
_UPDATE_ONLY_FIELDS_GOAL = {"comment", "comment_subtype", "comment_payload", "clear_priority"}

# create path 에만 의미 있는 필드.
_CREATE_ONLY_FIELDS_TASK = {"project_id", "dependencies"}
_CREATE_ONLY_FIELDS_GOAL = {"dependencies"}


class TestTaskSaveCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classes = _classes_in(os.path.join(HUB_APP, "issue.py"))

    def test_classes_exist(self):
        for name in ("IssueCreateRequest", "IssueUpdateRequest", "IssueSaveRequest"):
            self.assertIn(name, self.classes, f"{name} not defined")

    def test_save_covers_create_fields(self):
        create_fields = _fields_of(self.classes["IssueCreateRequest"])
        save_fields = _fields_of(self.classes["IssueSaveRequest"])
        missing = create_fields - save_fields
        self.assertFalse(
            missing,
            f"IssueSaveRequest missing create fields: {missing}",
        )

    def test_save_covers_update_fields_minus_id(self):
        update_fields = _fields_of(self.classes["IssueUpdateRequest"]) - {"issue_id"}
        save_fields = _fields_of(self.classes["IssueSaveRequest"])
        missing = update_fields - save_fields
        self.assertFalse(
            missing,
            f"IssueSaveRequest missing update fields: {missing}",
        )

    def test_save_has_id_optional(self):
        # issue_id 가 SaveRequest 에 있어야 dispatcher 가 분기 가능.
        save_fields = _fields_of(self.classes["IssueSaveRequest"])
        self.assertIn("issue_id", save_fields)

    def test_save_includes_update_only_fields(self):
        save_fields = _fields_of(self.classes["IssueSaveRequest"])
        for f in _UPDATE_ONLY_FIELDS_TASK:
            self.assertIn(f, save_fields, f"update-only field {f} missing from save")

    def test_save_includes_create_only_fields(self):
        save_fields = _fields_of(self.classes["IssueSaveRequest"])
        for f in _CREATE_ONLY_FIELDS_TASK:
            self.assertIn(f, save_fields, f"create-only field {f} missing from save")


class TestGoalSaveCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classes = _classes_in(os.path.join(HUB_APP, "project.py"))

    def test_classes_exist(self):
        for name in ("ProjectCreateRequest", "ProjectUpdateRequest", "ProjectSaveRequest"):
            self.assertIn(name, self.classes, f"{name} not defined")

    def test_save_covers_create_fields(self):
        create_fields = _fields_of(self.classes["ProjectCreateRequest"])
        save_fields = _fields_of(self.classes["ProjectSaveRequest"])
        missing = create_fields - save_fields
        self.assertFalse(
            missing,
            f"ProjectSaveRequest missing create fields: {missing}",
        )

    def test_save_covers_update_fields_minus_id(self):
        update_fields = _fields_of(self.classes["ProjectUpdateRequest"]) - {"project_id"}
        save_fields = _fields_of(self.classes["ProjectSaveRequest"])
        missing = update_fields - save_fields
        self.assertFalse(
            missing,
            f"ProjectSaveRequest missing update fields: {missing}",
        )

    def test_save_has_id_optional(self):
        save_fields = _fields_of(self.classes["ProjectSaveRequest"])
        self.assertIn("project_id", save_fields)

    def test_save_includes_update_only_fields(self):
        save_fields = _fields_of(self.classes["ProjectSaveRequest"])
        for f in _UPDATE_ONLY_FIELDS_GOAL:
            self.assertIn(f, save_fields, f"update-only field {f} missing from save")

    def test_save_includes_create_only_fields(self):
        save_fields = _fields_of(self.classes["ProjectSaveRequest"])
        for f in _CREATE_ONLY_FIELDS_GOAL:
            self.assertIn(f, save_fields, f"create-only field {f} missing from save")


class TestRouterEndpointsExist(unittest.TestCase):
    """@router.post 데코레이터에 issue.save / project.save 경로가 실제로 등록됐는지 AST 확인."""

    def _decorator_paths(self, path: str) -> set[str]:
        with open(path) as fh:
            tree = ast.parse(fh.read())
        out: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "post"
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                ):
                    out.add(dec.args[0].value)
        return out

    def test_task_save_endpoint_registered(self):
        paths = self._decorator_paths(os.path.join(HUB_APP, "issue.py"))
        self.assertIn("/issue.save", paths)
        # 기존 alias 도 그대로 유지되는지 회귀 체크.
        self.assertIn("/issue.create", paths)
        self.assertIn("/issue.update", paths)

    def test_goal_save_endpoint_registered(self):
        paths = self._decorator_paths(os.path.join(HUB_APP, "project.py"))
        self.assertIn("/project.save", paths)
        self.assertIn("/project.create", paths)
        self.assertIn("/project.update", paths)


if __name__ == "__main__":
    unittest.main()
