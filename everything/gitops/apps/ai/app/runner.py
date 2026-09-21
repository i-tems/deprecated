"""Run `claude -p` as subprocess and stream stream-json output as SSE."""
import os
import asyncio
import json
import time
from pathlib import Path
from typing import Optional, AsyncIterator

TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SEC", "600"))

# Dedicated working dir for the claude subprocess. claude stores resumable
# sessions under $HOME/.claude/projects/<cwd-slug>/. HOME is the shared NFS
# (for the single shared credentials file), so we pin a unique cwd here to
# give ai its own project-slug subtree — isolated from the hive workers'
# sessions while still sharing only ~/.claude/.credentials.json.
AI_CLAUDE_CWD = os.getenv("AI_CLAUDE_CWD", "/data/claude-cwd")
os.makedirs(AI_CLAUDE_CWD, exist_ok=True)


def sse(event: str, data) -> bytes:
    body = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


async def _drain(stream, buf: list):
    async for line in stream:
        buf.append(line.decode("utf-8", errors="replace"))


async def stream_claude(
    prompt: str,
    add_dir: Optional[Path],
    on_result=None,
    session_id: Optional[str] = None,
    resume: bool = False,
) -> AsyncIterator[bytes]:
    args = [
        "claude", "-p",
        "--model", "opus",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--disable-slash-commands",
        "--permission-mode", "default",
    ]
    # Session persistence is ON (no --no-session-persistence) so turns can be
    # resumed — this is what lets the Anthropic prompt cache hit across turns.
    if session_id:
        if resume:
            # Resume the prior session; only the new user message is sent and
            # claude restores the conversation context server-side.
            args += ["--resume", session_id]
        else:
            # First turn: pin the session id so later turns can --resume it.
            args += ["--session-id", session_id]
    if add_dir is not None:
        args += ["--add-dir", str(add_dir), "--tools", "Read"]
    else:
        args += ["--tools", ""]

    # StreamReader buffer — claude's stream-json "result" line can be tens of KB
    # (bundles full conversation); default 64K asyncio limit overflows.
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,
        cwd=AI_CLAUDE_CWD,
    )
    assert proc.stdin and proc.stdout and proc.stderr

    proc.stdin.write(prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    yield sse("start", {})

    deadline = time.monotonic() + TIMEOUT
    stderr_buf: list = []
    stderr_task = asyncio.create_task(_drain(proc.stderr, stderr_buf))
    timed_out = False

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                timed_out = True
                break
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(),
                    timeout=min(remaining, 30),
                )
            except asyncio.TimeoutError:
                yield sse("ping", {})
                continue
            if not line:
                break
            line_s = line.decode("utf-8", errors="replace").strip()
            if not line_s:
                continue
            try:
                obj = json.loads(line_s)
            except json.JSONDecodeError:
                continue

            t = obj.get("type")
            if t == "stream_event":
                ev = obj.get("event", {})
                if ev.get("type") == "content_block_delta":
                    delta = ev.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield sse("delta", {"text": text})
            elif t == "result":
                usage = obj.get("usage") or {}
                payload = {
                    "cost_usd": obj.get("total_cost_usd"),
                    "duration_ms": obj.get("duration_ms"),
                    "is_error": obj.get("is_error", False),
                    "text": obj.get("result", ""),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
                    "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                    "session_id": obj.get("session_id"),
                }
                if on_result:
                    try:
                        on_result({
                            "cost": payload["cost_usd"],
                            "usage": usage,
                            "duration_ms": payload["duration_ms"],
                            "is_error": payload["is_error"],
                            "session_id": obj.get("session_id"),
                        })
                    except Exception:
                        pass
                yield sse("result", payload)

        rc = await proc.wait()
        await stderr_task

        if timed_out:
            yield sse("error", {"message": f"timeout after {TIMEOUT}s"})
        elif rc and rc != 0:
            err_tail = "".join(stderr_buf).strip()[-500:]
            yield sse("error", {
                "message": f"claude exited {rc}",
                "detail": err_tail,
            })
        yield sse("end", {})
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
