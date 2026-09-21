"""Claude Agent SDK 기반 한 turn 실행 + Langfuse 기록.

기존 stream-json subprocess 모델을 대체. ClaudeSDKClient 는 worker 의 entity
cycle 루프 밖에서 1회 생성되어 같은 claude session 을 유지하며, runtime 은 매
cycle prompt 1개를 `query` → `receive_response` 로 한 turn 을 소비해 기존
run_agent 와 동일한 dict shape 으로 반환한다.

dict shape (외부 인터페이스 동등성 — log_usage, _persist_session, _LangfuseStream
등이 의존):
  - is_error: bool
  - result: str (최종 출력 또는 에러 메시지)
  - session_id: str | None
  - num_turns: int
  - total_cost_usd: float
  - duration_ms: int
  - duration_api_ms: int
  - usage: {input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens}
  - modelUsage: dict
  - subtype: str | None (SDK ResultMessage.subtype 그대로)

Langfuse: turn 진행 중 AssistantMessage 가 도착할 때마다 generation 의 output
필드를 누적 update + flush. 결과적으로 대화 도중 trace 가 실시간으로 차오른다
(기존 stream-json 의 PIPE buffering 우회).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Protocol, runtime_checkable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import ToolResultBlock

from .config import EXEC_TIER_DEFAULT, resolve_model
from .models import EntitySession, mcp_transport_dead

# 한 turn 안에서 mcp__* 툴 결과가 transport-dead 시그니처로 연속 N회 실패하면
# MCP 세션이 영구 무효로 판정. 1회는 일시 blip 여지를 두되(streak reset),
# 연속 2회면 영구 무효 확정 — 오판 비용은 worker 1회 재기동(idempotent,
# --resume 로 같은 대화 유지)뿐이라 민감하게 잡는다.
_MCP_TRANSPORT_DEAD_STREAK = 2


# SDK subprocess transport 는 CLI stdout 의 한 JSON 메시지(= 한 줄)를 버퍼에 모아
# 파싱하고, 기본 한도 1MB(claude_agent_sdk _DEFAULT_MAX_BUFFER_SIZE)를 넘으면
# CLIJSONDecodeError 로 stream 을 죽인다 → run_agent 가 api_error 로 잡아 turn 전체가
# force_error(running→error). 워커가 PDF·이미지를 Read 하면 base64 document/image
# 블록 한 메시지가 파일바이트×1.33 으로 쉽게 1MB 를 넘어(예: 1.9MB PDF → 2.56MB 단일
# 메시지) 멀쩡한 turn 이 죽었다 (ITEMS-ISSUE-95). 일반 메시지는 KB 단위라 한도를 올려도
# 메모리 비용은 그 outlier 한 줄뿐. 단 무한정 키우지 않는다 — 수십 MB 인라인은 여전히
# 막아 context/비용 폭주를 가드(텍스트 추출로 유도). 기본 8MB, HIVE_SDK_MAX_BUFFER_BYTES
# 로 override.
_DEFAULT_SDK_MAX_BUFFER_BYTES = 8 * 1024 * 1024


def _sdk_max_buffer_size() -> int:
    raw = os.environ.get("HIVE_SDK_MAX_BUFFER_BYTES")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return _DEFAULT_SDK_MAX_BUFFER_BYTES


@runtime_checkable
class AgentSession(Protocol):
    """Agent backend 의 공통 surface.

    worker.py 가 backend 별 구체 타입에 의존하지 않고 같은 코드로 cycle 을 돌리도록
    한 얕은 추상화. 현 구현체는 ClaudeSDKClient (claude-agent-sdk) 1개. anthropic 의
    가격·정책이 종종 바뀌어 (2026-06-15 Agent SDK 크레딧 분리 등) 다른 호출 경로
    (직접 anthropic-python API, claude -p subprocess 등) 로 갈아끼울 가능성이 있어
    factory 만 미리 둔다 — 두 번째 backend 가 실제로 들어올 때 본격 abstraction 정제.

    Message 타입은 SDK 의 AssistantMessage/SystemMessage/ResultMessage 그대로 사용
    (의도된 leakage — 진짜 다른 backend 가 들어오면 그 시점에 자체 Event 타입 도입).
    """

    async def query(self, prompt: str) -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...
    async def __aenter__(self) -> "AgentSession": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...


def make_client_options(
    *,
    model: str | None,
    max_turns: int,
    mcp_config_path: str | None,
    cwd: str | None,
    resume_session_id: str | None,
    deadline_epoch: int | None = None,
    timeout_sec: int | None = None,
    system_prompt: str | None = None,
) -> ClaudeAgentOptions:
    """ClaudeSDKClient (SDK backend) 전용 options 빌더.

    mcp_config_path: 기존 _setup_mcp_config 가 만든 JSON 파일 경로. SDK 가 `.mcp.json`
    포맷을 그대로 파싱하므로 path 만 넘겨도 충분.
    resume_session_id: hub 에 영속화된 sid. None 이면 fresh client.
    system_prompt: entity 수명 동안 불변. prompt caching 의 cache prefix 로 사용.
    HIVE_SESSION_DEADLINE_UTC / HIVE_SESSION_TIMEOUT_SEC 는 agent 가 잔여 시간 인지
    하고 self-yield 하는 데 사용 (기존 동작 유지).
    """
    extra_env: dict[str, str] = {}
    if deadline_epoch is not None:
        extra_env["HIVE_SESSION_DEADLINE_UTC"] = str(int(deadline_epoch))
    if timeout_sec is not None:
        extra_env["HIVE_SESSION_TIMEOUT_SEC"] = str(int(timeout_sec))

    # claude_code preset 을 쓰면 CLI 가 user(~/.claude/CLAUDE.md = hive 동기화
    # 계약) + project(<cwd>/.claude/ = cell) settings 를 자동 로드한다. str 로
    # 넘기면 --system-prompt override 라 그 자동 로드가 꺼진다 (기존 fragility 의
    # 원인). system_prompt 인자는 이제 런타임 사실 append 전용 (hub URL 등).
    sp: dict = {"type": "preset", "preset": "claude_code"}
    if system_prompt:
        sp["append"] = system_prompt

    return ClaudeAgentOptions(
        model=model or resolve_model(EXEC_TIER_DEFAULT),
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        mcp_servers=mcp_config_path,
        cwd=cwd,
        resume=resume_session_id,
        env=extra_env or None,
        system_prompt=sp,
        # user = ~/.claude/ (HOME=/data/shared, hive sync): CLAUDE.md 자동 로드
        # (ruler 가 rules 를 CLAUDE.md 로 concatenate — 별도 rules/*.md 없음, startup._sync_tree 가 prune).
        # project = <cwd>/.claude/ (cell).
        setting_sources=["user", "project"],
        # skills/processing-issues·processing-projects 등을 native 자동탐색 → 모델이 Skill 툴로 직접 호출.
        skills="all",
        # token-level StreamEvent 활성 — Langfuse 가 cycle 진행을 더 잘게 push 한다.
        # 명시 flush 빈도는 그대로 (5s) 라 Langfuse 부하는 거의 안 늘고, SDK 의 background
        # batch flush 가 자연 push.
        include_partial_messages=True,
        # CLI stdout 한 메시지의 버퍼 한도(SDK 기본 1MB). PDF/이미지 base64 블록이
        # 1MB 를 넘겨 turn 을 죽이던 것을 방지 — _sdk_max_buffer_size() 참조.
        max_buffer_size=_sdk_max_buffer_size(),
    )


def make_agent_session(
    *,
    model: str | None,
    max_turns: int,
    mcp_config_path: str | None,
    cwd: str | None,
    resume_session_id: str | None,
    deadline_epoch: int | None = None,
    timeout_sec: int | None = None,
    system_prompt: str | None = None,
) -> AgentSession:
    """`AGENT_BACKEND` env 로 호출 경로 선택. 기본값 "sdk".

    지원: "sdk" (ClaudeSDKClient) · "codex" (CodexAgentSession, ChatGPT 구독 OAuth).
    worker.py 는 backend 종류에 관계없이 같은 `async with` + `query` +
    `receive_response` 흐름 — 두 backend 모두 AgentSession Protocol 을 만족한다.
    """
    backend = os.environ.get("AGENT_BACKEND", "sdk").strip().lower()
    if backend == "sdk":
        return ClaudeSDKClient(options=make_client_options(
            model=model, max_turns=max_turns, mcp_config_path=mcp_config_path,
            cwd=cwd, resume_session_id=resume_session_id,
            deadline_epoch=deadline_epoch, timeout_sec=timeout_sec,
            system_prompt=system_prompt,
        ))
    if backend == "codex":
        # mcp_config_path(.mcp.json, Claude 포맷)는 codex 가 안 쓴다 — codex 는 hub
        # /mcp/ 를 자체 `-c` 오버라이드로 붙는다 (worker 와 같은 HUB_CALLER_TOKEN).
        from .codex_backend import CodexAgentSession
        # worker 의 model 인자는 claude 등급명(sonnet/opus 등)이라 codex 가 거부한다.
        # codex 모델은 별도 — CODEX_MODEL env(기본 gpt-5.5, ChatGPT 구독 계정 허용 모델).
        return CodexAgentSession(
            model=os.environ.get("CODEX_MODEL") or None, cwd=cwd, resume_session_id=resume_session_id,
            hub_url=os.environ.get("HUB_URL"),
            caller_token=os.environ.get("HUB_CALLER_TOKEN"),
            deadline_epoch=deadline_epoch, timeout_sec=timeout_sec,
            system_prompt=system_prompt,
        )
    raise NotImplementedError(
        f"AGENT_BACKEND={backend!r} 미구현. 지원되는 값: 'sdk', 'codex'"
    )


class _LangfuseStream:
    """한 turn 의 SDK Message 흐름을 Langfuse generation 으로 실시간 push.

    수명:
      1. open(session_id) — turn 시작 직전. session_id 미상이면 None 으로 호출해도
         되고, 첫 SystemMessage(init) 도착 시 다시 open 가능.
      2. on_text / on_tool_use — output 버퍼 누적 + 주기적 partial flush
      3. finalize_success / finalize_error — usage·cost·level 채워 generation 종료

    langfuse=None → 모든 메서드 no-op (관측 비활성 경로).
    SDK 예외는 worker 흐름을 막지 않도록 silent / warning.
    """

    def __init__(
        self,
        *,
        langfuse: Any,
        logger,
        cell_id: str | None,
        session_type: str | None,
        entity_type: str | None,
        session: EntitySession,
        prompt: str,
        resolved_model: str,
        entity_title: str | None = None,
        issue_owner: str | None = None,
        capability: list[str] | None = None,
        is_first: bool = False,
    ) -> None:
        self.lf = langfuse
        self.logger = logger
        self.cell_id = cell_id
        self.session_type = session_type
        self.entity_type = entity_type
        self.session = session
        self.prompt = prompt
        self.resolved_model = resolved_model
        self.entity_title = entity_title
        self.issue_owner = issue_owner
        self.capability = capability or []
        self.is_first = is_first
        self._gen: Any = None
        # turn 내내 누적만 한다. mid-turn 으로 Langfuse 에 push 하지 않으며
        # (실시간 보기는 in-app AI Activity 패널이 담당), turn 종료 시
        # finalize_* 가 최종 output 으로 1회 trace 를 마감·flush 한다.
        self._output_chunks: list[str] = []
        self._finalized: bool = False
        # tool_use_id → 열린 LangfuseTool span. ToolResultBlock 도착 시 매핑해 end.
        self._tool_spans: dict[str, Any] = {}

    def _trace_name(self) -> str:
        base = f"{self.session_type or 'unknown'}/{self.entity_type or 'unknown'}"
        if self.entity_title:
            return f"{base} — {self.entity_title[:80]}"
        return base

    def _tags(self, extra: list[str] | None = None) -> list[str]:
        tags: list[str] = []
        if self.cell_id:
            tags.append(f"cell:{self.cell_id}")
        if self.entity_type:
            tags.append(f"entity:{self.entity_type}")
        if self.resolved_model:
            tags.append(f"model:{self.resolved_model}")
        tags.append(f"is_first:{'true' if self.is_first else 'false'}")
        for cap in self.capability:
            if cap:
                tags.append(f"capability:{cap}")
        if extra:
            tags.extend(extra)
        return tags

    def open(self, session_id: str | None) -> None:
        if self.lf is None or self._gen is not None:
            return
        try:
            from langfuse import propagate_attributes
            with propagate_attributes(
                session_id=session_id,
                user_id=self.issue_owner or None,
                trace_name=self._trace_name(),
                tags=self._tags() or None,
            ):
                self._gen = self.lf.start_observation(
                    as_type="generation",
                    name=self._trace_name(),
                    model=self.resolved_model,
                    input=self.prompt,
                    metadata={
                        "cell_id": self.cell_id,
                        "entity_id": self.session.entity_id,
                        "entity_type": self.entity_type,
                        "session_type": self.session_type,
                    },
                )
        except Exception as exc:
            self.logger.warning(f"Langfuse generation 시작 실패: {exc}")
            self._gen = None

    def on_text(self, text: str) -> None:
        if self.lf is None or not text:
            return
        self._output_chunks.append(text)

    def on_tool_use_start(self, tool_use_id: str, name: str, tool_input: Any) -> None:
        """ToolUseBlock 도착 시 generation 의 child tool span 시작.

        Langfuse UI 의 trace tree 에 각 tool 호출이 펼쳐져, 어느 capability 가 시간/
        토큰을 잡아먹는지 즉시 시각화. tool_use_id 로 매핑해 매칭되는 ToolResultBlock
        도착 시 종료.
        """
        if self.lf is None or self._gen is None or not tool_use_id:
            return
        try:
            span = self._gen.start_observation(
                as_type="tool",
                name=name or "tool",
                input=tool_input,
            )
            self._tool_spans[tool_use_id] = span
            # text 흐름 안에서 tool 위치 가시화 — 기존 marker 동작 유지.
            self._output_chunks.append(f"\n[tool_use: {name}]\n")
        except Exception as exc:
            self.logger.debug(f"Langfuse tool span 시작 실패: {exc}")

    def on_tool_result(self, tool_use_id: str, content: Any, is_error: bool) -> None:
        """ToolResultBlock 도착 시 매칭 tool span 종료."""
        if self.lf is None or not tool_use_id:
            return
        span = self._tool_spans.pop(tool_use_id, None)
        if span is None:
            return
        try:
            span.update(
                output=content,
                level="ERROR" if is_error else "DEFAULT",
            )
            span.end()
        except Exception as exc:
            self.logger.debug(f"Langfuse tool span 종료 실패: {exc}")

    def finalize_success(self, data: dict) -> None:
        if self.lf is None or self._finalized:
            return
        self._finalized = True
        try:
            usage = data.get("usage") or {}
            model_usage = data.get("modelUsage") or {}
            model = next(iter(model_usage.keys()), None) or self.resolved_model
            final_output = data.get("result")
            if self._gen is None:
                from langfuse import propagate_attributes
                sid = data.get("session_id") or None
                with propagate_attributes(
                    session_id=sid,
                    user_id=self.issue_owner or None,
                    trace_name=self._trace_name(),
                    tags=self._tags() or None,
                ):
                    self._gen = self.lf.start_observation(
                        as_type="generation",
                        name=self._trace_name(),
                        model=model,
                        input=self.prompt,
                    )
            self._gen.update(
                output=final_output,
                model=model,
                metadata={
                    "cell_id": self.cell_id,
                    "entity_id": self.session.entity_id,
                    "entity_type": self.entity_type,
                    "entity_title": self.entity_title,
                    "session_type": self.session_type,
                    "capability": self.capability,
                    "is_first": self.is_first,
                    "num_turns": data.get("num_turns", 0),
                    "duration_ms": data.get("duration_ms", 0),
                    "duration_api_ms": data.get("duration_api_ms", 0),
                    "stop_reason": data.get("stop_reason"),
                    "api_error_status": data.get("api_error_status"),
                },
                usage_details={
                    "input": int(usage.get("input_tokens") or 0),
                    "output": int(usage.get("output_tokens") or 0),
                    "cache_read_input": int(usage.get("cache_read_input_tokens") or 0),
                    "cache_creation_input": int(usage.get("cache_creation_input_tokens") or 0),
                },
                cost_details={"total": float(data.get("total_cost_usd") or 0)},
                level="ERROR" if data.get("is_error") else "DEFAULT",
            )
            self._gen.end()
            self.lf.flush()
        except Exception as exc:
            self.logger.warning(f"Langfuse generation 종료 실패: {exc}")

    def finalize_error(self, *, elapsed_ms: int, message: str, session_id: str | None) -> None:
        """SDK 예외 / cancellation 등으로 ResultMessage 없이 끝난 경우."""
        if self.lf is None or self._finalized:
            return
        self._finalized = True
        try:
            partial = "".join(self._output_chunks)
            output = f"{partial}\n\n<{message}>" if partial else f"<{message}>"
            if self._gen is None:
                from langfuse import propagate_attributes
                with propagate_attributes(
                    session_id=session_id,
                    user_id=self.issue_owner or None,
                    trace_name=self._trace_name(),
                    tags=self._tags(["error"]) or None,
                ):
                    self._gen = self.lf.start_observation(
                        as_type="generation",
                        name=self._trace_name(),
                        model=self.resolved_model,
                        input=self.prompt,
                    )
            self._gen.update(
                output=output,
                metadata={
                    "cell_id": self.cell_id,
                    "entity_id": self.session.entity_id,
                    "entity_type": self.entity_type,
                    "entity_title": self.entity_title,
                    "session_type": self.session_type,
                    "capability": self.capability,
                    "is_first": self.is_first,
                    "duration_ms": int(elapsed_ms),
                },
                level="ERROR",
                status_message=message[:200],
            )
            self._gen.end()
            self.lf.flush()
        except Exception as exc:
            self.logger.warning(f"Langfuse error 기록 실패: {exc}")


def _safe_relay(relay: Callable[[dict], None] | None, item: dict) -> None:
    """relay 콜백 호출 — 어떤 예외도 turn 흐름을 막지 않는다.

    relay 는 hub 로 fine-grained AI activity(text/tool_use/tool_result)를
    push 하는 best-effort sink. PR #146 의 stdout `[ai-activity]` 채널을
    대체하며 (kubectl/stern 불요), UI 사이드바가 SSE 로 거의 실시간 표시.
    relay=None 이면 no-op (관측 비활성 경로 — Langfuse 와 독립).
    """
    if relay is None:
        return
    try:
        relay(item)
    except Exception:
        pass


def _mcp_dead_transition(streak: int, tr_is_error: bool, tr_content: Any) -> tuple[int, bool]:
    """mcp tool_result 하나에 대한 transport-dead streak 전이 → (new_streak, is_dead).

    dead 시그니처(error + mcp_transport_dead)면 streak+1, 임계 도달 시 is_dead.
    그 외(정상 결과·도메인 에러)는 streak 0 리셋. streak 은 run_agent 인자로 받아
    cross-turn 영속하므로(turn 당 mcp 호출 1회여도 누적), 매 turn 1 dead 인 zombie 도
    결국 임계에 도달해 잡힌다 — turn-local 이면 매 turn 리셋돼 영구 미탐이었다.
    """
    if tr_is_error and mcp_transport_dead(tr_content):
        streak += 1
        return streak, streak >= _MCP_TRANSPORT_DEAD_STREAK
    return 0, False


async def run_agent(
    *,
    client: AgentSession,
    logger,
    session: EntitySession,
    prompt: str,
    model: str | None = None,
    session_type: str | None = None,
    entity_type: str | None = None,
    langfuse: Any = None,
    cell_id: str | None = None,
    on_session_id: Callable[[str], None] | None = None,
    entity_title: str | None = None,
    issue_owner: str | None = None,
    capability: list[str] | None = None,
    is_first: bool = False,
    relay: Callable[[dict], None] | None = None,
    mcp_dead_streak: int = 0,
) -> dict:
    """한 turn = 한 prompt 를 SDK client 에 query 하고 ResultMessage 까지 소비.

    같은 client 를 cycle 마다 재사용하여 single long-running claude session 을
    유지한다. 반환 dict shape 은 기존 subprocess 기반 run_agent 와 호환.

    on_session_id: SystemMessage(init) 에서 session_id 추출 시 1회 콜백.
    entity_title / issue_owner / capability / is_first: Langfuse trace 의 가시성과
    차원별 dashboard 분석을 위한 메타. 없어도 동작은 동일.
    relay: text/tool_use/tool_result 를 hub 로 push 하는 best-effort sink
    (PR #146 stdout `[ai-activity]` 채널 대체 — UI 사이드바가 SSE 로 거의
    실시간 표시). None 이면 no-op. Langfuse 경로·반환 dict 와 완전 독립.
    mcp_dead_streak: 직전 turn 까지 누적된 transport-dead streak (cross-turn 영속).
    worker 가 반환 dict 의 `mcp_dead_streak` 를 다음 turn 에 다시 넘긴다.
    """
    resolved_model = model or resolve_model(EXEC_TIER_DEFAULT)
    if not model and logger:
        logger.warning(
            "model 미해소 — '%s' tier 기본 적용 (silent sonnet downgrade 방지)",
            EXEC_TIER_DEFAULT,
        )
    lf_stream = _LangfuseStream(
        langfuse=langfuse, logger=logger, cell_id=cell_id,
        session_type=session_type, entity_type=entity_type,
        session=session, prompt=prompt, resolved_model=resolved_model,
        entity_title=entity_title, issue_owner=issue_owner,
        capability=capability, is_first=is_first,
    )

    # 첫 cycle 이거나 hub 의 session_id 가 이미 있다면 미리 open. 첫 SystemMessage(init)
    # 가 도착하면 거기서 session_id 를 한 번 더 보정.
    initial_sid = session.session_id
    if initial_sid:
        lf_stream.open(initial_sid)

    sid_fired = False
    sid_captured: str | None = initial_sid
    # tool_use_id → tool name. tool_result relay item 에 어떤 툴의 결과인지
    # 붙이기 위한 turn-local 매핑 (lf_stream 의 span dict 와 별개).
    tool_names: dict[str, str] = {}
    start_ts = time.time()
    # MCP 세션 무효(hub 롤아웃) 감지 — mcp__* tool_use_id 를 모아 그 결과가
    # transport-dead 시그니처로 연속 실패하는지 센다. mcp_dead_streak 은 인자로
    # 받아 cross-turn 영속 (turn 당 mcp 호출 1회여도 누적 — 영구 zombie 탐지).
    mcp_tool_ids: set[str] = set()
    mcp_is_dead = False
    try:
        with session.lock:
            session.use_count += 1
        # turn 경계 — 이 turn 의 트리거(주입 작업지시/델타)를 live ring 에도
        # 흘려, 자율 워커가 왜 이때 도구를 시작했는지 맥락을 준다 (history
        # 경로는 세션 JSONL 의 user(str) 라인에서 동일 turn 마커를 만든다).
        _safe_relay(relay, {"kind": "turn", "prompt": prompt})
        await client.query(prompt)

        result_msg: ResultMessage | None = None
        async for message in client.receive_response():
            if isinstance(message, SystemMessage):
                sid = getattr(message, "session_id", None)
                if sid is None and hasattr(message, "data"):
                    sid = (getattr(message, "data", None) or {}).get("session_id")
                if sid and not sid_fired:
                    sid_fired = True
                    sid_captured = sid
                    with session.lock:
                        if not session.session_id:
                            session.session_id = sid
                    lf_stream.open(sid)
                    if on_session_id is not None:
                        try:
                            on_session_id(sid)
                        except Exception as e:
                            logger.debug(f"on_session_id 콜백 실패: {e}")
                continue

            if isinstance(message, AssistantMessage):
                for block in (message.content or []):
                    if isinstance(block, TextBlock):
                        text = block.text or ""
                        lf_stream.on_text(text)
                        if text.strip():
                            _safe_relay(relay, {"kind": "text", "text": text})
                    elif isinstance(block, ToolUseBlock):
                        tu_id = getattr(block, "id", "") or ""
                        tu_name = block.name or "?"
                        if tu_id:
                            tool_names[tu_id] = tu_name
                            if tu_name.startswith("mcp__"):
                                mcp_tool_ids.add(tu_id)
                        tu_input = getattr(block, "input", None)
                        lf_stream.on_tool_use_start(tu_id, tu_name, tu_input)
                        _safe_relay(relay, {
                            "kind": "tool_use",
                            "tool": tu_name,
                            "tool_use_id": tu_id,
                            "input": tu_input,
                        })
                continue

            if isinstance(message, UserMessage):
                # tool_result block 들이 들어오면 매칭 tool span 종료.
                for block in (message.content or []):
                    if isinstance(block, ToolResultBlock):
                        tr_id = getattr(block, "tool_use_id", "") or ""
                        tr_content = getattr(block, "content", None)
                        tr_is_error = bool(getattr(block, "is_error", False))
                        if tr_id in mcp_tool_ids:
                            mcp_dead_streak, _dead = _mcp_dead_transition(
                                mcp_dead_streak, tr_is_error, tr_content)
                            if _dead:
                                mcp_is_dead = True
                        lf_stream.on_tool_result(tr_id, tr_content, tr_is_error)
                        _safe_relay(relay, {
                            "kind": "tool_result",
                            "tool": tool_names.pop(tr_id, None),
                            "tool_use_id": tr_id,
                            "is_error": tr_is_error,
                            "output": tr_content,
                        })
                continue

            if isinstance(message, ResultMessage):
                result_msg = message
                break

    except Exception as exc:
        elapsed_ms = int((time.time() - start_ts) * 1000)
        err_msg = f"SDK exception: {type(exc).__name__}: {exc}"
        logger.error(f"[runtime] {err_msg}", exc_info=True)
        lf_stream.finalize_error(elapsed_ms=elapsed_ms, message=err_msg, session_id=sid_captured)
        return {"is_error": True, "result": err_msg, "session_id": sid_captured,
                "mcp_transport_dead": mcp_is_dead, "mcp_dead_streak": mcp_dead_streak}

    if result_msg is None:
        elapsed_ms = int((time.time() - start_ts) * 1000)
        err_msg = "SDK stream 종료 — ResultMessage 미수신"
        lf_stream.finalize_error(elapsed_ms=elapsed_ms, message=err_msg, session_id=sid_captured)
        return {"is_error": True, "result": err_msg, "session_id": sid_captured,
                "mcp_transport_dead": mcp_is_dead, "mcp_dead_streak": mcp_dead_streak}

    # SDK ResultMessage → 기존 dict shape 변환.
    data = _result_message_to_dict(result_msg, fallback_session_id=sid_captured, resolved_model=resolved_model)
    # MCP 세션 영구 무효 — turn 은 정상 종료해도(LLM 이 capability_rule 대로
    # curl 폴백 거부 후 텍스트만 출력) 시스템 반영 경로가 죽은 상태. worker 가
    # 이 플래그로 non-zero exit → fresh pod 재기동(새 MCP 세션)으로 복구.
    data["mcp_transport_dead"] = mcp_is_dead
    data["mcp_dead_streak"] = mcp_dead_streak

    if data.get("is_error"):
        subtype = data.get("subtype") or ""
        existing = (data.get("result") or "").strip()
        parts = [p for p in [subtype, existing] if p]
        data["result"] = " | ".join(parts) or "claude turn exited with error"
    else:
        with session.lock:
            session.last_prompt_at = datetime.now(timezone.utc).isoformat()

    new_id = data.get("session_id")
    if new_id and not data.get("is_error"):
        with session.lock:
            session.session_id = new_id

    lf_stream.finalize_success(data)
    return data


def _result_message_to_dict(
    msg: ResultMessage,
    *,
    fallback_session_id: str | None,
    resolved_model: str,
) -> dict:
    """SDK ResultMessage → 기존 stream-json result 이벤트와 호환되는 dict.

    SDK 의 ResultMessage attribute 이름은 버전마다 미세 변경 가능 — getattr 로 보호.
    """
    subtype = getattr(msg, "subtype", None) or "unknown"
    session_id = getattr(msg, "session_id", None) or fallback_session_id
    num_turns = int(getattr(msg, "num_turns", 0) or 0)
    duration_ms = int(getattr(msg, "duration_ms", 0) or 0)
    duration_api_ms = int(getattr(msg, "duration_api_ms", 0) or 0)
    total_cost_usd = float(getattr(msg, "total_cost_usd", 0.0) or 0.0)
    result_text = getattr(msg, "result", None)
    is_error = bool(getattr(msg, "is_error", False)) or (subtype != "success")

    usage_raw = getattr(msg, "usage", None) or {}
    if not isinstance(usage_raw, dict):
        usage_raw = {}

    model_usage = getattr(msg, "model_usage", None) or getattr(msg, "modelUsage", None) or {}
    if not isinstance(model_usage, dict):
        model_usage = {}
    if not model_usage and resolved_model:
        # 적어도 모델 키 1개는 두어 finalize_success 가 model 을 뽑을 수 있게 한다.
        model_usage = {resolved_model: {}}

    return {
        "is_error": is_error,
        "subtype": subtype,
        "stop_reason": getattr(msg, "stop_reason", None),
        "api_error_status": getattr(msg, "api_error_status", None),
        "result": result_text or "",
        "session_id": session_id,
        "num_turns": num_turns,
        "duration_ms": duration_ms,
        "duration_api_ms": duration_api_ms,
        "total_cost_usd": total_cost_usd,
        "usage": usage_raw,
        "modelUsage": model_usage,
    }


def log_usage(*, logger, session_type: str, entity_id: str, title: str, result: dict):
    """phase 비용·turn 수를 stdout 로그로만 남긴다. 영구 기록은 Langfuse 가 담당."""
    cost = result.get("total_cost_usd", 0)
    turns = result.get("num_turns", 0)
    duration = result.get("duration_ms", 0)
    logger.info(f"[{session_type}] {title} — ${cost:.4f}, {turns} turns, {duration}ms")
