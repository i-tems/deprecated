"""codex backend 이벤트→SDK Message 매핑 회귀 테스트.

codex `exec --json` 이벤트(thread.started / item.* / turn.completed·failed)가 worker
소비 루프(runtime._stream_turn)가 기대하는 claude_agent_sdk Message 타입으로 정확히
변환되는지 고정한다. subprocess·네트워크 없이 CodexAgentSession._translate 에 synthetic
이벤트를 주입 — 매핑이 이 backend 의 fragile 한 부분이라 여기를 잠근다 (라이브 end-to-end
는 별도 PoC 로 검증됨).
"""

import sys
import types as _types
import unittest

# CI 는 claude_agent_sdk 미설치 — 기존 테스트와 동일하게 스텁 (kwargs 보존형).
if "claude_agent_sdk" not in sys.modules:
    _sdk = _types.ModuleType("claude_agent_sdk")

    class _Msg:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    for _n in ("AssistantMessage", "ResultMessage", "SystemMessage",
               "TextBlock", "ToolUseBlock", "UserMessage"):
        setattr(_sdk, _n, type(_n, (_Msg,), {}))
    _t = _types.ModuleType("claude_agent_sdk.types")
    _t.ToolResultBlock = type("ToolResultBlock", (_Msg,), {})
    _sdk.types = _t
    sys.modules["claude_agent_sdk"] = _sdk
    sys.modules["claude_agent_sdk.types"] = _t

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock, UserMessage,
)
from claude_agent_sdk.types import ToolResultBlock  # noqa: E402

from app.codex_backend import (  # noqa: E402
    CodexAgentSession, _is_resume_failure,
)


def _sess(**kw):
    base = dict(model="gpt-5.5", cwd=None, hub_url="http://hub",
                caller_token="t", resume_session_id=None)
    base.update(kw)
    return CodexAgentSession(**base)


def _drain(sess, events):
    out, terminal = [], False
    for ev in events:
        msgs, is_term = sess._translate(ev)
        out += msgs
        if is_term:
            terminal = True
            break
    return out, terminal


class TranslateTest(unittest.TestCase):
    def test_thread_started_yields_systemmessage_and_captures_id(self):
        s = _sess()
        msgs, _ = _drain(s, [{"type": "thread.started", "thread_id": "T1"}])
        self.assertEqual(len(msgs), 1)
        self.assertIsInstance(msgs[0], SystemMessage)
        # worker 가 .data["session_id"] 로 읽어 resume 용으로 영속화.
        self.assertEqual(msgs[0].data["session_id"], "T1")
        self.assertEqual(s._thread_id, "T1")

    def test_mcp_tool_call_maps_to_tooluse_then_toolresult(self):
        s = _sess()
        started = {"type": "item.started", "item": {
            "type": "mcp_tool_call", "id": "i0", "server": "hive", "tool": "issue.get",
            "arguments": {"cell": "infra", "issue_id": "X"}}}
        completed = {"type": "item.completed", "item": {
            "type": "mcp_tool_call", "id": "i0", "server": "hive", "tool": "issue.get",
            "status": "completed", "result": {"content": [{"type": "text", "text": "{}"}]},
            "error": None}}
        msgs, _ = _drain(s, [started, completed])
        self.assertIsInstance(msgs[0], AssistantMessage)
        tu = msgs[0].content[0]
        self.assertIsInstance(tu, ToolUseBlock)
        # Claude 컨벤션 mcp__<server>__<tool> — worker 의 mcp-dead 감지·Langfuse 파싱 의존.
        self.assertEqual(tu.name, "mcp__hive__issue.get")
        self.assertEqual(tu.id, "i0")
        self.assertEqual(tu.input["cell"], "infra")
        self.assertIsInstance(msgs[1], UserMessage)
        tr = msgs[1].content[0]
        self.assertIsInstance(tr, ToolResultBlock)
        self.assertEqual(tr.tool_use_id, "i0")  # tool_use 와 매칭돼야 span 종료
        self.assertFalse(tr.is_error)

    def test_failed_tool_call_marks_error(self):
        s = _sess()
        ev = {"type": "item.completed", "item": {
            "type": "mcp_tool_call", "id": "i1", "server": "hive", "tool": "x",
            "status": "failed", "error": {"message": "boom"}}}
        msgs, _ = _drain(s, [ev])
        self.assertTrue(msgs[0].content[0].is_error)

    def test_agent_message_maps_to_textblock(self):
        s = _sess()
        msgs, _ = _drain(s, [{"type": "item.completed", "item": {
            "type": "agent_message", "id": "a0", "text": "hello"}}])
        self.assertIsInstance(msgs[0], AssistantMessage)
        self.assertIsInstance(msgs[0].content[0], TextBlock)
        self.assertEqual(msgs[0].content[0].text, "hello")
        self.assertEqual(s._last_text, "hello")

    def test_blank_agent_message_yields_nothing(self):
        s = _sess()
        msgs, _ = _drain(s, [{"type": "item.completed", "item": {
            "type": "agent_message", "id": "a", "text": "   "}}])
        self.assertEqual(msgs, [])

    def test_turn_completed_is_terminal_result_with_usage_mapping(self):
        s = _sess()
        s._thread_id = "T9"
        s._last_text = "final"
        usage = {"input_tokens": 100, "cached_input_tokens": 40,
                 "output_tokens": 7, "reasoning_output_tokens": 2}
        msgs, terminal = _drain(s, [{"type": "turn.completed", "usage": usage}])
        self.assertTrue(terminal)
        r = msgs[0]
        self.assertIsInstance(r, ResultMessage)
        self.assertEqual(r.subtype, "success")
        self.assertFalse(r.is_error)
        self.assertEqual(r.session_id, "T9")
        self.assertEqual(r.result, "final")
        self.assertEqual(r.total_cost_usd, 0.0)  # 구독 OAuth — 호출당 과금 0
        self.assertEqual(r.usage["input_tokens"], 100)
        self.assertEqual(r.usage["cache_read_input_tokens"], 40)  # cached_input_tokens 매핑
        self.assertEqual(r.usage["output_tokens"], 7)

    def test_turn_failed_is_terminal_error_result(self):
        s = _sess()
        msgs, terminal = _drain(s, [{"type": "turn.failed",
                                     "error": {"message": "model not supported"}}])
        self.assertTrue(terminal)
        self.assertTrue(msgs[0].is_error)
        self.assertEqual(msgs[0].subtype, "error")
        self.assertIn("model not supported", msgs[0].result)

    def test_unknown_and_skipped_events_ignored(self):
        s = _sess()
        msgs, term = _drain(s, [
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "reasoning"}},
        ])
        self.assertEqual(msgs, [])
        self.assertFalse(term)

    def test_build_argv_resume_options_before_subcommand(self):
        # 회귀(INFRA-ISSUE-256): `codex exec resume` 는 옵션을 resume *앞*에서만 받는다.
        # resume 뒤에 -C 등이 오면 'unexpected argument' (rc=2) → multi-turn 워커 전멸.
        s = _sess(resume_session_id="T-OLD", cwd="/work")
        argv = s._build_argv("do it")
        ri = argv.index("resume")
        self.assertLess(argv.index("-C"), ri)       # -C 가 resume 앞
        self.assertLess(argv.index("--json"), ri)   # --json 도 앞
        self.assertLess(argv.index("-m"), ri)
        self.assertEqual(argv[ri + 1], "T-OLD")     # thread_id 가 resume 바로 뒤
        self.assertEqual(argv[-1], "do it")         # prompt 마지막

    def test_build_argv_first_turn_has_no_resume(self):
        s = _sess(cwd="/work")
        argv = s._build_argv("hi")
        self.assertNotIn("resume", argv)
        self.assertEqual(argv[-1], "hi")
        self.assertIn("-C", argv)

    def test_is_resume_failure(self):
        # cutover 시 타 backend(Claude) session_id → codex resume 실패 시그니처.
        self.assertTrue(_is_resume_failure(
            "Error: thread/resume: thread/resume failed: no rollout found for thread id 2f31..."))
        self.assertTrue(_is_resume_failure("RESUME FAILED for thread"))
        self.assertFalse(_is_resume_failure("token_invalidated"))
        self.assertFalse(_is_resume_failure(""))

    def test_fresh_retry_drops_thread_id(self):
        # resume 실패 후 fresh 재시도 경로: thread_id 가 비면 _build_argv 에 resume 없음.
        s = _sess(resume_session_id="CLAUDE-SID", cwd="/work")
        self.assertIn("resume", s._build_argv("x"))
        s._thread_id = None  # fallback 이 비우는 동작
        self.assertNotIn("resume", s._build_argv("x"))



if __name__ == "__main__":
    unittest.main()
