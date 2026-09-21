"""field_change 감사 커버리지 — Linear parity (옵션 A).

apply_entity_fields_and_persist 는 update 적용 전 _TRACKED_FIELDS 스냅샷(old_vals)을
떠, 적용 후 값과 다른 필드마다 field_change 이벤트를 발행한다 (entities/__init__.py
의 `for _f in _TRACKED_FIELDS: if old_vals[_f] != found.get(_f): emit_event(...)`).

hub 테스트 규약상 app 패키지를 import 하지 않는다 (capability_framework 등 런타임
전용 의존이 로컬에 없음). 대신 entities/__init__.py 소스에서 _TRACKED_FIELDS 튜플
리터럴만 ast 로 추출해 실제 값에 대한 회귀 가드를 건다.

검증:
  1. _TRACKED_FIELDS 가 Linear 가 activity 에 남기는 필드(assignee=owner, priority,
     gates 등)를 모두 포함 — 회귀 시 누락 필드가 다시 audit 에서 빠진다.
  2. 제외 대상(priority_score 파생값 / status·labels·dependencies·hold 별도 발행 /
     metadata 내부 누적)은 _TRACKED_FIELDS 에 없어 이 경로로 발행되지 않는다.
  3. old_vals != found 디프 술어가 변경 필드만 골라낸다.
"""

import ast
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "app" / "entities" / "__init__.py"


def _load_tracked_fields() -> tuple[str, ...]:
    """entities/__init__.py 에서 `_TRACKED_FIELDS = (...)` 리터럴만 추출 (app import 회피)."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_TRACKED_FIELDS":
                    return tuple(ast.literal_eval(node.value))
    raise AssertionError("_TRACKED_FIELDS 정의를 찾지 못함")


_TRACKED_FIELDS = _load_tracked_fields()


def _changed_fields(old: dict, new: dict) -> set:
    """entities/__init__.py:210 의 발행 술어를 추출한 순수 함수."""
    return {f for f in _TRACKED_FIELDS if old.get(f) != new.get(f)}


class TestTrackedFieldsCoverage(unittest.TestCase):
    def test_audit_fields_present(self):
        for f in ("title", "description", "plan",
                  "owner", "capability", "model",
                  "priority", "resources", "gates", "source_signal_ids"):
            self.assertIn(f, _TRACKED_FIELDS, f"{f} 가 field_change audit 에서 빠짐")

    def test_excluded_fields_absent(self):
        for f in ("priority_score", "status", "labels", "dependencies",
                  "hold", "metadata"):
            self.assertNotIn(f, _TRACKED_FIELDS, f"{f} 는 _TRACKED_FIELDS 에 있으면 안 됨")


class TestChangedFieldsPredicate(unittest.TestCase):
    def test_owner_change_emits(self):
        self.assertIn("owner", _changed_fields({"owner": "a@x.com"}, {"owner": "b@x.com"}))

    def test_plan_change_emits(self):
        self.assertIn("plan", _changed_fields({"plan": None}, {"plan": "step 1"}))

    def test_priority_dict_change_emits(self):
        self.assertIn("priority", _changed_fields({"priority": {"value": 2}}, {"priority": {"value": 4}}))

    def test_gates_dict_change_emits(self):
        self.assertIn("gates", _changed_fields({"gates": {"completion": "auto"}},
                                               {"gates": {"completion": "require"}}))

    def test_resources_list_change_emits(self):
        self.assertIn("resources", _changed_fields(
            {"resources": []}, {"resources": [{"label": "r", "uri": "u", "type": "url"}]}))

    def test_unchanged_no_emit(self):
        same = {"owner": "a@x.com", "priority": {"value": 2}, "gates": {"completion": "auto"}}
        self.assertEqual(_changed_fields(same, dict(same)), set())

    def test_priority_score_not_emitted_even_if_changed(self):
        self.assertEqual(_changed_fields({"priority_score": 50}, {"priority_score": 90}), set())


if __name__ == "__main__":
    unittest.main()
