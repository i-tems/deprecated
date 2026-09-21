"""Initiative 를 agent-loop worker 로 점화한 변경(PR-3)의 핵심 계약 검증.

- models: entity type 디스패치. **Project 레코드는 부모참조 initiative_id 필드를 갖는데
  initiative 로 오분류되면 안 된다** (project_id 를 먼저 봐야 함) — 회귀 시 Project 워커가
  initiative_progress 로 잘못 라우팅된다.
- scheduler.classify_initiative_actions: 자식 Project 존재/완료 여부로 §A/§B/idle 결정.
- post_turn_guard: Initiative 엔 error/waiting/force_update 가 없으므로 hard 에러는
  hold=true 로 루프 차단, soft 에러는 status 유지(재시도), 둘 다 halt event + session reset.
"""

import unittest
from types import SimpleNamespace

from app import models
from app.scheduler import classify_initiative_actions
from app.phase_handlers.post import post_turn_guard


class EntityTypeDispatchTests(unittest.TestCase):
    def test_initiative_classified(self):
        ini = {"initiative_id": "I1", "status": "active"}
        self.assertEqual(models.entity_type_of(ini), "initiative")
        self.assertEqual(models.session_type_of(ini), "initiative_progress")
        self.assertEqual(models.action_entity_id(models.Action("progress", entity=ini)), "I1")

    def test_project_with_initiative_id_stays_project(self):
        # 회귀 핵심: Project 는 부모참조 initiative_id 를 갖는다 — project_id 우선 분류.
        proj = {"project_id": "g1", "initiative_id": "I1", "status": "running"}
        self.assertEqual(models.entity_type_of(proj), "project")
        self.assertEqual(models.action_entity_id(models.Action("progress", entity=proj)), "g1")

    def test_issue_precedence(self):
        issue = {"issue_id": "t1", "project_id": "g1"}
        self.assertEqual(models.entity_type_of(issue), "issue")

    def test_id_field_for_initiative(self):
        self.assertEqual(models.id_field_for("initiative"), "initiative_id")
        self.assertEqual(models.id_field_for("issue"), "issue_id")
        self.assertEqual(models.id_field_for("project"), "project_id")


class ClassifyInitiativeActionsTests(unittest.TestCase):
    def _ini(self):
        return {"initiative_id": "I1", "status": "active"}

    def test_no_children_yields_self_progress(self):
        actions = classify_initiative_actions(self._ini(), [])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].entity["initiative_id"], "I1")
        self.assertEqual(actions[0].priority, 3)

    def test_all_children_settled_yields_self_progress(self):
        projects = [{"project_id": "g1", "status": "done"},
                    {"project_id": "g2", "status": "archive"}]
        actions = classify_initiative_actions(self._ini(), projects)
        self.assertEqual(len(actions), 1)

    def test_any_active_child_idles(self):
        for active_status in ("todo", "running", "waiting", "cleanup", "error"):
            projects = [{"project_id": "g1", "status": active_status},
                        {"project_id": "g2", "status": "done"}]
            self.assertEqual(
                classify_initiative_actions(self._ini(), projects), [],
                f"active child status={active_status} 면 idle 이어야 함",
            )


# ── post_turn_guard initiative 분기 ──

class _FakeClient:
    def __init__(self):
        self.api_safe_calls = []

    def api(self, name, params):  # initiative 분기는 fresh status fetch 안 함
        return {"data": {"status": "active"}}

    def api_safe(self, name, data, *, issue_id=None, label=""):
        self.api_safe_calls.append((name, data))
        return {}


def _ctx():
    reset_calls = []
    ctx = SimpleNamespace(
        client=_FakeClient(),
        session_store=SimpleNamespace(reset=lambda eid: reset_calls.append(eid)),
        log=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None,
                            info=lambda *a, **k: None),
    )
    ctx.reset_calls = reset_calls
    return ctx


def _initiative():
    return {"initiative_id": "I1", "name": "n"}


class PostTurnGuardInitiativeTests(unittest.TestCase):
    def test_hard_error_holds_initiative(self):
        # max_turns = force_error 정책 → hold=true 로 루프 차단.
        ctx = _ctx()
        post_turn_guard(ctx, _initiative(), "initiative",
                        {"is_error": True, "subtype": "error_max_turns", "result": "max turns"})
        calls = ctx.client.api_safe_calls
        names = [c[0] for c in calls]
        self.assertIn("event.add", names)            # halt event
        self.assertIn("initiative.update", names)     # hold
        hold_call = next(c for c in calls if c[0] == "initiative.update")
        self.assertEqual(hold_call[1].get("hold"), True)
        # status=error 전이는 절대 없어야 한다 (initiative 엔 error 없음).
        for _, data in calls:
            self.assertNotEqual(data.get("status"), "error")
        self.assertEqual(ctx.reset_calls, ["I1"])

    def test_fail_holds_no_retry(self):
        # 정책 변경: runtime_error 도 force_error → 컨테이너는 hold=true 로 재spawn
        # 차단(재시도 안 함). status=error 는 여전히 없음(컨테이너 모델).
        ctx = _ctx()
        post_turn_guard(ctx, _initiative(), "initiative",
                        {"is_error": True, "subtype": "error_during_execution", "result": "boom"})
        calls = ctx.client.api_safe_calls
        names = [c[0] for c in calls]
        self.assertIn("event.add", names)
        self.assertIn("initiative.update", names)  # hold — 재시도 루프 차단
        hold_call = next(c for c in calls if c[0] == "initiative.update")
        self.assertEqual(hold_call[1].get("hold"), True)
        for _, data in calls:
            self.assertNotEqual(data.get("status"), "error")
        self.assertEqual(ctx.reset_calls, ["I1"])

    def test_no_force_update_endpoint_called(self):
        # initiative 엔 force_update 가 없다 — 어떤 카테고리든 호출 금지.
        for subtype in ("error_max_turns", "error_during_execution", "error_input_too_long"):
            ctx = _ctx()
            post_turn_guard(ctx, _initiative(), "initiative",
                            {"is_error": True, "subtype": subtype, "result": "x"})
            names = [c[0] for c in ctx.client.api_safe_calls]
            self.assertNotIn("initiative.force_update", names)


if __name__ == "__main__":
    unittest.main()
