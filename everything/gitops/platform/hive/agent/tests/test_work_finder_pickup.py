"""waiting 상태 entity 의 댓글 기반 자동 픽업 + 신규 progress 발급 검증.

핵심 동작:
  - waiting 인 issue·project 에 사용자가 댓글을 남기면 work_finder 가 progress action 으로 픽업
  - error 는 자동 픽업 안 함 (사람이 명시 전이해야 함)
  - todo/running/cleanup 인 issue 도 progress action 으로 발급
  - phase 분기는 prompt spec 안에서 LLM 이 판단 — work_finder 는 단일 `progress` action 만 발급
"""

import unittest
from types import SimpleNamespace

from app import work_finder


_ACTOR_TO_PRINCIPAL = {
    "human": ("user", "user:test@example.com"),
    "ai": ("worker", "worker:w-test"),
    "system": ("system", "system:test"),
}


def _comment(event_id: str, *, actor: str, ts: str, text: str = "", subtype: str = "discussion",
             payload: dict | None = None, parent_event_id: str | None = None) -> dict:
    data: dict = {"text": text, "subtype": subtype}
    if payload is not None:
        data["payload"] = payload
    if parent_event_id is not None:
        data["parent_event_id"] = parent_event_id
    ptype, pid = _ACTOR_TO_PRINCIPAL.get(actor, ("system", "system:test"))
    return {
        "kind": "comment", "event_id": event_id, "ts": ts,
        "principal_type": ptype, "principal_id": pid, "data": data,
    }


class FakeClient:
    """work_finder 가 호출하는 hub_client 메서드만 구현한 fake."""

    def __init__(self, *, projects=None, standalone_issues=None, issues_by_project=None,
                 events=None, initiatives=None, projects_by_initiative=None):
        self._goals = projects or []
        self._standalone_tasks = standalone_issues or []
        self._issues_by_project = issues_by_project or {}
        self._events = events or {}  # {(entity_id, entity_type): [event, ...]}
        self._initiatives = initiatives or []           # active initiatives
        self._projects_by_initiative = projects_by_initiative or {}  # {iid: [project, ...]}

    def get_all_goals(self):
        return list(self._goals)

    def get_tasks(self, project_id):
        return list(self._issues_by_project.get(project_id, []))

    def get_issues_without_project(self):
        return list(self._standalone_tasks)

    def get_all_initiatives(self):
        return list(self._initiatives)

    def get_initiative_projects(self, initiative_id):
        return list(self._projects_by_initiative.get(initiative_id, []))

    def get_events(self, entity_id, entity_type, *, kinds=None, limit=200):
        feed = list(self._events.get((entity_id, entity_type), []))
        if kinds is not None:
            feed = [e for e in feed if e.get("kind") in kinds]
        return feed


def _make_ctx(client: FakeClient) -> SimpleNamespace:
    return SimpleNamespace(client=client)


class BuildPickupActionTests(unittest.TestCase):
    def test_pending_user_comment_yields_progress_for_issue(self):
        issue = {"issue_id": "t1", "status": "waiting", "title": "task1"}
        events = [
            _comment("e_handoff", actor="ai", ts="2026-05-01T00:00:00Z",
                     subtype="handoff", payload={"reason": "needs_human"}),
            _comment("e_user", actor="human", ts="2026-05-02T00:00:00Z",
                     text="PR 머지 완료"),
        ]
        client = FakeClient(events={("t1", "issue"): events})
        action = work_finder._build_pickup_action(issue, "issue", _make_ctx(client))
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "progress")
        self.assertEqual(action.entity["issue_id"], "t1")
        self.assertEqual(action.priority, 1)

    def test_user_comment_already_replied_skips(self):
        issue = {"issue_id": "t1", "status": "waiting", "title": "task1"}
        events = [
            _comment("e_handoff", actor="ai", ts="2026-05-01T00:00:00Z",
                     subtype="handoff", payload={"reason": "needs_human"}),
            _comment("e_user", actor="human", ts="2026-05-02T00:00:00Z",
                     text="질문"),
            _comment("e_reply", actor="ai", ts="2026-05-02T01:00:00Z",
                     text="답변", parent_event_id="e_user"),
        ]
        client = FakeClient(events={("t1", "issue"): events})
        self.assertIsNone(work_finder._build_pickup_action(issue, "issue", _make_ctx(client)))

    def test_no_events_no_pickup(self):
        issue = {"issue_id": "t1", "status": "waiting", "title": "task1"}
        client = FakeClient(events={})
        self.assertIsNone(work_finder._build_pickup_action(issue, "issue", _make_ctx(client)))


class FindAllWorkTests(unittest.TestCase):
    def test_standalone_waiting_task_with_pending_comment_picked(self):
        issue = {"issue_id": "t1", "status": "waiting", "title": "task1", "dependencies": []}
        events = [
            _comment("e_handoff", actor="ai", ts="2026-05-01T00:00:00Z",
                     subtype="handoff", payload={"reason": "needs_human"}),
            _comment("e_user", actor="human", ts="2026-05-02T00:00:00Z", text="끝났어"),
        ]
        client = FakeClient(standalone_issues=[issue], events={("t1", "issue"): events})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "progress")
        self.assertEqual(actions[0].entity["issue_id"], "t1")

    def test_error_task_not_picked(self):
        issue = {"issue_id": "t1", "status": "error", "title": "task1", "dependencies": []}
        events = [
            _comment("e_halt", actor="ai", ts="2026-05-01T00:00:00Z",
                     subtype="halt", payload={"reason": "needs_human"}),
            _comment("e_user", actor="human", ts="2026-05-02T00:00:00Z", text="retry"),
        ]
        client = FakeClient(standalone_issues=[issue], events={("t1", "issue"): events})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_done_issue_with_pending_comment_not_picked(self):
        # INFRA-ISSUE-263: terminal(done/cancelled) issue 는 미응답 사용자 댓글이 있어도
        # 자동 픽업 안 함 — terminal+pending reply 가 실패 시 매 cycle 재dispatch 하던
        # 토큰 폭주 루프 차단. terminal 댓글은 사람이 처리하거나 새 entity 로 잇는다.
        issue = {"issue_id": "t1", "status": "done", "title": "task1", "dependencies": []}
        events = [
            _comment("e_user", actor="human", ts="2026-05-02T00:00:00Z", text="고마워, 추가 질문"),
        ]
        client = FakeClient(standalone_issues=[issue], events={("t1", "issue"): events})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_cancelled_issue_with_pending_comment_not_picked(self):
        issue = {"issue_id": "t1", "status": "cancelled", "title": "task1", "dependencies": []}
        events = [
            _comment("e_user", actor="human", ts="2026-05-02T00:00:00Z", text="재개?"),
        ]
        client = FakeClient(standalone_issues=[issue], events={("t1", "issue"): events})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_done_project_with_pending_comment_not_picked(self):
        # 컨테이너 terminal(done/archive)도 동일 — pending 필드가 있어도 미픽업.
        project = {"project_id": "g1", "status": "done",
                   "pending_user_comment_event_ids": ["e_u"]}
        client = FakeClient(projects=[project], events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_waiting_without_pending_comment_not_picked(self):
        issue = {"issue_id": "t1", "status": "waiting", "title": "task1", "dependencies": []}
        events = [
            _comment("e_handoff", actor="ai", ts="2026-05-01T00:00:00Z",
                     subtype="handoff", payload={"reason": "needs_human"}),
        ]
        client = FakeClient(standalone_issues=[issue], events={("t1", "issue"): events})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_todo_task_yields_progress(self):
        issue = {"issue_id": "t1", "status": "todo", "title": "task1", "dependencies": []}
        client = FakeClient(standalone_issues=[issue], events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "progress")
        self.assertEqual(actions[0].priority, 1)

    def test_running_task_yields_progress(self):
        issue = {"issue_id": "t1", "status": "running", "title": "task1",
                "description": "기존 plan", "dependencies": []}
        client = FakeClient(standalone_issues=[issue], events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "progress")

    def test_cleanup_task_yields_progress_priority_0(self):
        issue = {"issue_id": "t1", "status": "cleanup", "title": "task1", "dependencies": []}
        client = FakeClient(standalone_issues=[issue], events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "progress")
        self.assertEqual(actions[0].priority, 0)  # cleanup 우선

    def test_active_goal_active_child_task_yields_progress(self):
        project = {"project_id": "g1", "status": "active"}
        child = {"issue_id": "t1", "project_id": "g1", "status": "running", "dependencies": []}
        client = FakeClient(
            projects=[project],
            issues_by_project={"g1": [child]},
            events={},
        )
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "progress")
        self.assertEqual(actions[0].entity["issue_id"], "t1")

    def test_active_goal_cleanup_child_yields_priority_0(self):
        project = {"project_id": "g1", "status": "active"}
        cleanup_issue = {"issue_id": "t1", "project_id": "g1", "status": "cleanup", "dependencies": []}
        client = FakeClient(
            projects=[project],
            issues_by_project={"g1": [cleanup_issue]},
            events={},
        )
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "progress")
        self.assertEqual(actions[0].priority, 0)

    def test_backlog_goal_not_self_picked(self):
        # backlog = pre-launch (launch 게이트) — project-self action 안 나간다.
        project = {"project_id": "g1", "status": "backlog"}
        client = FakeClient(projects=[project], events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_backlog_goal_does_not_block_child_issue(self):
        # backlog parent 라도 자식 issue 는 자기 status 로 그대로 픽업 (parent 와 직교).
        project = {"project_id": "g1", "status": "backlog"}
        child = {"issue_id": "t1", "project_id": "g1", "status": "todo", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [child]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t1"])

    def test_archive_goal_skipped(self):
        # archive = terminal — 자식 fetch 도, self-action 도 없다.
        project = {"project_id": "g1", "status": "archive"}
        client = FakeClient(projects=[project], events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_waiting_goal_not_self_picked(self):
        # waiting = 사람 대기로 parked — pending 댓글이 없으면 self-action 도 reply 도 없다.
        project = {"project_id": "g1", "status": "waiting"}
        client = FakeClient(projects=[project], events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_waiting_goal_no_self_action_even_with_done_children(self):
        # 자식이 모두 done 이어도 waiting 컨테이너는 self-completion progress 가 안 나간다
        # (classify_goal_actions 가 active 한정) — 오직 pending 댓글 reply 만.
        project = {"project_id": "g1", "status": "waiting"}
        done = {"issue_id": "t1", "project_id": "g1", "status": "done", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [done]}, events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_waiting_goal_with_pending_comment_picked_for_reply(self):
        # waiting + pending 사용자 댓글 → reply 위해 progress 픽업 (pending 필드 기반).
        project = {"project_id": "g1", "status": "waiting",
                   "pending_user_comment_event_ids": ["e_u"]}
        client = FakeClient(projects=[project], events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["project_id"] for a in actions], ["g1"])
        self.assertEqual(actions[0].type, "progress")
        self.assertEqual(actions[0].priority, 2)

    def test_held_waiting_goal_with_pending_comment_not_picked(self):
        # hold=true → 수동 steering 보호. waiting + pending 이어도 픽업 제외.
        project = {"project_id": "g1", "status": "waiting", "hold": True,
                   "pending_user_comment_event_ids": ["e_u"]}
        client = FakeClient(projects=[project], events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_active_goal_all_children_done_yields_self_completion(self):
        # active project + 자식 issue 전부 done → project-self §B(완료 판단) progress.
        # scheduler.classify_goal_actions 가 self-completion 을 `status == "active"` 로
        # 게이트하므로 통합 컨테이너 모델에서 정상 발급된다.
        project = {"project_id": "g1", "status": "active"}
        done = {"issue_id": "t1", "project_id": "g1", "status": "done", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [done]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "progress")
        self.assertEqual(actions[0].entity["project_id"], "g1")
        self.assertEqual(actions[0].priority, 2)


class HoldFlagTests(unittest.TestCase):
    """hold=True entity 는 status 와 무관하게 자동 픽업에서 제외된다 (개인 세션 보호).

    hold 는 그 entity **자신만** 멈춘다 — project→자식 issue cascade 는 없다.
    held project 은 project 자신의 self-action 만 막히고, 그 자식 issue 는
    각자 issue.hold 로만 판단되어 그대로 픽업된다.
    """

    def test_held_standalone_task_not_picked(self):
        issue = {"issue_id": "t1", "status": "todo", "title": "t1",
                "dependencies": [], "hold": True}
        client = FakeClient(standalone_issues=[issue], events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_unheld_standalone_task_still_picked(self):
        issue = {"issue_id": "t1", "status": "todo", "title": "t1",
                "dependencies": [], "hold": False}
        client = FakeClient(standalone_issues=[issue], events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].entity["issue_id"], "t1")

    def test_held_active_goal_child_task_still_picked(self):
        """cascade 제거: held active project 의 자식 issue 는 그대로 픽업된다."""
        project = {"project_id": "g1", "status": "active", "hold": True}
        child = {"issue_id": "t1", "project_id": "g1", "status": "todo", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [child]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t1"])

    def test_held_active_goal_self_progress_not_emitted(self):
        """자식이 모두 done 이어도 held project 자신은 완료-판단 progress 가 안 나간다."""
        project = {"project_id": "g1", "status": "active", "hold": True}
        done = {"issue_id": "t1", "project_id": "g1", "status": "done", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [done]}, events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_held_child_task_skipped_under_held_goal_sibling_still_picked(self):
        """held project + held 자식 1 + 정상 자식 1 → 정상 자식만 픽업."""
        project = {"project_id": "g1", "status": "active", "hold": True}
        held = {"issue_id": "t1", "project_id": "g1", "status": "todo",
                "dependencies": [], "hold": True}
        sibling = {"issue_id": "t2", "project_id": "g1", "status": "todo", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [held, sibling]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t2"])

    def test_held_backlog_goal_not_picked(self):
        project = {"project_id": "g1", "status": "backlog", "hold": True}
        client = FakeClient(projects=[project], events={})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_held_child_task_skipped_sibling_still_picked(self):
        project = {"project_id": "g1", "status": "active"}
        held = {"issue_id": "t1", "project_id": "g1", "status": "todo",
                "dependencies": [], "hold": True}
        sibling = {"issue_id": "t2", "project_id": "g1", "status": "todo", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [held, sibling]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t2"])

    def test_held_waiting_task_with_pending_comment_not_picked(self):
        issue = {"issue_id": "t1", "status": "waiting", "title": "t1",
                "dependencies": [], "hold": True}
        events = [
            _comment("e_h", actor="ai", ts="2026-05-01T00:00:00Z",
                     subtype="handoff", payload={"reason": "x"}),
            _comment("e_u", actor="human", ts="2026-05-02T00:00:00Z", text="가자"),
        ]
        client = FakeClient(standalone_issues=[issue], events={("t1", "issue"): events})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])


class ParentStatusDoesNotGateChildTests(unittest.TestCase):
    """parent container (project) status 는 자식 issue 의 자율 진행을 막지 않는다.

    Project 은 4-status 컨테이너 (backlog/active) — 자식 issue 는 자기 8-status 워커
    모델대로 진행하고, parent 상태와 직교하게 픽업된다. 자식 pickup 은 자식 자신의
    status·hold·dep 만 본다.
    """

    def test_active_parent_goal_active_child_issue_progresses(self):
        """parent active — 자식 todo issue 는 progress 발급."""
        project = {"project_id": "g1", "status": "active"}
        child = {"issue_id": "t1", "project_id": "g1", "status": "todo", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [child]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t1"])
        self.assertEqual(actions[0].priority, 1)

    def test_active_parent_goal_cleanup_child_priority_0(self):
        project = {"project_id": "g1", "status": "active"}
        child = {"issue_id": "t1", "project_id": "g1", "status": "cleanup", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [child]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t1"])
        self.assertEqual(actions[0].priority, 0)

    def test_backlog_parent_active_child_still_progresses(self):
        """parent backlog (pre-launch) 라도 자식 issue 는 자기 status 로 그대로 픽업."""
        project = {"project_id": "g1", "status": "backlog"}
        child = {"issue_id": "t1", "project_id": "g1", "status": "todo", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [child]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t1"])

    def test_held_backlog_parent_active_child_still_picked(self):
        """hold cascade 제거 — held backlog parent 의 자식 todo 도 픽업된다."""
        project = {"project_id": "g1", "status": "backlog", "hold": True}
        child = {"issue_id": "t1", "project_id": "g1", "status": "todo", "dependencies": []}
        client = FakeClient(projects=[project], issues_by_project={"g1": [child]}, events={})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["issue_id"] for a in actions], ["t1"])


class FindPendingUserCommentsTests(unittest.TestCase):
    """`_find_pending_user_comments` + `_pending_chains` chain-aware 동작 검증.

    ITEMS-ISSUE-15 회귀(2026-05-23): 사용자가 자기 root 코멘트에 reply 를 달면 기존
    구현이 root 를 replied 로 마킹해 워커 입력에서 사라지는 결함. 새 계약 — AI/worker
    reply 만 replied 로 마킹, head dedup 으로 chain 안의 후손 pending 은 replies 로 묶음.
    """

    def test_user_self_reply_keeps_root_pending(self):
        events = [
            _comment("e_root", actor="human", ts="2026-05-23T21:24:53Z", text="피드백 3종"),
            _comment("e_child", actor="human", ts="2026-05-23T21:25:28Z",
                     parent_event_id="e_root", text="one_pager 가 아닌 문서는 삭제 필요"),
        ]
        heads = work_finder._find_pending_user_comments(events)
        self.assertEqual([h["event_id"] for h in heads], ["e_root"])

        chains = work_finder._pending_chains(heads, events)
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["head"]["event_id"], "e_root")
        self.assertEqual([r["event_id"] for r in chains[0]["replies"]], ["e_child"])

    def test_ai_reply_to_root_promotes_unreplied_child(self):
        events = [
            _comment("e_root", actor="human", ts="2026-05-01T00:00:00Z", text="질문 A"),
            _comment("e_child", actor="human", ts="2026-05-01T00:01:00Z",
                     parent_event_id="e_root", text="추가 질문 B"),
            _comment("e_ai", actor="ai", ts="2026-05-01T00:02:00Z",
                     parent_event_id="e_root", text="A 에 대한 답"),
        ]
        heads = work_finder._find_pending_user_comments(events)
        self.assertEqual([h["event_id"] for h in heads], ["e_child"])

        chains = work_finder._pending_chains(heads, events)
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["head"]["event_id"], "e_child")
        self.assertEqual(chains[0]["replies"], [])

    def test_ai_reply_to_all_yields_empty_pending(self):
        events = [
            _comment("e_root", actor="human", ts="2026-05-01T00:00:00Z", text="질문 A"),
            _comment("e_child", actor="human", ts="2026-05-01T00:01:00Z",
                     parent_event_id="e_root", text="추가 질문 B"),
            _comment("e_ai_root", actor="ai", ts="2026-05-01T00:02:00Z",
                     parent_event_id="e_root", text="A 답"),
            _comment("e_ai_child", actor="ai", ts="2026-05-01T00:03:00Z",
                     parent_event_id="e_child", text="B 답"),
        ]
        heads = work_finder._find_pending_user_comments(events)
        self.assertEqual(heads, [])

        chains = work_finder._pending_chains(heads, events)
        self.assertEqual(chains, [])


class InitiativeFindWorkTests(unittest.TestCase):
    """active Initiative 의 self-progress 발급 — Project todo/running 을 자식 Project
    존재 여부로 대신 (initiative 는 3-state). planned/completed 은 get_active_initiatives
    가 애초에 반환 안 함 (status=active 필터)."""

    def test_active_initiative_no_children_yields_progress(self):
        # §A: 자식 미생성 → self-progress (plan + 자식 Project 생성).
        ini = {"initiative_id": "I1", "status": "active", "name": "n"}
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": []})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["initiative_id"] for a in actions], ["I1"])
        self.assertEqual(actions[0].priority, 3)  # 전략 tier — issue/project 뒤

    def test_active_initiative_all_children_done_yields_progress(self):
        # §B: 자식 Project 전부 terminal(done/archive) → self-progress (완료 판단).
        ini = {"initiative_id": "I1", "status": "active", "name": "n"}
        projects = [
            {"project_id": "g1", "status": "done"},
            {"project_id": "g2", "status": "archive"},
        ]
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": projects})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["initiative_id"] for a in actions], ["I1"])

    def test_active_initiative_with_active_child_idles(self):
        # 활성 자식 Project ≥1 → idle (자식 Project 워커가 일함, child→initiative cascade 가 깨움).
        ini = {"initiative_id": "I1", "status": "active", "name": "n"}
        projects = [
            {"project_id": "g1", "status": "running"},
            {"project_id": "g2", "status": "done"},
        ]
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": projects})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_active_initiative_active_child_but_pending_comment_picked(self):
        # 자식 활동 중이라 self-action 은 없지만 미응답 사용자 댓글엔 reply 진입.
        ini = {"initiative_id": "I1", "status": "active", "name": "n",
               "pending_user_comment_event_ids": ["e_u"]}
        projects = [{"project_id": "g1", "status": "running"}]
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": projects})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["initiative_id"] for a in actions], ["I1"])
        self.assertEqual(actions[0].priority, 3)

    def test_waiting_initiative_not_self_picked(self):
        # waiting initiative + pending 없음 → self-action 도 reply 도 없다 (parked).
        ini = {"initiative_id": "I1", "status": "waiting", "name": "n"}
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": []})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_waiting_initiative_no_self_action_even_with_no_children(self):
        # §A(자식 미생성) 조건이어도 waiting 은 self-action 안 냄 — active 한정.
        ini = {"initiative_id": "I1", "status": "waiting", "name": "n",
               "pending_user_comment_event_ids": ["e_u"]}
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": []})
        actions = work_finder.find_all_work(_make_ctx(client))
        # pending 댓글이 있으니 reply 픽업은 1건, self-action(§A)은 없음 → 정확히 1건.
        self.assertEqual([a.entity["initiative_id"] for a in actions], ["I1"])
        self.assertEqual(actions[0].priority, 3)

    def test_waiting_initiative_with_pending_comment_picked_for_reply(self):
        ini = {"initiative_id": "I1", "status": "waiting", "name": "n",
               "pending_user_comment_event_ids": ["e_u"]}
        projects = [{"project_id": "g1", "status": "done"}]
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": projects})
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["initiative_id"] for a in actions], ["I1"])
        self.assertEqual(actions[0].priority, 3)

    def test_waiting_initiative_without_pending_not_picked(self):
        ini = {"initiative_id": "I1", "status": "waiting", "name": "n"}
        projects = [{"project_id": "g1", "status": "done"}]
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": projects})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_held_waiting_initiative_with_pending_not_picked(self):
        ini = {"initiative_id": "I1", "status": "waiting", "name": "n", "hold": True,
               "pending_user_comment_event_ids": ["e_u"]}
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": []})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_held_active_initiative_not_picked(self):
        # hold=true → 수동 steering 보호, 자동 픽업 제외 (self-action 도 pending reply 도 X).
        ini = {"initiative_id": "I1", "status": "active", "name": "n", "hold": True,
               "pending_user_comment_event_ids": ["e_u"]}
        client = FakeClient(initiatives=[ini], projects_by_initiative={"I1": []})
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_initiative_action_ordered_after_issue_and_project(self):
        # priority 정렬: issue(1) < project self(2) < initiative(3).
        ini = {"initiative_id": "I1", "status": "active", "name": "n"}
        issue = {"issue_id": "t1", "status": "todo", "title": "t", "dependencies": []}
        client = FakeClient(
            standalone_issues=[issue],
            initiatives=[ini], projects_by_initiative={"I1": []},
        )
        actions = sorted(work_finder.find_all_work(_make_ctx(client)), key=lambda a: a.priority)
        self.assertEqual(actions[0].entity.get("issue_id"), "t1")
        self.assertEqual(actions[-1].entity.get("initiative_id"), "I1")

    def test_frame_initiative_with_subinitiative_skipped(self):
        # frame(자식이 sub-initiative) 은 직속 Project 0 이어도 §A 로 진입하면 안 됨 —
        # 영구 anchor, 사람/CEO 관리. leaf 자식만 자율 오케스트레이션.
        frame = {"initiative_id": "I-FRAME", "status": "active", "name": "frame"}
        leaf = {"initiative_id": "I-LEAF", "status": "active", "name": "leaf",
                "parent_initiative_id": "I-FRAME"}
        client = FakeClient(
            initiatives=[frame, leaf],
            projects_by_initiative={"I-FRAME": [], "I-LEAF": []},
        )
        actions = work_finder.find_all_work(_make_ctx(client))
        # frame 은 제외, leaf 만 §A self-progress.
        self.assertEqual([a.entity["initiative_id"] for a in actions], ["I-LEAF"])

    def test_frame_skipped_even_when_subinitiative_completed(self):
        # 자식 sub-initiative 가 completed(=비활성)여도 parent 는 여전히 frame —
        # parentage 는 status 무관 (frame 의 §B 완료는 사람이 한다).
        frame = {"initiative_id": "I-FRAME", "status": "active", "name": "frame"}
        leaf = {"initiative_id": "I-LEAF", "status": "completed", "name": "leaf",
                "parent_initiative_id": "I-FRAME"}
        client = FakeClient(
            initiatives=[frame, leaf],
            projects_by_initiative={"I-FRAME": []},
        )
        # frame 제외 + leaf 는 completed 라 active 필터에서 빠짐 → 빈 큐.
        self.assertEqual(work_finder.find_all_work(_make_ctx(client)), [])

    def test_leaf_initiative_with_parent_still_orchestrated(self):
        # 부모가 있어도(sub-initiative) 자기 자식이 없으면 leaf — 정상 오케스트레이션.
        leaf = {"initiative_id": "I-LEAF", "status": "active", "name": "leaf",
                "parent_initiative_id": "I-FRAME"}
        client = FakeClient(
            initiatives=[leaf],  # 부모 frame 은 이 목록에 없어도(다른 이유로) leaf 는 leaf
            projects_by_initiative={"I-LEAF": []},
        )
        actions = work_finder.find_all_work(_make_ctx(client))
        self.assertEqual([a.entity["initiative_id"] for a in actions], ["I-LEAF"])


if __name__ == "__main__":
    unittest.main()
