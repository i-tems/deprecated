"""Worker entity context — intent / plan 슬롯 포함 회귀 가드 (INFRA-ISSUE-46).

T1 (i-tems/everything#298) 으로 hub schema 에 intent·plan 슬롯이 추가됐고,
T3 (i-tems/hive#65) 로 phase spec 이 이를 채택했다. 워커가 두 슬롯을 실제로
받을 수 있도록 prompt_builders SLIM 필드와 work_finder sibling slim 에 두
필드가 포함돼 있어야 한다.

검증:
  1. _GOAL_SLIM_FIELDS / _TASK_SLIM_FIELDS 에 intent · plan 포함.
  2. build_issue_progress / build_project_progress 출력에 intent · plan 값이
     실제로 dump 됨 (값이 None 이 아닐 때).
  3. work_finder._slim_sibling_issue 에 intent 포함 (worker 가 sibling
     의도 파악 — plan 은 sibling 의 working draft 라 제외).
"""

from __future__ import annotations

import unittest

from app import prompt_builders, work_finder


class TestSlimFieldsContainIntentAndPlan(unittest.TestCase):
    def test_goal_slim_includes_intent_and_plan(self):
        self.assertIn("intent", prompt_builders._GOAL_SLIM_FIELDS)
        self.assertIn("plan", prompt_builders._GOAL_SLIM_FIELDS)

    def test_task_slim_includes_intent_and_plan(self):
        self.assertIn("intent", prompt_builders._TASK_SLIM_FIELDS)
        self.assertIn("plan", prompt_builders._TASK_SLIM_FIELDS)


class TestPromptIncludesIntentAndPlan(unittest.TestCase):
    def setUp(self):
        self.factory = prompt_builders.PromptFactory(hub_url="https://hub.test")

    def test_task_intent_and_plan_in_prompt(self):
        issue = {
            "issue_id": "t1",
            "title": "Demo",
            "status": "running",
            "intent": "## Outcome\nDemo done\n## Scope\n**In-scope**: demo",
            "plan": "## Plan\n1. step",
            "description": "background facts",
        }
        out = self.factory.build_issue_progress(issue)
        self.assertIn("Demo done", out)
        self.assertIn("1. step", out)
        self.assertIn("background facts", out)

    def test_goal_intent_and_plan_in_prompt(self):
        project = {
            "project_id": "g1",
            "title": "G",
            "status": "running",
            "intent": "## Outcome\nG done",
            "plan": "## Plan\n- a",
        }
        out = self.factory.build_project_progress(project)
        self.assertIn("G done", out)
        self.assertIn("- a", out)

    def test_null_fields_not_dumped(self):
        # intent/plan 이 None 이면 slim 결과에 키 자체가 안 들어와야 함 (_slim 의 v is not None 필터).
        issue = {"issue_id": "t1", "title": "T", "status": "todo",
                "intent": None, "plan": None, "description": "notes only"}
        out = self.factory.build_issue_progress(issue)
        self.assertNotIn('"intent":', out)
        self.assertNotIn('"plan":', out)
        self.assertIn("notes only", out)


class TestSiblingSlimIncludesIntent(unittest.TestCase):
    def test_sibling_slim_has_intent_no_plan(self):
        slim = work_finder._slim_sibling_issue({
            "issue_id": "t2", "title": "Sibling", "status": "running",
            "intent": "## Outcome\ndo X", "description": "background",
            "plan": "## Plan\nshould not leak",
        })
        self.assertEqual(slim.get("intent"), "## Outcome\ndo X")
        self.assertNotIn("plan", slim)
        # description 은 사실/맥락 슬롯 — sibling 의 누적 노트도 worker 가 활용 가능하도록 유지.
        self.assertEqual(slim.get("description"), "background")


if __name__ == "__main__":
    unittest.main()
