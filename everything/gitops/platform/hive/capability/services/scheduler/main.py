"""Scheduler capability server.

Cron 기반 스케줄 관리. 지정 시간에 Core API capability를 자동 호출한다.
단일 호출(endpoint+body) 또는 다단계 파이프라인(steps) 지원.
APScheduler + JSON 파일 영속화. Asia/Seoul 타임존 기본.

파이프라인 예시:
    {
        "steps": [
            {"id": "sigs", "endpoint": "signal.list", "body": {"status": "emitted"}},
            {"endpoint": "project.create", "foreach": "sigs.signals", "body": {
                "title": "{{item.detail.message}}"
            }},
            {"endpoint": "signal.update_status", "foreach": "sigs.signals", "body": {
                "signal_id": "{{item.signal_id}}", "status": "consumed"
            }}
        ]
    }
"""

import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, model_validator
from uuid_utils import uuid7

from capability_framework import CapabilityResponse, create_app

logger = logging.getLogger(__name__)

# --- Config ---

HUB_URL = os.environ.get("HUB_URL", "http://core:8000")
CELL_ID = os.environ.get("CELL_ID", os.environ.get("DEFAULT_CELL_ID", "default"))
HUB_INTERNAL_TOKEN = os.environ.get("HUB_INTERNAL_TOKEN", "").strip()
DATA_DIR = Path(os.environ.get("DATA_DIR", "/var/data"))
SCHEDULES_FILE = DATA_DIR / "schedules.json"
TIMEZONE = os.environ.get("TZ", "Asia/Seoul")

app = create_app(
    service_id="scheduler",
    version="0.2.0",
    description="Cron 기반 스케줄러. 단일 호출 또는 다단계 파이프라인을 지정 시간에 자동 실행한다.",
)

cron_scheduler = AsyncIOScheduler(timezone=TIMEZONE)
_lock = threading.Lock()


# --- Persistence ---


def _load() -> dict:
    if SCHEDULES_FILE.exists():
        return json.loads(SCHEDULES_FILE.read_text())
    return {}


def _save(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str)
    )


# --- Pipeline engine ---

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


def _resolve_path(context: dict, path: str):
    """Dot-separated path를 context에서 탐색. dict key와 list index 지원."""
    parts = path.split(".")
    current = context
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(part)
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                raise KeyError(part)
        else:
            raise KeyError(part)
    return current


def _resolve_templates(value, context: dict):
    """값 내부의 {{path}} 템플릿을 context 기반으로 치환. 타입 보존."""
    if isinstance(value, str):
        full = re.fullmatch(r"\s*\{\{(.+?)\}\}\s*", value)
        if full:
            try:
                return _resolve_path(context, full.group(1).strip())
            except KeyError:
                return value
        def _replacer(m):
            try:
                return str(_resolve_path(context, m.group(1).strip()))
            except KeyError:
                return m.group(0)
        return _TEMPLATE_RE.sub(_replacer, value)
    elif isinstance(value, dict):
        return {k: _resolve_templates(v, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_templates(v, context) for v in value]
    return value


def _execute_pipeline(steps: list[dict], headers: dict) -> dict:
    """steps 목록을 순차 실행. foreach가 있으면 배열 순회."""
    context: dict = {}
    step_results: list[dict] = []

    with httpx.Client(timeout=60) as client:
        for step in steps:
            step_id = step.get("id")
            endpoint = step["endpoint"]
            body_tpl = step.get("body", {})
            foreach = step.get("foreach")

            if foreach:
                try:
                    items = _resolve_path(context, foreach)
                except KeyError:
                    step_results.append({
                        "step": step_id or endpoint,
                        "status": "error",
                        "error": f"foreach path '{foreach}' not found in context",
                    })
                    break

                if not isinstance(items, list):
                    items = [items]

                item_results = []
                for idx, item in enumerate(items):
                    item_ctx = {**context, "item": item, "_index": idx}
                    body = _resolve_templates(body_tpl, item_ctx)
                    try:
                        resp = client.post(
                            f"{HUB_URL}/{endpoint}",
                            json=body,
                            headers=headers,
                            timeout=30,
                        )
                        resp_data = resp.json()
                        item_results.append({
                            "status": "ok" if resp.status_code == 200 else "error",
                            "data": resp_data.get("data"),
                        })
                    except Exception as e:
                        item_results.append({"status": "error", "error": str(e)})

                if step_id:
                    context[step_id] = item_results

                ok_count = sum(1 for r in item_results if r["status"] == "ok")
                step_results.append({
                    "step": step_id or endpoint,
                    "count": len(items),
                    "ok": ok_count,
                    "errors": len(items) - ok_count,
                })

            else:
                body = _resolve_templates(body_tpl, context)
                try:
                    resp = client.post(
                        f"{HUB_URL}/{endpoint}",
                        json=body,
                        headers=headers,
                        timeout=30,
                    )
                    resp_data = resp.json()
                    result_data = resp_data.get("data")
                    status = "ok" if resp.status_code == 200 else "error"

                    if step_id:
                        context[step_id] = result_data

                    entry = {"step": step_id or endpoint, "status": status}
                    if status == "error":
                        entry["error"] = resp_data.get("message", resp.text[:200])
                        step_results.append(entry)
                        break
                    step_results.append(entry)

                except Exception as e:
                    step_results.append({
                        "step": step_id or endpoint,
                        "status": "error",
                        "error": str(e),
                    })
                    break

    return {"steps": step_results}


# --- Job execution ---


def _execute_job(schedule_id: str) -> dict:
    """스케줄 1건 실행 — 동기 blocking 함수(_execute_pipeline 의 sync httpx HTTP).

    반드시 executor 스레드에서만 호출한다(이벤트 루프에서 직접 호출 금지). 현재 두 경로
    모두 offload 됨: 수동 트리거는 schedule_run 이 run_in_executor 로(이 파일 schedule_run),
    cron 트리거는 AsyncIOScheduler 가 sync job 을 기본 ThreadPoolExecutor 로 돌린다
    (_register_job 의 add_job). async 핸들러에서 직접 await/호출하면 sync httpx 가 루프를
    막으니 이 offload 계약을 깨지 말 것.
    """
    with _lock:
        schedules = _load()
        s = schedules.get(schedule_id)
        if not s:
            return {"status": "error", "detail": "schedule not found"}
        action = dict(s["action"])

    headers = {"Content-Type": "application/json", "X-Cell-Id": CELL_ID}
    if HUB_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = HUB_INTERNAL_TOKEN

    if action.get("steps"):
        result = _execute_pipeline(action["steps"], headers)
        has_error = any(
            sr.get("status") == "error" or sr.get("errors", 0) > 0
            for sr in result["steps"]
        )
        status = "error" if has_error else "ok"
        detail = json.dumps(result, ensure_ascii=False, default=str)[:500]
    else:
        url = f"{HUB_URL}/{action['endpoint']}"
        try:
            resp = httpx.post(
                url,
                json=action.get("body", {}),
                headers=headers,
                timeout=30,
            )
            status = "ok" if resp.status_code == 200 else "error"
            detail = resp.text[:500]
        except Exception as e:
            status = "error"
            detail = str(e)

    now = datetime.now().isoformat()
    with _lock:
        schedules = _load()
        s = schedules.get(schedule_id)
        if s:
            s["last_run"] = now
            s.setdefault("history", []).append({"ran_at": now, "status": status})
            s["history"] = s["history"][-20:]
            _save(schedules)

    logger.info(
        "Schedule %s (%s) executed: %s",
        schedule_id,
        s.get("name", "?") if s else "?",
        status,
    )
    return {"ran_at": now, "status": status, "detail": detail}


def _register_job(schedule_id: str, cron: str):
    trigger = CronTrigger.from_crontab(cron, timezone=TIMEZONE)
    cron_scheduler.add_job(
        _execute_job,
        trigger=trigger,
        args=[schedule_id],
        id=schedule_id,
        replace_existing=True,
    )


# ============================================================
# Models
# ============================================================


class ActionStep(BaseModel):
    id: str | None = Field(
        default=None,
        description="단계 ID. 이후 단계에서 {{id.path}} 형태로 결과 참조",
        examples=["signals", "projects"],
    )
    endpoint: str = Field(
        description="호출할 capability endpoint",
        examples=["signal.list", "project.create"],
    )
    body: dict = Field(
        default_factory=dict,
        description="요청 body. {{step_id.path}} 또는 foreach 내 {{item.path}} 템플릿 지원",
    )
    foreach: str | None = Field(
        default=None,
        description="반복 대상 경로. 이전 단계 결과에서 배열을 참조 (예: 'sigs.signals')",
    )


class ScheduleAction(BaseModel):
    endpoint: str | None = Field(
        default=None,
        description="호출할 capability endpoint (단일 호출 모드)",
        examples=["slack.send", "issue.create"],
    )
    body: dict = Field(
        default_factory=dict,
        description="요청 body (JSON)",
    )
    steps: list[ActionStep] | None = Field(
        default=None,
        description="파이프라인 단계 목록. 설정 시 endpoint/body 무시. 순차 실행, 템플릿으로 단계 간 데이터 전달.",
    )

    @model_validator(mode="after")
    def _check_action_type(self):
        if not self.endpoint and not self.steps:
            raise ValueError("endpoint 또는 steps 중 하나는 필수입니다")
        return self


# ============================================================
# schedule.create
# ============================================================


class ScheduleCreateRequest(BaseModel):
    name: str = Field(description="스케줄 이름", examples=["매일 학습 트리아지"])
    cron: str = Field(
        description="Cron 표현식 (5필드, Asia/Seoul 기준)",
        examples=["0 9 * * *", "30 18 * * 1-5"],
    )
    action: ScheduleAction = Field(description="실행할 액션 (단일 호출 또는 파이프라인)")
    enabled: bool = Field(default=True, description="활성화 여부")


@app.post(
    "/schedule.create",
    summary="스케줄 생성",
    description=(
        "Cron 기반 스케줄을 생성한다. "
        "action.endpoint로 단일 호출, action.steps로 다단계 파이프라인 실행. "
        "파이프라인: steps 순차 실행, foreach로 배열 순회, {{step_id.path}} 템플릿으로 단계 간 데이터 전달."
    ),
    openapi_extra={
        "x-side-effects": "mutates",
        "x-requires-approval": False,
    },
)
async def schedule_create(req: ScheduleCreateRequest) -> CapabilityResponse:
    try:
        CronTrigger.from_crontab(req.cron, timezone=TIMEZONE)
    except Exception as e:
        return CapabilityResponse(
            status="error", error_code="invalid_cron", message=str(e)
        )

    schedule_id = str(uuid7())

    with _lock:
        schedules = _load()
        entry = {
            "schedule_id": schedule_id,
            "name": req.name,
            "cron": req.cron,
            "action": req.action.model_dump(exclude_none=True),
            "enabled": req.enabled,
            "created_at": datetime.now().isoformat(),
            "last_run": None,
            "history": [],
        }
        schedules[schedule_id] = entry
        _save(schedules)

    if req.enabled:
        _register_job(schedule_id, req.cron)

    return CapabilityResponse(status="ok", data=entry)


# ============================================================
# schedule.list
# ============================================================


class ScheduleListRequest(BaseModel):
    enabled: bool | None = Field(default=None, description="필터: 활성화 상태")


@app.post(
    "/schedule.list",
    summary="스케줄 목록 조회",
    description="등록된 스케줄 목록을 조회한다.",
    openapi_extra={
        "x-side-effects": "read-only",
        "x-requires-approval": False,
    },
)
async def schedule_list(req: ScheduleListRequest) -> CapabilityResponse:
    schedules = _load()
    items = list(schedules.values())
    if req.enabled is not None:
        items = [s for s in items if s.get("enabled", True) == req.enabled]
    return CapabilityResponse(
        status="ok", data={"schedules": items, "count": len(items)}
    )


# ============================================================
# schedule.update
# ============================================================


class ScheduleUpdateRequest(BaseModel):
    schedule_id: str = Field(description="수정할 스케줄 ID")
    name: str | None = Field(default=None, description="스케줄 이름")
    cron: str | None = Field(default=None, description="Cron 표현식")
    action: ScheduleAction | None = Field(default=None, description="실행할 액션")
    enabled: bool | None = Field(default=None, description="활성화 여부")


@app.post(
    "/schedule.update",
    summary="스케줄 수정",
    description="기존 스케줄의 설정을 수정한다.",
    openapi_extra={
        "x-side-effects": "mutates",
        "x-requires-approval": False,
    },
)
async def schedule_update(req: ScheduleUpdateRequest) -> CapabilityResponse:
    if req.cron is not None:
        try:
            CronTrigger.from_crontab(req.cron, timezone=TIMEZONE)
        except Exception as e:
            return CapabilityResponse(
                status="error", error_code="invalid_cron", message=str(e)
            )

    with _lock:
        schedules = _load()
        s = schedules.get(req.schedule_id)
        if not s:
            return CapabilityResponse(
                status="error",
                error_code="not_found",
                message="스케줄을 찾을 수 없습니다.",
            )

        if req.name is not None:
            s["name"] = req.name
        if req.cron is not None:
            s["cron"] = req.cron
        if req.action is not None:
            s["action"] = req.action.model_dump(exclude_none=True)
        if req.enabled is not None:
            s["enabled"] = req.enabled
        _save(schedules)

    if s.get("enabled", True):
        _register_job(req.schedule_id, s["cron"])
    else:
        try:
            cron_scheduler.remove_job(req.schedule_id)
        except Exception:
            pass

    return CapabilityResponse(status="ok", data=s)


# ============================================================
# schedule.delete
# ============================================================


class ScheduleDeleteRequest(BaseModel):
    schedule_id: str = Field(description="삭제할 스케줄 ID")


@app.post(
    "/schedule.delete",
    summary="스케줄 삭제",
    description="스케줄을 삭제하고 등록된 Job을 제거한다.",
    openapi_extra={
        "x-side-effects": "mutates",
        "x-requires-approval": False,
    },
)
async def schedule_delete(req: ScheduleDeleteRequest) -> CapabilityResponse:
    with _lock:
        schedules = _load()
        s = schedules.pop(req.schedule_id, None)
        if not s:
            return CapabilityResponse(
                status="error",
                error_code="not_found",
                message="스케줄을 찾을 수 없습니다.",
            )
        _save(schedules)

    try:
        cron_scheduler.remove_job(req.schedule_id)
    except Exception:
        pass

    return CapabilityResponse(status="ok", data={"deleted": req.schedule_id})


# ============================================================
# schedule.run
# ============================================================


class ScheduleRunRequest(BaseModel):
    schedule_id: str = Field(description="즉시 실행할 스케줄 ID")


@app.post(
    "/schedule.run",
    summary="스케줄 즉시 실행",
    description="스케줄을 즉시 한 번 실행한다. enabled 상태와 무관하게 실행.",
    openapi_extra={
        "x-side-effects": "external",
        "x-requires-approval": False,
    },
)
async def schedule_run(req: ScheduleRunRequest) -> CapabilityResponse:
    schedules = _load()
    if req.schedule_id not in schedules:
        return CapabilityResponse(
            status="error",
            error_code="not_found",
            message="스케줄을 찾을 수 없습니다.",
        )

    import asyncio

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _execute_job, req.schedule_id)

    schedules = _load()
    data = schedules.get(req.schedule_id, {})
    data["run_result"] = result
    return CapabilityResponse(status="ok", data=data)


# --- Startup ---


@app.on_event("startup")
async def startup():
    schedules = _load()
    registered = 0
    for sid, s in schedules.items():
        if s.get("enabled", True):
            try:
                _register_job(sid, s["cron"])
                registered += 1
            except Exception as e:
                logger.error("Failed to register schedule %s: %s", sid, e)
    cron_scheduler.start()
    logger.info(
        "Scheduler started: %d/%d schedules registered (timezone: %s)",
        registered,
        len(schedules),
        TIMEZONE,
    )
