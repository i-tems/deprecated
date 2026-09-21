"""FastAPI entrypoint: serves static page, OAuth, /api/ask (SSE), /api/history."""
import os
import asyncio
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import router as auth_router, require_user, get_claims
from .runner import stream_claude, sse
from .stats import record_usage, get_stats
from .audit import record as audit_record
from . import history

app = FastAPI(title="ai.i-tems.com", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth_router)

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_ROOT = Path("/data/uploads")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
ARCHIVE_ROOT = Path("/data/_archive")
ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)

MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "3"))
MAX_USD_PER_DAY = float(os.getenv("MAX_USD_PER_DAY", "80"))
MAX_PROMPT = int(os.getenv("MAX_PROMPT_CHARS", "50000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))

ALLOWED_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf",
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".xml", ".html", ".htm", ".log",
    ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
    ".py", ".ipynb", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".kt", ".swift", ".c", ".h", ".cc",
    ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh", ".bash", ".zsh",
    ".sql", ".r", ".lua", ".pl",
}

_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

PANDOC_EXT = {".docx", ".odt", ".pptx", ".odp", ".rst", ".html", ".htm"}


def _pandoc_to_markdown(src: Path) -> Path:
    if src.suffix.lower() not in PANDOC_EXT:
        return src
    dst = src.with_suffix(src.suffix + ".md")
    try:
        subprocess.run(
            ["pandoc", str(src), "-o", str(dst), "--wrap=none"],
            check=True, capture_output=True, timeout=30,
        )
        src.unlink(missing_ok=True)
        return dst
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return src


def _check_quota(email: str):
    # Daily USD budget per user. Cost is only known after a request finishes
    # (recorded into the persisted stats in the request's finally block), so
    # this gate is "have you already spent today's budget?" — a user can
    # exceed by at most one in-flight request's cost. Backed by the durable
    # /data/_stats.json (survives pod restarts), unlike the old in-memory
    # request counter.
    spent = float(get_stats(email)["today"].get("cost") or 0.0)
    if spent >= MAX_USD_PER_DAY:
        raise HTTPException(
            429, f"daily budget reached (${spent:.2f} / ${MAX_USD_PER_DAY:.2f})"
        )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/stats")
async def stats_endpoint(user=Depends(require_user)):
    return get_stats(user["email"])


# ── History endpoints ──────────────────────────────────────────────

@app.get("/api/history")
async def history_list(user=Depends(require_user)):
    return history.list_all(user["email"])


@app.get("/api/history/{cid}")
async def history_get(cid: str, user=Depends(require_user)):
    entry = history.get(user["email"], cid)
    if not entry:
        raise HTTPException(404, "not found")
    return entry


@app.delete("/api/history/{cid}")
async def history_delete(cid: str, user=Depends(require_user)):
    if not history.delete(user["email"], cid):
        raise HTTPException(404, "not found")
    return {"ok": True}


# ── Ask endpoint ───────────────────────────────────────────────────

@app.post("/api/ask")
async def ask(
    request: Request,
    prompt: str = Form(...),
    conversation_id: str = Form(default=""),
    files: List[UploadFile] = File(default=[]),
    user=Depends(require_user),
):
    email = user["email"]
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(400, "empty prompt")
    if len(prompt) > MAX_PROMPT:
        raise HTTPException(400, f"prompt too long (max {MAX_PROMPT})")

    _check_quota(email)

    # Resolve the conversation: continue an existing one if a valid id was
    # sent and it belongs to this user, otherwise start a fresh one. We
    # resume the conversation's claude session so the Anthropic prompt cache
    # hits across turns (only the new message is sent; claude restores the
    # prior context server-side).
    conversation_id = (conversation_id or "").strip()
    claude_session_id = ""
    resume_session = False
    if history.is_valid_id(conversation_id):
        existing = history.get(email, conversation_id)
        if existing:
            claude_session_id = (existing.get("session_id") or "").strip()
            resume_session = bool(claude_session_id)
        else:
            conversation_id = history.new_id()
    else:
        conversation_id = history.new_id()
    if not claude_session_id:
        # New conversation (or a legacy one with no session): pin a fresh
        # claude session id so subsequent turns can --resume it.
        claude_session_id = str(uuid.uuid4())

    req_id = uuid.uuid4().hex
    upload_dir: Optional[Path] = None
    saved: List[dict] = []
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024

    try:
        for idx, f in enumerate(files, start=1):
            if not f.filename:
                continue
            orig_name = Path(f.filename).name
            ext = Path(orig_name).suffix.lower()
            if ext not in ALLOWED_EXT:
                raise HTTPException(400, f"extension not allowed: {ext}")
            if upload_dir is None:
                upload_dir = UPLOAD_ROOT / req_id
                upload_dir.mkdir(parents=True, exist_ok=True)
            safe_name = f"file-{idx}{ext}"
            dest = upload_dir / safe_name
            size = 0
            with dest.open("wb") as out:
                while True:
                    chunk = await f.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(413, f"file too large (max {MAX_UPLOAD_MB}MB)")
                    out.write(chunk)
            final = _pandoc_to_markdown(dest)
            saved.append({"orig": orig_name, "path": str(final)})
    except Exception:
        if upload_dir is not None:
            shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    if saved:
        file_list = "\n".join(
            f"- 원본 파일명: {item['orig']}  →  경로: {item['path']}"
            for item in saved
        )
        full_prompt = (
            f"{prompt}\n\n---\n"
            f"첨부 파일이 아래 경로에 저장되어 있습니다. "
            f"Read 도구로 각 경로를 읽어서 내용을 참고해 답변하세요.\n"
            f"(docx/odt/pptx 등은 이미 서버에서 markdown으로 변환되어 있습니다.)\n\n"
            f"{file_list}"
        )
    else:
        full_prompt = prompt

    captured: dict = {}
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:200]
    file_names = [s["orig"] for s in saved]
    stream_error: dict = {}
    response_acc: list = []

    def _on_result(r: dict):
        captured.update(r)

    async def event_stream():
        try:
            # Tell the client which conversation this turn belongs to so it
            # can keep continuing it (esp. for a freshly created one).
            yield sse("conversation", {"id": conversation_id})
            async with _semaphore:
                async for chunk in stream_claude(
                    full_prompt, upload_dir, on_result=_on_result,
                    session_id=claude_session_id, resume=resume_session,
                ):
                    # Collect response text for history
                    try:
                        raw = chunk.decode("utf-8", errors="replace")
                        for block in raw.split("\n\n"):
                            lines = block.split("\n")
                            ev_line = next((l for l in lines if l.startswith("event: ")), None)
                            data_line = next((l for l in lines if l.startswith("data: ")), None)
                            if ev_line and data_line:
                                ev = ev_line[7:].strip()
                                if ev == "delta":
                                    import json as _json
                                    try:
                                        payload = _json.loads(data_line[6:])
                                        response_acc.append(payload.get("text", ""))
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    yield chunk
        except Exception as e:
            stream_error["message"] = f"{e!r}"
            yield sse("error", {"message": f"internal error: {e!r}"})
        finally:
            usage = (captured.get("usage") or {}) if captured else {}
            if captured:
                try:
                    record_usage(email, captured)
                except Exception:
                    pass
            # Save to history
            response_text = "".join(response_acc)
            if response_text and not stream_error:
                try:
                    history.append(
                        email=email,
                        cid=conversation_id,
                        user_text=prompt,
                        assistant_text=response_text,
                        cost_usd=captured.get("cost"),
                        duration_ms=captured.get("duration_ms"),
                        session_id=(captured.get("session_id")
                                    or claude_session_id),
                    )
                except Exception:
                    pass
            try:
                audit_record({
                    "email": email,
                    "ip": ip,
                    "ua": ua,
                    "prompt_chars": len(prompt),
                    "prompt_preview": prompt[:500],
                    "file_count": len(file_names),
                    "files": file_names,
                    "duration_ms": captured.get("duration_ms") if captured else None,
                    "cost": captured.get("cost") if captured else None,
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "cache_write_tokens": usage.get("cache_creation_input_tokens"),
                    "cache_read_tokens": usage.get("cache_read_input_tokens"),
                    "is_error": bool(stream_error) or (captured.get("is_error", False) if captured else True),
                    "error": stream_error.get("message"),
                })
            except Exception:
                pass
            if upload_dir is not None:
                try:
                    archive_dest = ARCHIVE_ROOT / upload_dir.name
                    shutil.move(str(upload_dir), str(archive_dest))
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
