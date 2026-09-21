"""Initiative 를 active 한정 worker entity 로 승격한 변경(PR-1)의 계약 회귀 가드.

Initiative 가 Project 처럼 agent-loop 워커로 자율 동작하려면 hub 가 다음을 보장해야 한다:

  1. **session 영속** — `initiative.set_session` 라우트 + `InitiativeSetSessionRequest`.
     pod crash 시 다음 워커가 같은 claude 대화를 --resume 하는 유일한 경로.
  2. **hold 게이트** — `InitiativeUpdateRequest.hold` 필드. 없으면 Pydantic 이 unknown
     field 를 drop → 수동 steering 중에도 워커가 끼어든다.
  3. **워커 wake 신호** — `initiative.update` 가 status 전이 시 cell cascade(런칭 픽업),
     hold 변경 시 bare initiative_id 키(parked 워커 재개) 를 깨우도록 emit_event 발행.
  4. **자식 Project → 부모 Initiative cascade** — child Project 이 terminal 되면
     `apply_entity_fields_and_persist` 의 cascade 에 부모 `initiative_id` 가 들어가야
     parked initiative 워커가 §B(완료 판단)로 깨어난다. 빠지면 워커가 자식 생성 후
     영구 sleep.
  5. **entity_type → file/recompute 분기** — `_entity_file`(공용 헬퍼), event 의
     `_recompute_pending_and_wake`, `wake._ENTITY_TYPES` 가 "initiative" 를 인식해야
     pending user comment 재계산·HOTL 핸드오프 wake 가 동작.

hub 테스트 규약상 app 패키지를 import 하지 않는다 (capability_framework 등 런타임
전용 의존 부재). 소스를 `ast` 로 파싱하거나 순수 로직을 추출해 불변식을 검증한다.
"""

import ast
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"
_INITIATIVE = _APP / "entities" / "initiative.py"
_ENT_INIT = _APP / "entities" / "__init__.py"
_EVENT = _APP / "entities" / "event.py"
_WAKE = _APP / "entities" / "wake.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _classdefs(path: Path) -> dict:
    return {n.name: n for n in ast.walk(_tree(path)) if isinstance(n, ast.ClassDef)}


def _annotated_fields(class_def: ast.ClassDef) -> set:
    out: set = set()
    for stmt in class_def.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            out.add(stmt.target.id)
    return out


def _route_decorators(path: Path) -> set:
    """@router.post("/x") 의 경로 문자열 집합."""
    out: set = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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


# ── 1. session 영속 ──

class SessionPersistenceTest(unittest.TestCase):
    def test_set_session_route_defined(self):
        self.assertIn("/initiative.set_session", _route_decorators(_INITIATIVE))

    def test_set_session_request_model_defined(self):
        classes = _classdefs(_INITIATIVE)
        self.assertIn("InitiativeSetSessionRequest", classes)
        fields = _annotated_fields(classes["InitiativeSetSessionRequest"])
        # last_prompt_at 은 재진입 워커가 delta 만 주입하게 하는 cursor — 누락 시 토큰 낭비.
        self.assertEqual(fields, {"initiative_id", "session_id", "last_prompt_at"})


# ── 2. hold 게이트 ──

class HoldFieldTest(unittest.TestCase):
    def test_update_request_has_hold(self):
        fields = _annotated_fields(_classdefs(_INITIATIVE)["InitiativeUpdateRequest"])
        self.assertIn("hold", fields)


# ── 3. 워커 wake 신호 (initiative.update emit_event) ──

class UpdateEmitsWakeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _INITIATIVE.read_text(encoding="utf-8")

    def test_emit_event_imported(self):
        # status_change·field_change wake 발행의 전제.
        self.assertIn("emit_event", self.src)

    def test_update_emits_status_change_with_cell_cascade(self):
        # 런칭(planned→active) 이 agent-loop cell long-poll 을 즉시 깨우려면
        # status_change emit 의 cascade_to 에 cell 키가 있어야 한다.
        fn = next(
            n for n in ast.walk(_tree(_INITIATIVE))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "initiative_update"
        )
        body = ast.unparse(fn)
        self.assertIn("status_change", body)
        # ast.unparse 가 따옴표를 정규화하므로 f-string 내용물로 확인.
        self.assertIn("cell:{cp.cell_id}", body)
        self.assertIn("cascade_to", body)
        # hold 변경 시 field_change 발행 (parked 워커 재개 — bare initiative_id 키).
        self.assertIn("field_change", body)


# ── 4. 자식 Project → 부모 Initiative cascade (순수 로직 추출) ──

def _build_cascade(entity_type: str, new_status: str, status_changed: bool,
                   found: dict, cell_id: str) -> list:
    """apply_entity_fields_and_persist 의 cascade 빌드 로직 그대로 추출.

    소스와 동기 유지 — 분기 형태가 바뀌면 이 함수와 아래 단언이 같이 깨져야 한다.
    """
    cascade: list = []
    if status_changed:
        if new_status in ("done", "cancelled", "error"):
            if entity_type == "issue" and found.get("project_id"):
                cascade.append(found["project_id"])
            if entity_type == "project" and found.get("initiative_id"):
                cascade.append(found["initiative_id"])
        cascade.append(f"cell:{cell_id}")
    return cascade


class ChildCascadeTest(unittest.TestCase):
    def test_project_terminal_cascades_to_parent_initiative(self):
        # 핵심 회귀: 이게 없으면 initiative 워커가 자식 Project 생성 후 영구 sleep.
        cascade = _build_cascade(
            "project", "done", True, {"initiative_id": "I1"}, "infra",
        )
        self.assertIn("I1", cascade)
        self.assertIn("cell:infra", cascade)

    def test_standalone_project_terminal_no_initiative_in_cascade(self):
        cascade = _build_cascade("project", "done", True, {"initiative_id": None}, "infra")
        self.assertEqual(cascade, ["cell:infra"])

    def test_issue_terminal_still_cascades_to_project(self):
        # 기존 issue→project cascade 회귀 안 났는지.
        cascade = _build_cascade("issue", "cancelled", True, {"project_id": "G1"}, "infra")
        self.assertIn("G1", cascade)

    def test_non_terminal_status_change_only_cell(self):
        cascade = _build_cascade("project", "running", True, {"initiative_id": "I1"}, "infra")
        self.assertEqual(cascade, ["cell:infra"])

    def test_source_matches_extracted_logic(self):
        # 추출 로직이 실제 소스와 같은 분기를 갖는지 (drift 가드).
        src = _ENT_INIT.read_text(encoding="utf-8")
        self.assertIn(
            'if entity_type == "project" and found.get("initiative_id"):', src,
        )
        self.assertIn('cascade.append(found["initiative_id"])', src)


# ── 5. entity_type → file/recompute/wake 분기 ──

class EntityTypeDispatchTest(unittest.TestCase):
    def test_entity_file_handles_initiative(self):
        src = _ENT_INIT.read_text(encoding="utf-8")
        # _entity_file 가 initiative → cp.initiative_file 분기를 가져야
        # entity_set_session 이 initiative 파일에 쓴다.
        self.assertIn('entity_type == "initiative"', src)
        self.assertIn("cp.initiative_file", src)

    def test_event_recompute_includes_initiative(self):
        src = _EVENT.read_text(encoding="utf-8")
        self.assertIn('("issue", "project", "initiative")', src)
        self.assertIn("cp.initiative_file", src)

    def test_wake_entity_types_includes_initiative(self):
        src = _WAKE.read_text(encoding="utf-8")
        # _ENTITY_TYPES 에 initiative 가 있어야 since-precheck race 방어가 동작.
        tree = _tree(_WAKE)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_ENTITY_TYPES" for t in node.targets)
            ):
                members = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
                self.assertEqual(members, {"issue", "project", "initiative"})
                return
        self.fail("_ENTITY_TYPES 정의를 찾지 못함")


if __name__ == "__main__":
    unittest.main()
