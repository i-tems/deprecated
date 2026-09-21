"""Project worker per-cycle 컨텍스트 빌더 검증.

회귀 방지 대상 (사용자 보고):
  1. 중복 — resume turn 에 project slim + 자식 description 을 매번 재덤프하던 문제.
     delta 섹션은 description 을 뺀 compact roster(id/title/status)만 담아야 한다.
  2. comment 미주입 — project 이 pending-only 라 activity feed(자기 reply·status_change
     ·사람 대화 스레드)를 전혀 못 보던 문제. full 섹션은 Activity Events 를,
     delta 섹션은 since 이후 새 activity + pending 을 담아야 한다.
"""

import unittest
from types import SimpleNamespace

from app import work_finder


_ACTOR_TO_PRINCIPAL = {
    "human": ("user", "user:test@example.com"),
    "ai": ("worker", "worker:w-test"),
    "system": ("system", "system:test"),
}


def _comment(event_id: str, *, actor: str, ts: str, text: str = "",
             parent_event_id: str | None = None) -> dict:
    data: dict = {"text": text, "subtype": "discussion"}
    if parent_event_id is not None:
        data["parent_event_id"] = parent_event_id
    ptype, pid = _ACTOR_TO_PRINCIPAL.get(actor, ("system", "system:test"))
    return {
        "kind": "comment", "event_id": event_id, "ts": ts,
        "principal_type": ptype, "principal_id": pid, "data": data,
    }


def _status_change(ts: str, frm: str, to: str) -> dict:
    return {"kind": "status_change", "ts": ts, "principal_type": "worker",
            "principal_id": "worker:w-test", "data": {"from": frm, "to": to}}


class FakeClient:
    def __init__(self, events):
        self._events = events  # {(entity_id, entity_type): [event, ...]}

    def get_events(self, entity_id, entity_type, *, kinds=None, limit=200):
        feed = list(self._events.get((entity_id, entity_type), []))
        if kinds is not None:
            feed = [e for e in feed if e.get("kind") in kinds]
        return feed


def _ctx(client) -> SimpleNamespace:
    return SimpleNamespace(client=client)


_GOAL = {
    "project_id": "g1",
    "title": "릴리스 오케스트레이션",
    "description": "정적이라 resume 마다 재주입하면 토큰 낭비인 긴 본문 " * 5,
    "status": "running",
}
_TASKS = [
    {"issue_id": "t1", "title": "빌드", "status": "done",
     "description": "자식 description 도 정적 — roster 에서 빠져야 한다 " * 5},
    {"issue_id": "t2", "title": "배포", "status": "running",
     "description": "또 다른 긴 정적 본문 " * 5},
]


class GoalFullContextTests(unittest.TestCase):
    def test_includes_activity_events_with_comment_thread(self):
        events = [
            _comment("e_user", actor="human", ts="2026-05-01T00:00:00Z", text="A 로 가자"),
            _comment("e_reply", actor="ai", ts="2026-05-01T01:00:00Z",
                     text="A 채택했습니다", parent_event_id="e_user"),
            _status_change("2026-05-01T02:00:00Z", "todo", "running"),
        ]
        ctx = _ctx(FakeClient({("g1", "project"): events}))
        out = work_finder.format_goal_full_context_section(project=_GOAL, ctx=ctx)
        # comment 스레드(사람 + AI reply) + status_change 가 모두 노출된다.
        self.assertIn("Activity Events", out)
        self.assertIn("A 로 가자", out)
        self.assertIn("A 채택했습니다", out)
        self.assertIn("status_change", out)

    def test_pending_user_comment_block_present(self):
        events = [_comment("e_user", actor="human", ts="2026-05-01T00:00:00Z",
                            text="머지했어")]
        ctx = _ctx(FakeClient({("g1", "project"): events}))
        out = work_finder.format_goal_full_context_section(project=_GOAL, ctx=ctx)
        self.assertIn("Pending User Comments", out)
        self.assertIn("머지했어", out)

    def test_empty_when_no_events(self):
        ctx = _ctx(FakeClient({}))
        self.assertEqual(work_finder.format_goal_full_context_section(project=_GOAL, ctx=ctx), "")


class GoalDeltaSectionTests(unittest.TestCase):
    def _delta(self, events, since):
        ctx = _ctx(FakeClient({("g1", "project"): events}))
        return work_finder.format_goal_delta_section(
            project=_GOAL, issues=_TASKS, since=since, ctx=ctx
        )

    def test_no_static_redump_goal_slim_or_child_descriptions(self):
        out = self._delta([], since="2026-05-01T00:00:00Z")
        # 문제 1: project description / 자식 description 은 resume 컨텍스트에서 빠진다.
        self.assertNotIn("토큰 낭비인 긴 본문", out)
        self.assertNotIn("roster 에서 빠져야 한다", out)

    def test_child_status_roster_always_present(self):
        out = self._delta([], since="2026-05-01T00:00:00Z")
        # 자식 status 는 휘발 — since 와 무관하게 compact roster 로 항상 갱신.
        self.assertIn("자식 상태 roster", out)
        for token in ("t1", "t2", "done", "running", "빌드", "배포"):
            self.assertIn(token, out)

    def test_new_activity_since_only(self):
        events = [
            _comment("old", actor="human", ts="2026-05-01T00:00:00Z", text="옛 코멘트"),
            _comment("new", actor="human", ts="2026-05-03T00:00:00Z", text="새 코멘트"),
        ]
        out = self._delta(events, since="2026-05-02T00:00:00Z")
        self.assertIn("새 Activity", out)
        self.assertIn("새 코멘트", out)
        # since 이전 코멘트는 새 Activity 블록엔 없지만, 미응답이라 pending 으로 노출.
        self.assertIn("Pending User Comments", out)
        self.assertIn("옛 코멘트", out)

    def test_pending_survives_even_when_no_new_activity(self):
        events = [_comment("u", actor="human", ts="2026-05-01T00:00:00Z", text="대기 코멘트")]
        out = self._delta(events, since="2026-06-01T00:00:00Z")
        self.assertIn("Pending User Comments", out)
        self.assertIn("대기 코멘트", out)
        self.assertNotIn("새 Activity", out)

    def test_child_status_change_since_exposed(self):
        # BEAUTY-PROJECT-3 회귀: 자식 transition 이 부모 event feed 에 없어 claude 가
        # roster=done 인데도 옛 인상으로 idle 코멘트 작성 → no_progress 가드로 강제
        # error 됐다. 자식 status_change 를 별도 블록으로 노출해 신호를 직접 준다.
        child_events = {
            ("g1", "project"): [],
            ("t1", "issue"): [
                _status_change("2026-04-30T00:00:00Z", "todo", "running"),  # since 이전 — 제외
                _status_change("2026-05-02T01:00:00Z", "running", "cleanup"),
                _status_change("2026-05-02T02:00:00Z", "cleanup", "done"),
            ],
            ("t2", "issue"): [
                _status_change("2026-05-02T03:00:00Z", "todo", "running"),
            ],
        }
        ctx = _ctx(FakeClient(child_events))
        out = work_finder.format_goal_delta_section(
            project=_GOAL, issues=_TASKS,
            since="2026-05-01T00:00:00Z", ctx=ctx
        )
        self.assertIn("자식 status_change (since)", out)
        # since 이후 transition 만 (3 issue) 노출
        self.assertIn("cleanup", out)
        self.assertIn("done", out)
        # child_id 와 child_title 로 어느 자식 건지 식별 가능
        self.assertIn("t1", out)
        self.assertIn("빌드", out)
        # since 이전 transition (t1 의 todo→running) 은 제외
        self.assertNotIn("\"from\": \"todo\",\n      \"to\": \"running\",\n      \"child_id\": \"t1\"", out)

    def test_no_child_status_change_block_when_none_since(self):
        # since 이전 transition 만 있으면 블록 자체가 안 만들어진다 (소음 차단).
        child_events = {
            ("g1", "project"): [],
            ("t1", "issue"): [_status_change("2026-04-01T00:00:00Z", "todo", "running")],
            ("t2", "issue"): [],
        }
        ctx = _ctx(FakeClient(child_events))
        out = work_finder.format_goal_delta_section(
            project=_GOAL, issues=_TASKS,
            since="2026-05-01T00:00:00Z", ctx=ctx
        )
        self.assertNotIn("자식 status_change", out)


if __name__ == "__main__":
    unittest.main()
