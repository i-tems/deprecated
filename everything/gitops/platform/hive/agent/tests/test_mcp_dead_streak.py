"""MCP transport-dead streak 의 cross-turn 영속 회귀.

근거(INFRA-ISSUE-322 ③): run_agent 의 mcp_dead_streak 가 turn-local 이라 매 turn
0 으로 리셋됐다. turn 당 mcp 호출이 1회면 streak 이 임계(_MCP_TRANSPORT_DEAD_STREAK=2)에
영영 못 닿아, MCP 세션이 죽은 zombie 워커가 fresh-pod 복구 없이 영구히 돈다. 이제 streak 을
run_agent 인자로 받아 반환 dict 로 다음 turn 에 운반(worker 가 운반)한다.
"""

import logging
import sys
import types as _types
import unittest

# claude_agent_sdk 미설치(CI·로컬) — kwargs 보존형 스텁. 단 collection 순서와 무관하게
# (다른 테스트가 먼저 설치한 불완전 스텁 뒤여도) app.runtime 가 쓰는 심볼이 모두 있도록
# 있는 모듈을 augment 한다 — `not in sys.modules` 가드만 쓰면 앞 테스트의 부분 스텁에
# ClaudeAgentOptions 등이 빠져 import 가 깨진다.

class _Msg:
    def __init__(self, **kw):
        self.__dict__.update(kw)

_sdk = sys.modules.get("claude_agent_sdk")
if _sdk is None:
    _sdk = _types.ModuleType("claude_agent_sdk")
    sys.modules["claude_agent_sdk"] = _sdk
for _n in ("AssistantMessage", "ClaudeAgentOptions", "ClaudeSDKClient",
           "ResultMessage", "SystemMessage", "TextBlock", "ToolUseBlock",
           "UserMessage"):
    if not hasattr(_sdk, _n):
        setattr(_sdk, _n, type(_n, (_Msg,), {}))
_t = sys.modules.get("claude_agent_sdk.types")
if _t is None:
    _t = _types.ModuleType("claude_agent_sdk.types")
    sys.modules["claude_agent_sdk.types"] = _t
    _sdk.types = _t
if not hasattr(_t, "ToolResultBlock"):
    _t.ToolResultBlock = type("ToolResultBlock", (_Msg,), {})

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage, ResultMessage, SystemMessage, ToolUseBlock, UserMessage,
)
from claude_agent_sdk.types import ToolResultBlock  # noqa: E402

from app.models import EntitySession  # noqa: E402
from app.runtime import (  # noqa: E402
    _MCP_TRANSPORT_DEAD_STREAK, _mcp_dead_transition, run_agent,
)

_DEAD = "upstream said: Session not found"   # mcp_transport_dead 매칭 시그니처
_LOG = logging.getLogger("test_mcp_dead_streak")


def _dead_turn_stream():
    """mcp 호출 1회가 transport-dead 로 끝나는 한 turn 의 메시지 스트림."""
    return [
        SystemMessage(subtype="init", data={"session_id": "sid-1"}),
        AssistantMessage(content=[ToolUseBlock(id="t1", name="mcp__hive__issue_get", input={})]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", is_error=True, content=_DEAD)]),
        ResultMessage(subtype="success", is_error=False, result="done", session_id="sid-1"),
    ]


class _FakeAgentSession:
    """AgentSession 흉내 — receive_response 가 매 호출 stream_factory() 를 yield."""

    def __init__(self, stream_factory):
        self._stream_factory = stream_factory
        self.queried = []

    async def query(self, prompt):
        self.queried.append(prompt)

    async def receive_response(self):
        for m in self._stream_factory():
            yield m


class McpDeadTransitionTest(unittest.TestCase):
    def test_accumulates_and_trips_at_threshold(self):
        self.assertEqual(_MCP_TRANSPORT_DEAD_STREAK, 2)
        s, dead = _mcp_dead_transition(0, True, _DEAD)
        self.assertEqual((s, dead), (1, False))
        s, dead = _mcp_dead_transition(s, True, _DEAD)   # 직전 turn 누적분 + 1 → 임계
        self.assertEqual((s, dead), (2, True))

    def test_healthy_result_resets(self):
        self.assertEqual(_mcp_dead_transition(1, False, "ok"), (0, False))

    def test_non_transport_error_resets(self):
        # error 라도 transport-dead 시그니처가 아니면(도메인 에러) 리셋.
        self.assertEqual(_mcp_dead_transition(5, True, "schema_validation_failed"), (0, False))


class RunAgentStreakThreadingTest(unittest.IsolatedAsyncioTestCase):
    async def test_streak_persists_across_turns(self):
        sess = EntitySession(entity_id="INFRA-ISSUE-1")
        client = _FakeAgentSession(_dead_turn_stream)
        # turn 1: 1 dead → streak 1, 아직 dead 아님.
        r1 = await run_agent(client=client, logger=_LOG, session=sess, prompt="t1",
                             langfuse=None, mcp_dead_streak=0)
        self.assertEqual(r1["mcp_dead_streak"], 1)
        self.assertFalse(r1["mcp_transport_dead"])
        # turn 2: streak 1 운반 + 1 dead → 2 ≥ 임계 → transport_dead.
        r2 = await run_agent(client=client, logger=_LOG, session=sess, prompt="t2",
                             langfuse=None, mcp_dead_streak=r1["mcp_dead_streak"])
        self.assertEqual(r2["mcp_dead_streak"], 2)
        self.assertTrue(r2["mcp_transport_dead"])

    async def test_not_threading_never_detects(self):
        # 회귀 의미 고정: streak 을 운반하지 않으면(매 turn 0 주입 = 옛 turn-local 동작)
        # 1 dead/turn 은 임계에 영영 못 닿아 zombie 영구 미탐.
        sess = EntitySession(entity_id="x")
        client = _FakeAgentSession(_dead_turn_stream)
        for _ in range(5):
            r = await run_agent(client=client, logger=_LOG, session=sess, prompt="t",
                                langfuse=None, mcp_dead_streak=0)
            self.assertEqual(r["mcp_dead_streak"], 1)
            self.assertFalse(r["mcp_transport_dead"])


if __name__ == "__main__":
    unittest.main()
