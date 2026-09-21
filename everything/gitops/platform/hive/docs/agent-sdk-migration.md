# Agent SDK Migration — 영구 Claude 세션 도입

> 작성 2026-05-12. 다음 세션이 현재 코드를 다시 보고 판단해 진행.

## 왜

PR #44 가 worker pod 수명을 영구화했지만, claude 프로세스는 여전히 매 cycle `claude -p --resume <sid>` 로 새로 spawn 된다. 이 단위에서 파생하는 문제:

1. **관측 단절** — Langfuse 가 대화 도중 차오르지 않고 ([claude-code#25670](https://github.com/anthropics/claude-code/issues/25670): stream-json 이 PIPE 에서 block-buffered, Anthropic 미해결), cycle 마다 새 generation 이라 한 issue 의 trace 가 여러 개로 분리.
2. **컨텍스트 중복** — `--resume` 이 이전 대화를 갖고 있는데도 prompt header / entity slim JSON / spec refs 가 cycle 마다 새 user turn 으로 다시 들어간다. 토큰 낭비 + LLM 혼란.
3. **spawn 오버헤드** — claude binary 부팅 + MCP 핸드셰이크가 cycle 마다 반복.

셋 다 "1 client = N turn" 으로 가면 같이 풀린다.

## 목표

**1 entity active = 1 long-running claude session.** cycle 마다 user message 만 추가, subprocess spawn 은 worker 시작 시 한 번.

## 결정: Claude Agent SDK (Python)

- ❌ CLI `--input-format stream-json` — 단일 메시지 처리 후 종료. issue #24594 "Closed as not planned".
- ✅ **`claude-agent-sdk`** — `ClaudeSDKClient` 가 정확히 "1 client = N turn" 패턴.

## SDK 핵심 사실 (2026-05 기준)

- 패키지: `pip install claude-agent-sdk` · 최신 v0.1.81 · **Alpha** (마이너마다 API 변경 → 핀 필수).
- async-only.
- 패턴:
  ```python
  async with ClaudeSDKClient(options=...) as client:
      await client.query("turn 1")
      async for msg in client.receive_response(): ...   # AssistantMessage / SystemMessage / ResultMessage / StreamEvent
      await client.query("turn 2")                       # 같은 세션, 같은 MCP 연결
  ```
- **MCP streamable_http 지원**: `mcp_servers={"name": {"type": "http", "url": ..., "headers": ...}}`. 우리 hub 가 streamable_http 라 호환 — 단 Accept 헤더 케이스 [typescript#202](https://github.com/anthropics/claude-agent-sdk-typescript/issues/202) PoC 에서 실연결 확인 필요.
- session_id 는 `SystemMessage(subtype="init")` 에서 노출. `ResultMessage` 에 cost/usage/num_turns.
- CLI 옵션 매핑: `--model`/`--max-turns`/`--resume` 동명 필드, `--dangerously-skip-permissions` → `permission_mode="bypassPermissions"`, `--mcp-config <file>` → `mcp_servers=path`.
- cross-process resume 은 로컬 jsonl 파일 의존. 외부 transcript inject 는 [#848](https://github.com/anthropics/claude-agent-sdk-python/issues/848) 미지원.

## 함정

- Alpha — 버전 핀 + 업그레이드 시 회귀 테스트.
- async-only — 현재 sync worker 흐름 (heartbeat thread, signal handler) 과의 통합 설계 필요.
- pod crash 시 in-process conversation 손실 — fresh start 허용 여부 확인 (작업 컨텍스트는 entity 에 있어 이어갈 수 있음).

## 참고

- [PyPI](https://pypi.org/project/claude-agent-sdk/) · [GitHub](https://github.com/anthropics/claude-agent-sdk-python) · [Agent SDK Python docs](https://code.claude.com/docs/en/agent-sdk/python) · [MCP](https://code.claude.com/docs/en/agent-sdk/mcp) · [Sessions](https://code.claude.com/docs/en/agent-sdk/sessions)
