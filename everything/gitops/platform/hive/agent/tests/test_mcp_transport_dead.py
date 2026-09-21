"""hub 롤아웃으로 MCP 세션이 무효화됐을 때의 transport-dead 시그니처 판정.

근거 사고(2026-05-17 NESS-ISSUE-4): hub 신규 ReplicaSet 롤아웃 후 worker 의
영구 MCP 클라이언트가 모든 mcp__* 호출에 대해 아래 형태로 영구 실패.
worker 는 이 시그니처를 보고 non-zero exit → K8s Job 이 fresh pod 재기동.

추가(2026-05-23 INFRA-ISSUE-83): hub Recreate 롤아웃 중 새 pod 가 아직 미준비일 때
Claude Code MCP 클라이언트가 "MCP server X is not connected" 시그니처로 실패.
기존 "Session not found" 경로와 별개 — 새 마커로 동일 복구 흐름.
"""

import unittest

from app.models import mcp_transport_dead

# 실측 ToolResultBlock.content (claude SDK 가 str 로 주는 케이스).
_REAL = (
    'Streamable HTTP error: Error POSTing to endpoint: '
    '{"jsonrpc":"2.0","id":"server-error",'
    '"error":{"code":-32600,"message":"Session not found"}}'
)


class McpTransportDeadTest(unittest.TestCase):
    def test_real_signature_str(self):
        self.assertTrue(mcp_transport_dead(_REAL))

    def test_real_signature_block_list(self):
        # SDK 가 [{"type":"text","text": ...}] 형태로 줄 때도 평탄화돼 잡힌다.
        self.assertTrue(mcp_transport_dead([{"type": "text", "text": _REAL}]))

    def test_partial_marker_only(self):
        self.assertTrue(mcp_transport_dead("upstream said: Session not found"))
        self.assertTrue(mcp_transport_dead("JSON-RPC error code -32600"))

    def test_none_and_empty(self):
        self.assertFalse(mcp_transport_dead(None))
        self.assertFalse(mcp_transport_dead(""))
        self.assertFalse(mcp_transport_dead([]))

    def test_normal_error_not_transport_dead(self):
        # 정상 도메인 에러(스키마 검증 실패 등)는 transport-dead 가 아니다 —
        # 오판하면 멀쩡한 worker 를 재기동시킨다.
        self.assertFalse(mcp_transport_dead(
            '{"status":"error","error_code":"schema_validation_failed",'
            '"message":"detail: \'raw\' is a required property"}'
        ))
        self.assertFalse(mcp_transport_dead([{"type": "text", "text": "ok"}]))

    def test_non_string_content_coerced(self):
        self.assertFalse(mcp_transport_dead({"unexpected": "shape"}))

    def test_is_not_connected_str(self):
        # 실측(2026-05-23 INFRA-ISSUE-83): hub Recreate 롤아웃 중 Claude Code MCP 클라이언트
        # 가 서버 미준비 상태에서 내보내는 시그니처.
        self.assertTrue(mcp_transport_dead('MCP server "hive-beauty" is not connected'))
        self.assertTrue(mcp_transport_dead('MCP server "hive-infra" is not connected'))

    def test_is_not_connected_block_list(self):
        content = [{"type": "text", "text": 'MCP server "hive-beauty" is not connected'}]
        self.assertTrue(mcp_transport_dead(content))


if __name__ == "__main__":
    unittest.main()
