"""Initiative archive 가 status 모델로 흡수된 후의 계약 가드 (container 4-status 통일).

변경 배경 (구 archived 플래그 → archive status):
- container 모델에서 archive 는 별도 retention 플래그가 아니라 terminal status 다
  (Project 과 통일: backlog/active/done/archive). 구버전은 `archived=True` 플래그였다.
- `initiative.archive` 는 하위호환 이름 유지용 편의 — `status="archive"` 로 전이한다.
  `deleted` 플래그는 건드리지 않는다 (delete 축은 여전히 직교).
- `initiative.restore` 는 archive status → backlog 로 되돌리고, deleted 플래그는 별도로 떨군다.
- archive 는 일반 terminal status 라 list 가 done 처럼 정상 노출 — archived 플래그 필터 제거,
  `include_archived` 는 하위호환 no-op.

AST + 순수 함수 단위 — fastapi/db 의존성 없이 외부에서 단독 실행 가능.
"""

import ast
import os
import unittest


HUB_APP = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "entities")
)
INITIATIVE_PY = os.path.join(HUB_APP, "initiative.py")


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


def _func_in(path: str, name: str) -> ast.FunctionDef:
    with open(path) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found in {path}")


def _assigned_subscript_keys(func: ast.FunctionDef) -> set:
    """함수 본문의 `found["X"] = ...` 형태에서 X 키를 모은다."""
    keys: set = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.slice, ast.Constant)
                    and isinstance(tgt.slice.value, str)
                ):
                    keys.add(tgt.slice.value)
    return keys


class TestListRequestField(unittest.TestCase):
    def test_has_include_archived(self):
        # 하위호환 no-op 으로 필드는 유지 — 호출자가 보내도 reject 안 되도록.
        fields = _annotated_fields(_classes_in(INITIATIVE_PY)["InitiativeListRequest"])
        self.assertIn("include_archived", fields)


class TestArchiveIsStatusNotFlag(unittest.TestCase):
    def test_archive_sets_status_not_archived_flag(self):
        # archive 는 이제 status — initiative.archive 가 status 를 'archive' 로 박고
        # archived 플래그는 더 이상 쓰지 않는다. deleted 도 건드리면 안 된다 (직교 축).
        keys = _assigned_subscript_keys(_func_in(INITIATIVE_PY, "initiative_archive"))
        self.assertIn("status", keys)
        self.assertNotIn("archived", keys, "archived 플래그는 폐기 — status='archive' 로 흡수")
        self.assertNotIn("deleted", keys, "archive 는 deleted 를 건드리면 안 된다 (직교 축)")
        self.assertNotIn("deleted_at", keys)
        # status='archive' 문자열이 실제로 박히는지.
        src = ast.dump(_func_in(INITIATIVE_PY, "initiative_archive"))
        self.assertIn("archive", src)

    def test_restore_moves_archive_status_to_backlog(self):
        # restore 는 archive status → backlog 로 되돌리고 deleted 플래그를 떨군다.
        fn = _func_in(INITIATIVE_PY, "initiative_restore")
        keys = _assigned_subscript_keys(fn)
        self.assertIn("status", keys)
        src = ast.dump(fn)
        self.assertIn("backlog", src)
        self.assertIn("deleted", src)  # deleted 플래그 복원 경로는 유지.


class TestArchiveIsNormalTerminalInList(unittest.TestCase):
    """archive 가 done 처럼 일반 terminal status 라 list 가 archived 플래그로 거르지 않는다."""

    @classmethod
    def setUpClass(cls):
        with open(INITIATIVE_PY) as fh:
            cls.source = fh.read()

    def test_no_archived_flag_filter_in_list(self):
        # 구 `if not req.include_archived: ... not i.get("archived")` 필터가 제거됐는지.
        self.assertNotIn('i.get("archived")', self.source,
                         "archived 플래그 필터는 제거됐어야 한다 (archive 는 status)")
        self.assertNotIn("if not req.include_archived:", self.source,
                         "include_archived 는 no-op — 분기 자체가 없어야 한다")


if __name__ == "__main__":
    unittest.main()
