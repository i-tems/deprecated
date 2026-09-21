import asyncio
import gzip
import logging
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.events import emit_request
from app.core.storage import DATA_DIR, storage, _read_collection
from app.routers import auth, groups, ai_schedule, patterns, schedules

logger = logging.getLogger("meetup.scheduler")

_KST = timezone(timedelta(hours=9))


async def _daily_pattern_extend():
    """Background task: extend all users's shift patterns to +365 days, once per day."""
    while True:
        try:
            all_patterns = _read_collection("shift_patterns")
            user_ids = {p["user_id"] for p in all_patterns}
            for user_id in user_ids:
                user_patterns = [p for p in all_patterns if p["user_id"] == user_id]
                for pattern in user_patterns:
                    await patterns._generate_blocks_from_pattern(user_id, pattern)
            if user_ids:
                logger.info(f"Pattern auto-extend done: {len(all_patterns)} patterns for {len(user_ids)} users")
        except Exception:
            logger.exception("Pattern auto-extend failed")
        await asyncio.sleep(86400)  # 24h


async def _daily_event_rotate():
    """Background task: gzip previous-day NDJSON event files at KST midnight; delete >13 months."""
    while True:
        try:
            now_kst = datetime.now(_KST)
            next_midnight = (now_kst + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            wait_sec = (next_midnight - now_kst).total_seconds()
            await asyncio.sleep(wait_sec)

            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            cutoff = datetime.now(timezone.utc) - timedelta(days=395)  # ~13 months

            events_dir = DATA_DIR / "events"
            if not events_dir.exists():
                continue

            for path in sorted(events_dir.iterdir()):
                name = path.name
                # Skip already compressed and active (today's) files
                if name.endswith(".gz"):
                    continue
                if not (name.endswith(".ndjson") or name.endswith(".requests.ndjson")):
                    continue

                # Extract date prefix (yyyy-mm-dd)
                date_part = name.split(".")[0]
                if date_part == today_utc:
                    continue

                try:
                    file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

                if file_date < cutoff:
                    path.unlink(missing_ok=True)
                    logger.info("event log deleted (>13mo): %s", name)
                else:
                    gz_path = path.with_suffix(path.suffix + ".gz")
                    with open(path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    path.unlink()
                    logger.info("event log rotated: %s → %s", name, gz_path.name)

        except Exception:
            logger.exception("Event log rotation failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "events").mkdir(parents=True, exist_ok=True)
    task1 = asyncio.create_task(_daily_pattern_extend())
    task2 = asyncio.create_task(_daily_event_rotate())
    yield
    task1.cancel()
    task2.cancel()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emits request.completed for every HTTP request (guardrail: error rate / p95 latency)."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        route = request.scope.get("route")
        route_pattern = route.path if route else request.url.path
        method = request.method

        emit_request("request.completed", {
            "route_pattern": f"{method} {route_pattern}",
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        })
        return response


app = FastAPI(title="Meetup Scheduler", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:3004", "https://meetup.i-tems.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router)
app.include_router(schedules.router)
app.include_router(patterns.router)
app.include_router(groups.router)
app.include_router(ai_schedule.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
