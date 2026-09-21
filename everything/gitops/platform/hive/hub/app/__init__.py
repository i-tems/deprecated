"""Core gateway — Signal·Action·Project·Issue + 리모트 프록시."""

from capability_framework import create_app

from .config import ACTION_DIR
from .registry import load_registry
from .proxy import setup_proxy_routes
from .auth_middleware import AuthMiddleware
from .cell_middleware import CellMiddleware
from .action_log_sql import SqlActionLogMiddleware
from .metrics import MetricsMiddleware
from .metrics import router as metrics_router
from .tracing_middleware import TracingMiddleware
from .entities import signal, action, project, issue, label, initiative, introspection, event, inbox, cell, user_settings, langfuse, worker, deployment, wake, sse, itemflow_notify, pr, bus, metric, view
from . import auth, mcp_server

# 1. Registry 로드 (환경변수에서 리모트 서비스 등록)
load_registry()

# 2. App 생성. ActionLog 는 아래 SqlActionLogMiddleware (SQL append) 로만 부착.
app = create_app(
    service_id="hub",
    version="0.3.0",
    description="Core gateway — Signal·Action·Project·Issue + 리모트 프록시",
)
# 미들웨어는 Starlette 규약에 따라 add_middleware 순서가 안→밖. 즉 마지막에 add 한
# 미들웨어가 OUTERMOST가 되어 요청 path에서 먼저 실행된다. 의존 관계:
# Metrics(최외곽) → Auth → Cell → Tracing → ActionLog(가장 안쪽) → handler.
# Metrics 가 가장 바깥이라야 status_code/지연을 전체 처리 시간으로 측정.
# Auth는 request.state.principal을 채워야 Cell이 그 cell_id를 읽을 수 있고,
# Tracing은 ActionLog/emit_event가 trace 컨텍스트를 읽을 수 있도록 미리 set.
app.add_middleware(SqlActionLogMiddleware, log_dir=ACTION_DIR)

# 2.4 Tracing 미들웨어 (W3C traceparent → request.state + ContextVar)
app.add_middleware(TracingMiddleware)

# 2.3 Cell 미들웨어 (cell_id → request.state.cell_paths)
app.add_middleware(CellMiddleware)

# 2.2 Auth 미들웨어 (caller token / console JWT / legacy internal token 검증)
app.add_middleware(AuthMiddleware)

# 2.1 Metrics 미들웨어 (capability call counter / duration — Auth 보다 바깥)
app.add_middleware(MetricsMiddleware)

# 3. 로컬 capability 라우터
app.include_router(auth.router)
app.include_router(cell.router)
app.include_router(signal.router)
app.include_router(bus.router)
app.include_router(action.router)
app.include_router(project.router)
app.include_router(issue.router)
app.include_router(label.router)
app.include_router(initiative.router)
app.include_router(introspection.router)
app.include_router(event.router)
app.include_router(inbox.router)
app.include_router(user_settings.router)
app.include_router(view.router)
app.include_router(langfuse.router)
app.include_router(worker.router)
app.include_router(deployment.router)
app.include_router(itemflow_notify.router)
app.include_router(pr.router)
app.include_router(metric.router)
app.include_router(wake.router)
app.include_router(sse.router)
app.include_router(metrics_router)

# 4. 리모트 프록시 라우트
setup_proxy_routes(app)

# 5. 후처리
introspection.set_app_ref(app)

# 6. MCP 서버 마운트 (Tier 1 메타툴 3종을 streamable HTTP로 노출)
mcp_server.set_hub_app(app)
# 6.1 자주 쓰는 capability 를 레지스트리 기반 전용 함수 툴로 동적 노출.
#     generic capability_invoke(long-tail)는 무변경 — 그 위 facade 만 추가.
#     스키마는 capability.describe 와 동일 경로로 OpenAPI 에서 동적 생성(정적 0).
mcp_server.register_facade_tools()
app.mount("/mcp", mcp_server.get_asgi_app())

import asyncio
from contextlib import asynccontextmanager
from .startup import bootstrap as _bootstrap
from . import hive_repo_route as _hive_repo_route  # noqa: F401 — git_push_router "hive-repo" 라우트 self-register
from . import cell_repo_route as _cell_repo_route  # noqa: F401 — git_push_router "cell-repo" 라우트 self-register


@asynccontextmanager
async def _lifespan(_app):
    # startup hook들을 lifespan에 통합 (lifespan_context 설정이 @app.on_event를 bypass하므로).
    # sync 핸들러(list/get/event 등)·audit append 는 anyio 기본 threadpool 에서 돈다.
    # 기본 40 토큰은 UI list_all + work_finder 버스트 동시성에 모자라 큐잉→지연을
    # 유발하므로 상향한다 (INFRA-ISSUE-276). 이벤트루프 자체는 비므로 /health 는 무관.
    import os
    import anyio
    _tokens = int(os.environ.get("HUB_THREADPOOL_TOKENS", "100"))
    anyio.to_thread.current_default_thread_limiter().total_tokens = _tokens
    # 이벤트루프 stall 진단 (INFRA-ISSUE-277) — hang 시 전체 스레드 스택 덤프.
    from . import loop_watchdog
    _wd_hb = asyncio.create_task(loop_watchdog.heartbeat())
    loop_watchdog.start_watchdog()
    _bootstrap()
    await mcp_server.start_session_manager()
    # wake_bus 는 in-process pubsub — 별도 poller lifecycle 없음.
    try:
        yield
    finally:
        _wd_hb.cancel()
        await mcp_server.stop_session_manager()


app.router.lifespan_context = _lifespan

# rebuild trigger: rename PR #456 image build miss recovery
