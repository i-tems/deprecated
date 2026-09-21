"""SESSION_TIMEOUT watchdog 회귀 테스트.

근본 결함(NESS-ISSUE-3): persistent worker 가 단일 SDK 서브프로세스를 entity
수명 내내 들고 있어, waiting(HOTL) 으로 SESSION_TIMEOUT 보다 오래 idle 한 뒤
wake 되면 묵은 세션 resume query 가 error_during_execution 으로 깨졌다.

수정: 마지막 query 이후 idle 이 SESSION_TIMEOUT 이상이면 다음 query 직전에
세션을 teardown 후 영속 session_id 로 resume 재생성한다. back-to-back 활성
cycle(gap < SESSION_TIMEOUT)은 같은 세션을 재사용한다.

검증:
  - idle ≥ SESSION_TIMEOUT → 세션 재생성(__aexit__ 후 새 __aenter__ resume=sid)
  - idle <  SESSION_TIMEOUT → 같은 세션 재사용(재생성 없음)
  - 어떤 경로로 빠져나가도 finally 가 세션을 닫는다
"""

import asyncio
import sys
import types as _types
import unittest
from types import SimpleNamespace

# claude_agent_sdk 는 worker 이미지에만 설치된다. 테스트 환경(SDK 없음)에서
# app.worker import 가 깨지지 않도록 최소 stub 주입 — 본 테스트는 SDK 경로를
# fake make_agent_session/run_agent 로 우회하므로 심볼 존재만 필요하다.
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
from app.config import SESSION_TIMEOUT
from app.models import Action


class FakeClock:
    """worker 모듈의 time 을 대체. 테스트가 monotonic 을 명시적으로 전진시킨다."""

    def __init__(self):
        self._mono = 1000.0

    def monotonic(self):
        return self._mono

    def time(self):
        return 1_700_000_000.0 + self._mono

    def sleep(self, _s):
        # 실제로 자지 않는다. POLL_INTERVAL sleep 을 짧은 시간 경과로 본다.
        self._mono += 0.01

    def advance(self, secs: float):
        self._mono += secs


class FakeSDKClient:
    """ClaudeSDKClient 의 async context 계약만 흉내. aenter/aexit 횟수 기록."""

    log: list = []

    def __init__(self, resume):
        self.resume = resume

    async def __aenter__(self):
        FakeSDKClient.log.append(("aenter", self.resume))
        return self

    async def __aexit__(self, *exc):
        FakeSDKClient.log.append(("aexit", self.resume))
        return False


class FakeHeartbeat:
    def __init__(self):
        self.auth_fatal = False

    def has_auth_fatal(self):
        return self.auth_fatal

    def set_phase(self, *_a, **_k):
        pass

    def set_session_id(self, *_a, **_k):
        pass


class FakeHubClient:
    """_refresh_action 이 쓰는 .api 와 get_tasks 만 구현."""

    def __init__(self, entity_seq):
        # entity_seq: cycle 마다 반환할 entity dict 리스트 (마지막은 terminal).
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


def _issue(status):
    return {"issue_id": "T-1", "title": "t", "status": status, "owner": "u"}


def _run(entity_statuses, *, idle_before_first_work):
    """entity_statuses: cycle 별 status. 'todo' 면 work 발급, 그 외 refresh 값.

    idle_before_first_work: 첫 work cycle 직전에 흘려보낼 idle 초.
    반환: (FakeSDKClient.log, recycle_count).
    """
    FakeSDKClient.log = []
    clock = FakeClock()
    worker.time = clock  # 모듈 time 대체

    seq = [_issue(s) for s in entity_statuses]
    hub = FakeHubClient(seq)
    action0 = Action(type="progress", entity=_issue("todo"), priority=0)

    sess = SimpleNamespace(session_id="sid-1", last_prompt_at="2026-01-01T00:00:00Z")
    wi = SimpleNamespace(
        context={"session_type": "issue_progress", "entity_type": "issue", "issue": _issue("todo")},
        session=sess, prompt="p", model="sonnet",
    )

    state = {"work_calls": 0}

    def fake_pre_dispatch(_ctx, _action):
        # 첫 호출 직전 idle 주입(stale 트리거 시뮬레이션).
        if state["work_calls"] == 0:
            clock.advance(idle_before_first_work)
        state["work_calls"] += 1
        if state["work_calls"] > 1:
            # 두 번째부터는 terminal 로 만들어 루프 종료(refresh 가 error/done 반환).
            return None
        return wi

    async def fake_run_agent(**_kw):
        clock.advance(5)  # query 가 5초 걸렸다고 가정
        return {"is_error": False, "result": "ok"}

    recycle = {"n": 0}
    orig_open_marker = []

    def fake_make_agent_session(**kw):
        recycle["n"] += 1
        orig_open_marker.append(kw.get("resume_session_id"))
        return FakeSDKClient(kw.get("resume_session_id"))

    worker.make_agent_session = fake_make_agent_session
    worker.run_agent = fake_run_agent
    worker.pre_dispatch = fake_pre_dispatch
    worker.post_dispatch = lambda *_a, **_k: None
    worker._persist_session = lambda *_a, **_k: None
    worker._wait_for_wake = lambda **_k: None

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
    return FakeSDKClient.log, recycle["n"]


class SessionWatchdogTests(unittest.TestCase):
    def tearDown(self):
        # 모듈 전역을 원복(다른 테스트 오염 방지).
        import importlib
        importlib.reload(worker)

    def test_long_idle_recycles_session_via_resume(self):
        # 첫 work 직전 idle = SESSION_TIMEOUT + 60 → stale → 재생성.
        log, recycle = _run(["todo", "done"], idle_before_first_work=SESSION_TIMEOUT + 60)
        # 최초 open 1 + stale 재생성 1 = make_agent_session 2회.
        self.assertEqual(recycle, 2, f"세션이 재생성되지 않음 log={log}")
        # 재생성은 teardown(aexit) 후 resume sid 로 새 aenter.
        kinds = [k for k, _ in log]
        self.assertIn("aexit", kinds)
        # 재생성 aenter 는 영속 session_id('sid-1') 로 resume.
        reopen = [r for k, r in log if k == "aenter"]
        self.assertEqual(reopen[-1], "sid-1", f"resume sid 누락 log={log}")
        # 마지막은 finally teardown.
        self.assertEqual(log[-1][0], "aexit")

    def test_short_idle_reuses_session(self):
        # 첫 work 직전 idle = SESSION_TIMEOUT - 60 → 재사용(재생성 없음).
        log, recycle = _run(["todo", "done"], idle_before_first_work=SESSION_TIMEOUT - 60)
        self.assertEqual(recycle, 1, f"불필요한 세션 재생성 발생 log={log}")
        # open 1회 + finally aexit 1회.
        self.assertEqual([k for k, _ in log], ["aenter", "aexit"])


if __name__ == "__main__":
    unittest.main()
