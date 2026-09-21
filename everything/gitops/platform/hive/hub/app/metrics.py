"""Prometheus metrics — hub capability call + worker 통계.

Counter / Histogram / Gauge 정의 + /metrics 엔드포인트 + Starlette 미들웨어.

PodMonitor (manifests/podmonitor.yaml) 가 :8000/metrics 를 scrape 한다.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.requests import Request


# /metrics 자체 스크레이프는 카운트하지 않음. /health 와 docs 류도 제외.
# /sse.subscribe 는 시간 단위로 열려 있는 스트림이라 capability duration
# 히스토그램을 오염시킨다 — skip.
_SKIP_PATHS = {"/metrics", "/health", "/openapi.json", "/docs", "/redoc", "/sse.subscribe"}


hive_capability_total = Counter(
    "hive_capability_total",
    "Hub capability 호출 총수 (status_code, principal_type 별).",
    labelnames=("capability", "status", "principal_type"),
)

hive_capability_duration_seconds = Histogram(
    "hive_capability_duration_seconds",
    "Hub capability 호출 처리 지연 (s).",
    labelnames=("capability",),
    # capability 는 file IO + 다른 service 호출이라 ms~s 분포.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

hive_active_workers = Gauge(
    "hive_active_workers",
    "현재 heartbeat 가 유효한 활성 worker pod 수.",
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """capability path 별 호출 count + duration 측정."""

    async def dispatch(self, request: "Request", call_next):
        path = request.url.path
        if path in _SKIP_PATHS:
            return await call_next(request)
        start = time.monotonic()
        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            duration = time.monotonic() - start
            capability = path.lstrip("/") or "root"
            hive_capability_total.labels(
                capability=capability, status="500", principal_type="unknown",
            ).inc()
            hive_capability_duration_seconds.labels(capability=capability).observe(duration)
            raise
        duration = time.monotonic() - start
        capability = path.lstrip("/") or "root"
        principal = getattr(request.state, "principal", None)
        ptype = getattr(principal, "type", None) or "anonymous"
        hive_capability_total.labels(
            capability=capability, status=status, principal_type=ptype,
        ).inc()
        hive_capability_duration_seconds.labels(capability=capability).observe(duration)
        return response


router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape 엔드포인트. text/plain (OpenMetrics 호환).

    active_workers gauge 는 scrape 시점에 heartbeat TTL 통과 항목 수로 갱신
    (worker_heartbeats SQL 공유 저장 — INFRA-ISSUE-284).
    """
    from datetime import datetime, timezone, timedelta
    from .entities.worker import TTL_SECONDS
    from .storage.sql import list_heartbeats
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=TTL_SECONDS)).isoformat()
    hive_active_workers.set(len(list_heartbeats(cutoff_iso)))
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
