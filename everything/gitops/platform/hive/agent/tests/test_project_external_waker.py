"""project_has_external_waker — worker 데드락 가드가 스케줄러와 같은 컨테이너 모델로
판단하는지 검증.

통합 컨테이너 모델: Project 의 유일한 능동 status 는 `active`, 이는 Initiative 의
`active` 와 동일하게 idle-ok 다 — 자식 worker 완료 cascade·스케줄러 재pickup·사용자
댓글이 외부 깨움 주체이므로 전이 없이 turn 을 끝내도 데드락이 아니다. 따라서
`active` 컨테이너는 항상 외부 깨움 주체가 있다고 본다 (escalate 금지). 컨테이너엔
waiting/cleanup/error/running/todo 가 없다.
"""

import unittest

from app.scheduler import project_has_external_waker

PROJECT = {"project_id": "ITEMS-PROJECT-1"}


def _t(status):
    return {"issue_id": "t", "status": status}


class GoalExternalWakerTest(unittest.TestCase):
    def test_active_is_idle_not_deadlock(self):
        # active = idle-ok (Initiative active 와 동일). 자식 활동 중이든 모두 종결이든
        # 외부 깨움 주체(자식 cascade·스케줄러 §B 재spawn·사용자 댓글)가 존재.
        self.assertTrue(project_has_external_waker(PROJECT, [_t("running")], "active"))
        self.assertTrue(
            project_has_external_waker(PROJECT, [_t("done"), _t("cancelled")], "active")
        )
        self.assertTrue(project_has_external_waker(PROJECT, [], "active"))

    def test_non_active_status_is_not_waker(self):
        # 컨테이너의 능동 status 는 active 하나뿐 — 그 외(backlog/done/archive)는
        # 이 함수 호출 경로가 아니며 방어적으로 False.
        self.assertFalse(project_has_external_waker(PROJECT, [_t("running")], "backlog"))
        self.assertFalse(project_has_external_waker(PROJECT, [], "done"))


if __name__ == "__main__":
    unittest.main()
