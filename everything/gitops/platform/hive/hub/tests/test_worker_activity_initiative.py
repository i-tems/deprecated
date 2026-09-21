"""worker.activity_push/list/history 가 entity_type="initiative" 를 수용하는지.

Initiative 가 active 한정 worker entity 가 되면서 워커 runtime 의 activity_relay 가
entity_type=initiative 로 push 한다. 세 핸들러가 issue/project 만 허용하면 push 가
422 로 거부되어 UI AI Activity 패널에 아무것도 안 뜬다 (백엔드에 저장조차 안 됨).

hub 테스트 규약상 app import 금지 — 소스에서 entity_type 게이트 문자열을 검증한다.
"""

import unittest
from pathlib import Path

_WORKER = Path(__file__).resolve().parents[1] / "app" / "entities" / "worker.py"


class WorkerActivityInitiativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _WORKER.read_text(encoding="utf-8")

    def test_no_issue_project_only_gate_remains(self):
        # 회귀: ("issue", "project") 단독 게이트가 남아 있으면 initiative push 가 거부됨.
        self.assertNotIn(
            'entity_type not in ("issue", "project")', self.src,
            "activity 게이트가 아직 issue/project 만 허용 — initiative push 가 422 거부됨",
        )

    def test_three_handlers_accept_initiative(self):
        # push / list / history 세 핸들러 모두 initiative 포함 게이트여야 한다.
        self.assertEqual(
            self.src.count('("issue", "project", "initiative")'), 3,
            "activity_push/list/history 세 곳 모두 initiative 를 수용해야 한다",
        )


if __name__ == "__main__":
    unittest.main()
