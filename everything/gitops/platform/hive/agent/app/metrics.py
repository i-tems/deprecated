"""Prometheus metrics — agent-loop cycle + worker spawn 통계.

main loop 프로세스에서 prometheus_client.start_http_server(8002) 로 자체 HTTP
server 를 별도 thread 에 띄운다 (uvicorn :8001 과 분리 — multiprocess collector
부담 회피). PodMonitor 가 :8002/metrics 를 scrape.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server


METRICS_PORT = 8002


hive_agent_cycle_total = Counter(
    "hive_agent_cycle_total",
    "Agent loop cycle 총수 (result: ok / error).",
    labelnames=("result",),
)

hive_agent_cycle_duration_seconds = Histogram(
    "hive_agent_cycle_duration_seconds",
    "Agent loop 한 cycle 처리 지연 (s).",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

hive_agent_spawn_total = Counter(
    "hive_agent_spawn_total",
    "Agent loop 가 spawn 한 worker Job 총수.",
    labelnames=("action_type",),
)

hive_agent_reap_total = Counter(
    "hive_agent_reap_total",
    "Agent loop 가 reap (finished K8s Job 정리) 한 총수.",
)

hive_agent_active_jobs = Gauge(
    "hive_agent_active_jobs",
    "현재 살아있는 worker K8s Job 수.",
)


def start_metrics_server() -> None:
    """별도 thread 에서 Prometheus HTTP server 띄운다. main loop 의 in-process 카운터를
    그대로 노출 — multiprocess collector 불필요."""
    start_http_server(METRICS_PORT)
