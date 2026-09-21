"""classify_goal_actions 의 형제 직렬화 — 같은 project 자식은 한 번에 1개만 실행.

근거(INFRA-ISSUE-296): ITEMS-PROJECT-12 에서 병렬 형제 4개가 같은 앱 화면을 동시에
고쳐 서로 덮어씀(sibling clobber). 규칙 문장 대신 디스패치 단계에서 구조적으로 차단:
running/cleanup 형제가 있으면 새 todo 미시작, 시작은 한 번에 1개 (높은 priority_score
먼저, 같으면 생성순).
"""

import unittest

from app.scheduler import classify_goal_actions


def _proj(status="active", pid="P-1"):
    return {"project_id": pid, "status": status}


def _issue(iid, status, *, seq=0, priority_score=0, deps=None):
    return {
        "issue_id": iid, "status": status, "seq": seq,
        "priority_score": priority_score, "dependencies": deps or [],
    }


class SiblingSerializationTest(unittest.TestCase):
    def test_two_todos_only_one_starts(self):
        # 핵심: actionable todo 가 2개여도 시작은 1개 (병렬 clobber 차단).
        issues = [_issue("I-1", "todo", seq=1), _issue("I-2", "todo", seq=2)]
        actions = classify_goal_actions(_proj(), issues)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].entity["issue_id"], "I-1")  # 생성순

    def test_priority_score_wins_over_seq(self):
        issues = [_issue("I-1", "todo", seq=1, priority_score=50),
                  _issue("I-2", "todo", seq=2, priority_score=100)]
        actions = classify_goal_actions(_proj(), issues)
        self.assertEqual([a.entity["issue_id"] for a in actions], ["I-2"])

    def test_running_sibling_blocks_new_todo(self):
        issues = [_issue("I-1", "running"), _issue("I-2", "todo")]
        actions = classify_goal_actions(_proj(), issues)
        self.assertEqual([a.entity["issue_id"] for a in actions], ["I-1"])

    def test_cleanup_sibling_blocks_new_todo(self):
        issues = [_issue("I-1", "cleanup"), _issue("I-2", "todo")]
        actions = classify_goal_actions(_proj(), issues)
        self.assertEqual([a.entity["issue_id"] for a in actions], ["I-1"])

    def test_held_running_sibling_blocks_todo_and_self_completion(self):
        # 사람이 hold 로 잡고(--direct) 실행 중인 자식 — 형제 todo 시작도, project
        # 완료 판단도 막혀야 한다 (수동 세션 보호).
        issues = [_issue("I-1", "running"), _issue("I-2", "todo")]
        actions = classify_goal_actions(_proj(), issues, exclude_ids={"I-1"})
        self.assertEqual(actions, [])

    def test_waiting_sibling_does_not_block_todo(self):
        # waiting(사람 대기·suggestion)이 project 전체를 세우지 않는다 — 명시 선택.
        issues = [_issue("I-1", "waiting"), _issue("I-2", "todo")]
        actions = classify_goal_actions(_proj(), issues)
        self.assertEqual([a.entity["issue_id"] for a in actions], ["I-2"])

    def test_dep_blocked_todo_not_started(self):
        issues = [_issue("I-2", "todo", deps=["I-1"])]
        actions = classify_goal_actions(_proj(), issues, status_index={"I-1": "running"})
        self.assertEqual(actions, [])

    def test_dep_satisfied_after_terminal_then_starts(self):
        issues = [_issue("I-2", "todo", deps=["I-1"])]
        actions = classify_goal_actions(_proj(), issues, status_index={"I-1": "done"})
        self.assertEqual([a.entity["issue_id"] for a in actions], ["I-2"])

    def test_all_children_done_self_completion_kept(self):
        # 회귀: 직렬화가 project-self 완료 판단을 깨지 않는다.
        issues = [_issue("I-1", "done"), _issue("I-2", "done")]
        actions = classify_goal_actions(_proj(), issues)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].entity["project_id"], "P-1")

    def test_multiple_running_all_dispatched(self):
        # 이미 병렬로 시작돼 버린 running 형제들(배포 전 잔재)은 그대로 진행 — 단 새
        # todo 는 안 끼어든다.
        issues = [_issue("I-1", "running"), _issue("I-2", "running"), _issue("I-3", "todo")]
        actions = classify_goal_actions(_proj(), issues)
        self.assertEqual(sorted(a.entity["issue_id"] for a in actions), ["I-1", "I-2"])


if __name__ == "__main__":
    unittest.main()
