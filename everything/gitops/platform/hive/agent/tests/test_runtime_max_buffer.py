"""make_client_options 가 SDK 의 1MB 기본 stdout 버퍼 한도를 올리는지 회귀.

근거(ITEMS-ISSUE-95): 워커가 PDF 를 Read 하면 base64 document 블록 한 메시지가
1.9MB→2.56MB 로 SDK 의 _DEFAULT_MAX_BUFFER_SIZE(1MB)를 넘겨 CLIJSONDecodeError 로
turn 전체가 force_error 됐다. make_client_options 가 ClaudeAgentOptions.max_buffer_size
를 명시(기본 8MB, HIVE_SDK_MAX_BUFFER_BYTES override)해 그 절벽을 없앤다.
"""

import os
import sys
import types as _types
import unittest
from unittest import mock


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

from app.runtime import (  # noqa: E402
    _DEFAULT_SDK_MAX_BUFFER_BYTES, _sdk_max_buffer_size, make_client_options,
)


def _opts():
    return make_client_options(
        model=None, max_turns=8, mcp_config_path=None, cwd="/x",
        resume_session_id=None,
    )


class SdkMaxBufferTest(unittest.TestCase):
    def test_default_is_8mb_and_above_sdk_floor(self):
        self.assertEqual(_DEFAULT_SDK_MAX_BUFFER_BYTES, 8 * 1024 * 1024)
        # SDK 기본 1MB 절벽을 확실히 넘어선다 (실패한 2.56MB 메시지도 여유).
        self.assertGreater(_DEFAULT_SDK_MAX_BUFFER_BYTES, 1024 * 1024)

    def test_make_client_options_sets_max_buffer_size(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HIVE_SDK_MAX_BUFFER_BYTES", None)
            opts = _opts()
        self.assertEqual(opts.max_buffer_size, _DEFAULT_SDK_MAX_BUFFER_BYTES)

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"HIVE_SDK_MAX_BUFFER_BYTES": "33554432"}):
            self.assertEqual(_sdk_max_buffer_size(), 33554432)
            self.assertEqual(_opts().max_buffer_size, 33554432)

    def test_invalid_or_nonpositive_env_falls_back(self):
        for bad in ("not-an-int", "0", "-5", ""):
            with mock.patch.dict(os.environ, {"HIVE_SDK_MAX_BUFFER_BYTES": bad}):
                self.assertEqual(_sdk_max_buffer_size(), _DEFAULT_SDK_MAX_BUFFER_BYTES)


if __name__ == "__main__":
    unittest.main()
