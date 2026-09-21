"""Codex (OpenAI) backend — `AGENT_BACKEND=codex` 일 때 make_agent_session 이 반환.

ClaudeSDKClient 대안. codex CLI 를 `codex exec --json` 으로 turn 당 1회 subprocess
구동하고, codex 의 JSONL 이벤트를 claude_agent_sdk Message 타입으로 변환해 yield 한다.
소비 루프(runtime._stream_turn)는 backend 종류를 모르고 같은 isinstance 분기로 처리
한다 — Message 타입을 그대로 재사용하는 의도된 leakage (runtime.AgentSession 주석 참조).

세션 연속성: codex thread 를 thread_id 로 resume (`codex exec resume <tid>`). worker 가
thread_id 를 session_id 로 hub 에 영속화 → fresh pod 가 같은 thread 를 이어간다
(ClaudeSDKClient 의 --resume 등가).

인증: ChatGPT 구독 OAuth (`~/.codex/auth.json`, CODEX_HOME). 유료 API 0. MCP 는 hub
`/mcp/` streamable HTTP, HUB_CALLER_TOKEN(worker JWT) Bearer — worker 의 _setup_mcp_config
가 ClaudeSDKClient 용으로 쓰는 것과 같은 토큰/엔드포인트를 codex `-c` 오버라이드로 전달.

NOTE: CLAUDE.md/rules/skills 하네스의 codex 이식(AGENTS.md/.codex)은 ruler 자매 이슈 소관.
이 모듈은 worker↔codex 배선(세션·이벤트·MCP)만 담당한다.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import ToolResultBlock

# ChatGPT 구독 계정에서 허용되는 모델 (gpt-5.4 / gpt-5.5-codex 등은 거부됨 — PoC 확인).
DEFAULT_CODEX_MODEL = "gpt-5.5"


def _codex_bin() -> str:
    return os.environ.get("CODEX_BIN") or shutil.which("codex") or "codex"


def _mcp_tool_name(item: dict) -> str:
    """codex {server, tool} → Claude 컨벤션 mcp__<server>__<tool>.

    worker 의 MCP-dead 감지(mcp__ prefix)·Langfuse server 파싱이 이 형식에 의존.
    """
    return f"mcp__{item.get('server', '?')}__{item.get('tool', '?')}"


def _tool_result_content(item: dict) -> Any:
    """codex mcp_tool_call.result → ToolResultBlock.content 로 넘길 값.

    result 는 {content: [...]|str, structured_content}. content 를 그대로 전달
    (lf_stream.on_tool_result·relay·mcp_transport_dead 가 소비).
    """
    res = item.get("result")
    if isinstance(res, dict) and "content" in res:
        return res["content"]
    if item.get("error"):
        return str(item["error"])
    return res


def _map_usage(u: dict | None) -> dict:
    """codex usage → SDK usage dict (lf_stream finalize 가 읽는 키)."""
    u = u or {}
    return {
        "input_tokens": int(u.get("input_tokens", 0) or 0),
        "output_tokens": int(u.get("output_tokens", 0) or 0),
        "cache_read_input_tokens": int(u.get("cached_input_tokens", 0) or 0),
        "cache_creation_input_tokens": 0,
        "reasoning_output_tokens": int(u.get("reasoning_output_tokens", 0) or 0),
    }


def _err_text(ev: dict) -> str:
    if isinstance(ev.get("message"), str):
        return ev["message"]
    err = ev.get("error")
    if isinstance(err, dict) and isinstance(err.get("message"), str):
        return err["message"]
    return json.dumps(ev, ensure_ascii=False)[:500]


def _is_resume_failure(stderr: str) -> bool:
    """codex exec resume 가 thread 부재로 실패한 시그니처.

    cutover 시 entity 의 session_id 가 타 backend(Claude) 세션이면 codex thread
    스토어에 없어 "no rollout found for thread id" / "resume failed" 로 죽는다.
    """
    s = stderr.lower()
    return "resume failed" in s or "no rollout found" in s


class CodexAgentSession:
    """AgentSession Protocol 구현 (codex backend). turn 당 codex exec 1 프로세스."""

    def __init__(
        self,
        *,
        model: str | None,
        cwd: str | None,
        hub_url: str | None,
        caller_token: str | None,
        resume_session_id: str | None,
        deadline_epoch: int | None = None,
        timeout_sec: int | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._model = model or DEFAULT_CODEX_MODEL
        self._cwd = cwd
        self._hub_url = (hub_url or "").rstrip("/")
        self._caller_token = caller_token
        self._thread_id = resume_session_id
        self._deadline_epoch = deadline_epoch
        self._timeout_sec = timeout_sec
        self._system_prompt = system_prompt
        self._system_injected = bool(resume_session_id)  # resume 면 이미 thread 에 있음
        self._proc: asyncio.subprocess.Process | None = None
        self._start_ts = 0.0
        self._last_text = ""

    async def __aenter__(self) -> "CodexAgentSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._kill_proc()

    async def _kill_proc(self) -> None:
        p = self._proc
        if p is not None and p.returncode is None:
            try:
                p.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(p.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    p.kill()
                except ProcessLookupError:
                    pass
        self._proc = None

    def _build_argv(self, prompt: str) -> list[str]:
        # codex exec 옵션(-C·-m·--json·-c 등)은 `resume` 서브커맨드 *앞*에 와야 한다.
        # resume 뒤에 두면 `codex exec resume` 가 모르는 인자로 거부한다("unexpected
        # argument '-C'", rc=2) → multi-turn(resume) 워커 전멸. 첫 turn 은 resume 가
        # 없어 통과하므로 단일턴 테스트로는 안 잡힌다(INFRA-ISSUE-256 회귀).
        argv = [_codex_bin(), "exec"]
        argv += [
            "--json",
            "-m", self._model,
            # worker 는 ClaudeSDKClient 의 permission_mode=bypassPermissions 와 동등하게
            # 비대화·무승인 실행 (MCP 툴 승인 게이트 포함) 이 필요 — PoC 에서 'user
            # cancelled' 의 원인이 이 게이트였다.
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if self._cwd:
            argv += ["-C", self._cwd, "--skip-git-repo-check"]
        # MCP: hub streamable HTTP. 토큰은 config 에 박지 않고 env var 참조 (비밀 비기록).
        if self._hub_url and self._caller_token:
            argv += [
                "-c", f'mcp_servers.hive.url="{self._hub_url}/mcp/"',
                "-c", 'mcp_servers.hive.bearer_token_env_var="HUB_CALLER_TOKEN"',
            ]
            # 테스트 seam — console JWT 경로는 X-Source=console 필요 (prod caller_token 은 불필요).
            extra = os.environ.get("CODEX_MCP_HTTP_HEADERS")
            if extra:
                argv += ["-c", f"mcp_servers.hive.http_headers={extra}"]
        # resume 서브커맨드 + thread_id 는 모든 옵션 뒤, prompt 앞.
        if self._thread_id:
            argv += ["resume", self._thread_id]
        argv.append(prompt)
        return argv

    async def query(self, prompt: str) -> None:
        await self._kill_proc()
        # 런타임 사실(system_prompt)은 첫 turn 프롬프트에 preamble 로 주입 (codex exec 는
        # --system-prompt 가 없음; thread 가 이후 turn 에 맥락 유지).
        if self._system_prompt and not self._system_injected:
            prompt = f"{self._system_prompt}\n\n---\n\n{prompt}"
            self._system_injected = True

        env = dict(os.environ)
        if self._caller_token:
            env["HUB_CALLER_TOKEN"] = self._caller_token
        if self._deadline_epoch is not None:
            env["HIVE_SESSION_DEADLINE_UTC"] = str(int(self._deadline_epoch))
        if self._timeout_sec is not None:
            env["HIVE_SESSION_TIMEOUT_SEC"] = str(int(self._timeout_sec))

        self._pending_prompt = prompt
        self._pending_env = env
        self._fresh_retried = False
        await self._spawn()

    async def _spawn(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._build_argv(self._pending_prompt),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd or None,
            env=self._pending_env,
            # codex JSONL 한 줄(큰 tool_result·agent_message)이 asyncio StreamReader 기본
            # 버퍼 64KB 를 넘으면 receive_response 의 line iteration 이 "Separator is not
            # found, and chunk exceed the limit" 로 깨진다 (INFRA-ISSUE-256, 큰 entity 에서
            # 재현). 넉넉히 16MB.
            limit=16 * 1024 * 1024,
        )
        self._start_ts = time.time()

    def _translate(self, ev: dict) -> tuple[list[Any], bool]:
        """codex JSONL 이벤트 1개 → (SDK messages, is_terminal).

        self._thread_id / self._last_text 를 mutate. subprocess 없이 호출 가능해
        synthetic 이벤트로 단위 테스트한다 (매핑이 이 backend 의 fragile 한 부분).
        """
        t = ev.get("type")

        if t == "thread.started":
            tid = ev.get("thread_id")
            if tid:
                self._thread_id = tid
                return [SystemMessage(subtype="init", data={"session_id": tid})], False
            return [], False

        if t == "item.started":
            it = ev.get("item") or {}
            if it.get("type") == "mcp_tool_call":
                return [AssistantMessage(
                    content=[ToolUseBlock(
                        id=it.get("id") or "",
                        name=_mcp_tool_name(it),
                        input=it.get("arguments") or {},
                    )],
                    model=self._model,
                )], False
            return [], False

        if t == "item.completed":
            it = ev.get("item") or {}
            itt = it.get("type")
            if itt == "mcp_tool_call":
                is_error = it.get("status") == "failed" or bool(it.get("error"))
                return [UserMessage(content=[ToolResultBlock(
                    tool_use_id=it.get("id") or "",
                    content=_tool_result_content(it),
                    is_error=is_error,
                )])], False
            if itt == "agent_message":
                txt = it.get("text") or ""
                self._last_text = txt
                if txt.strip():
                    return [AssistantMessage(content=[TextBlock(text=txt)], model=self._model)], False
            # reasoning/command_execution/file_change 등은 best-effort skip.
            return [], False

        if t == "turn.completed":
            return [self._result_message(
                usage=ev.get("usage"), text=self._last_text, is_error=False, subtype="success")], True

        if t in ("turn.failed", "error"):
            return [self._result_message(
                usage=None, text=_err_text(ev), is_error=True, subtype="error")], True

        return [], False

    async def receive_response(self) -> AsyncIterator[Any]:
        # resume 실패 시 fresh session 으로 1회 재시도하기 위해 루프로 감싼다.
        while True:
            if self._proc is None or self._proc.stdout is None:
                raise RuntimeError("query() 선행 필요")

            self._last_text = ""
            terminal = False
            async for raw in self._proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                messages, is_terminal = self._translate(ev)
                for m in messages:
                    yield m
                if is_terminal:
                    terminal = True
                    break

            await self._proc.wait()
            if terminal:
                return

            stderr = b""
            if self._proc.stderr is not None:
                try:
                    stderr = await self._proc.stderr.read()
                except Exception:
                    pass
            tail = stderr.decode("utf-8", "replace")[-2000:]

            # resume 실패(타 backend session_id 등 → "no rollout found")면 thread_id 를
            # 버리고 fresh session 으로 1회 재시도 (cutover 시 in-flight entity 보호).
            if self._thread_id and not self._fresh_retried and _is_resume_failure(tail):
                self._fresh_retried = True
                self._thread_id = None
                await self._kill_proc()
                await self._spawn()
                continue

            yield self._result_message(
                usage=None,
                text=f"codex 종료 — terminal 이벤트 미수신 (rc={self._proc.returncode}). stderr: {tail}",
                is_error=True, subtype="error")
            return

    def _result_message(self, *, usage: dict | None, text: str, is_error: bool, subtype: str) -> ResultMessage:
        elapsed = int((time.time() - (self._start_ts or time.time())) * 1000)
        return ResultMessage(
            subtype=subtype,
            duration_ms=elapsed,
            duration_api_ms=0,
            is_error=is_error,
            num_turns=1,
            session_id=self._thread_id,
            total_cost_usd=0.0,  # 구독 OAuth — 호출당 과금 0.
            usage=_map_usage(usage),
            result=text,
            model_usage={self._model: {}},
        )
