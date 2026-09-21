"""hold 게이트 회귀 테스트 (INFRA-ISSUE-187).

근본 결함: hold 은 agent-loop 의 find_all_work(spawn 게이트)에서만 검사돼,
hold 이전부터 살아있던 persistent worker 는 hold 을 무시하고 held entity 에
계속 claude turn 을 돌렸다 (새 comment → _wait_for_wake 가 깨움 → reply).

수정: _run_cycles 의 cycle 경계에 hold 게이트를 둬, held(=hold:true) 면 claude
실행을 건너뛰고 idle 로 대기한다. terminal(done/cancelled) + pending reply 경로도
held 면 진입하지 않는다.

검증:
  - held + active status → claude 미실행, idle 대기(_wait_for_wake 호출)
  - held + done + pending user comment → reply 진입 안 함(종료)
  - unheld + active status → claude 정상 실행 (게이트가 정상 흐름을 막지 않음)
"""

import asyncio
import sys
import types as _types
import unittest
from types import SimpleNamespace

# claude_agent_sdk 는 worker 이미지에만 설치된다 — 테스트 환경 stub (watchdog 테스트와 동일).
if "claude_agent_sdk" not in sys.modules:
    _sdk = _types.ModuleType("claude_agent_sdk")
    for _n in ("AssistantMessage", "ClaudeAgentOptions", "ClaudeSDKClient",
               "ResultMessage", "SystemMessage", "TextBlock", "ToolUseBlock",
               "UserMessage"):
        setattr(_sdk, _n, type(_n, (), {}))
    _sdk_types = _types.ModuleType("claude_agent_sdk.types")
    _sdk_types.ToolResultBlock = type("ToolResultBlock", (), {})
    _sdk.types = _sdk_types
    sys.modules["claude_agent_sdk"] = _sdk
    sys.modules["claude_agent_sdk.types"] = _sdk_types

from app import worker
from app.models import Action


class FakeSDKClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeHeartbeat:
    def has_auth_fatal(self):
        return False

    def set_phase(self, *_a, **_k):
        pass

    def set_session_id(self, *_a, **_k):
        pass


class FakeHubClient:
    """_refresh_action 의 `.get` 에 cycle 별 entity 를 순서대로 돌려준다."""

    def __init__(self, entity_seq):
        self._seq = entity_seq
        self._i = 0

    def api(self, name, params):
        if name.endswith(".get"):
            ent = self._seq[min(self._i, len(self._seq) - 1)]
            self._i += 1
            return {"data": ent}
        return {"data": {}}

    def get_tasks(self, _gid):
        return []


def _issue(status, *, hold=False, pending=None):
    e = {"issue_id": "T-1", "title": "t", "status": status, "owner": "u", "hold": hold}
    if pending is not None:
        e["pending_user_comment_event_ids"] = pending
    return e


def _run(entity_seq):
    """entity_seq 를 cycle 별 refresh 결과로 흘려보내고 (run_agent 호출수, wake 호출수) 반환."""
    counters = {"run_agent": 0, "wait_for_wake": 0}

    clock = SimpleNamespace(_t=1000.0)
    fake_time = SimpleNamespace(
        monotonic=lambda: clock._t,
        time=lambda: 1_700_000_000.0,
        sleep=lambda _s: None,
    )
    worker.time = fake_time

    hub = FakeHubClient(entity_seq)
    action0 = Action(type="progress", entity=_issue("todo"), priority=0)

    sess = SimpleNamespace(session_id="sid-1", last_prompt_at="2026-01-01T00:00:00Z")
    wi = SimpleNamespace(
        context={"session_type": "issue_progress", "entity_type": "issue", "issue": _issue("running")},
        session=sess, prompt="p", model="sonnet",
    )

    async def fake_run_agent(**_kw):
        counters["run_agent"] += 1
        return {"is_error": False, "result": "ok"}

    def fake_wait_for_wake(**_kw):
        counters["wait_for_wake"] += 1

    worker.make_agent_session = lambda **_k: FakeSDKClient()
    worker.run_agent = fake_run_agent
    worker.pre_dispatch = lambda _ctx, _a: wi
    worker.post_dispatch = lambda *_a, **_k: None
    worker._persist_session = lambda *_a, **_k: None
    worker._wait_for_wake = fake_wait_for_wake

    ctx = SimpleNamespace(
        prompt_factory=SimpleNamespace(build_runtime_append=lambda _t: "rt"),
        resolve_model=lambda _t: "sonnet",
        session_store=SimpleNamespace(get_or_create=lambda _e: SimpleNamespace(session_id="sid-1")),
        exec_tier_default="medium",
        client=hub, log=worker.log,
    )

    asyncio.run(worker._run_cycles(
        ctx=ctx, action=action0, log=worker.log, hub_client=hub,
        heartbeat=FakeHeartbeat(), langfuse=None, cell_id="ness",
        mcp_config_path=None, bootstrap=("issue", "T-1"),
        entity_type_for_branch="issue", entity_id_for_branch="T-1",
    ))
    return counters


class HoldGateTests(unittest.TestCase):
    def tearDown(self):
        import importlib
        importlib.reload(worker)

    def test_held_active_skips_claude_and_idles(self):
        # cycle1: held running → 게이트가 claude skip + idle. cycle2: done → break.
        c = _run([_issue("running", hold=True), _issue("done")])
        self.assertEqual(c["run_agent"], 0, "held entity 에서 claude 가 실행됨 (게이트 누설)")
        self.assertGreaterEqual(c["wait_for_wake"], 1, "held entity 가 idle 대기로 들어가지 않음")

    def test_held_terminal_does_not_reply(self):
        # held + done + pending → reply 진입 금지(즉시 break). claude 미실행.
        c = _run([_issue("done", hold=True, pending=["EV-1"])])
        self.assertEqual(c["run_agent"], 0, "held terminal entity 에서 reply(claude) 가 실행됨")

    def test_unheld_active_runs_claude(self):
        # 게이트가 정상 흐름을 막지 않는지 — 대조군. cycle1 running 처리 후 stuck-check
        # 가 waiting 을 보고 idle, cycle2 done → break.
        c = _run([_issue("running"), _issue("waiting"), _issue("done")])
        self.assertEqual(c["run_agent"], 1, "unheld active entity 에서 claude 가 실행되지 않음")


if __name__ == "__main__":
    unittest.main()
