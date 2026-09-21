"""Query capability — Kyuubi REST API thin wrapper.

Iceberg(Polaris) 테이블을 SQL 로 read. Spark engine 은 Kyuubi 가 띄우고 maintain;
이 서비스는 그 REST API 위 sync 호출 wrapper. Kyuubi 의 async operation 모델을
short poll loop 로 sync 단일 호출에 묶는다.

엔드포인트:
- query.sql(sql, limit) — SELECT 결과 (rows + schema + ms)
- query.tables(namespace?, catalog?) — namespace/table 목록
- query.describe(table) — DESCRIBE TABLE EXTENDED 결과
"""

import asyncio
import logging
import os
import time

import httpx
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse, create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("query")

# ── Config ───────────────────────────────────────────────────────────────────

KYUUBI_REST_URL = os.environ.get(
    "KYUUBI_REST_URL", "http://kyuubi.kyuubi.svc.cluster.local:10099",
).rstrip("/")
DEFAULT_CATALOG = os.environ.get("DEFAULT_CATALOG", "polaris")
DEFAULT_LIMIT = int(os.environ.get("DEFAULT_LIMIT", "1000"))
MAX_LIMIT = int(os.environ.get("MAX_LIMIT", "10000"))
POLL_INTERVAL_S = float(os.environ.get("POLL_INTERVAL_S", "0.5"))
POLL_TIMEOUT_S = float(os.environ.get("POLL_TIMEOUT_S", "60"))
HTTP_TIMEOUT_S = float(os.environ.get("HTTP_TIMEOUT_S", "30"))

app = create_app(
    service_id="query",
    version="0.1.0",
    description="Iceberg(Polaris) SQL read via Kyuubi — query.sql / query.tables / query.describe.",
)


# ── Models ───────────────────────────────────────────────────────────────────


class SqlRequest(BaseModel):
    sql: str = Field(..., description="실행할 SQL. read 가정 (DDL/DML 은 OOS).")
    limit: int | None = Field(
        default=None, description=f"최대 row 수 (기본 {DEFAULT_LIMIT}, 상한 {MAX_LIMIT}).",
    )


class TablesRequest(BaseModel):
    catalog: str = Field(default=DEFAULT_CATALOG)
    namespace: str | None = Field(
        default=None, description="namespace 필터. None=모든 namespace 목록.",
    )


class DescribeRequest(BaseModel):
    table: str = Field(..., description="FQN — 예: 'polaris.news.news_hada'.")


# ── Kyuubi REST helpers ──────────────────────────────────────────────────────


async def _run_statement(sql: str, *, max_rows: int) -> dict:
    """SQL 실행 → schema + rows + ms. session 은 호출 단위로 열고 닫는다.

    engine.share.level=SERVER 라 engine 자체는 warm 유지; session 만 새로 생성.
    """
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        # 1) session
        sresp = await client.post(
            f"{KYUUBI_REST_URL}/api/v1/sessions", json={"configs": {}},
        )
        sresp.raise_for_status()
        session_id = sresp.json()["identifier"]
        try:
            # 2) submit
            oresp = await client.post(
                f"{KYUUBI_REST_URL}/api/v1/sessions/{session_id}/operations/statement",
                json={"statement": sql, "runAsync": True},
            )
            oresp.raise_for_status()
            op_id = oresp.json()["identifier"]
            # 3) poll
            deadline = time.monotonic() + POLL_TIMEOUT_S
            while True:
                eresp = await client.get(
                    f"{KYUUBI_REST_URL}/api/v1/operations/{op_id}/event",
                )
                eresp.raise_for_status()
                event = eresp.json()
                # Kyuubi 1.10 의 state 값은 `FINISHED_STATE` 처럼 `_STATE` suffix 가
                # 붙는다 (TOperationState enum). suffix 제거 후 비교.
                state = str(event.get("state", "")).upper().removesuffix("_STATE")
                if state == "FINISHED":
                    break
                if state in ("ERROR", "CANCELED", "CLOSED", "TIMEDOUT", "TIMEOUT"):
                    err = event.get("exception") or event.get("errorMessage") or ""
                    raise RuntimeError(f"operation {state}: {err}")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"operation poll timeout after {POLL_TIMEOUT_S}s")
                await asyncio.sleep(POLL_INTERVAL_S)
            # 4) schema
            mresp = await client.get(
                f"{KYUUBI_REST_URL}/api/v1/operations/{op_id}/resultsetmetadata",
            )
            mresp.raise_for_status()
            schema = mresp.json().get("columns", [])
            # 5) rows
            rresp = await client.get(
                f"{KYUUBI_REST_URL}/api/v1/operations/{op_id}/rowset",
                params={"maxrows": max_rows, "fetchorientation": "FETCH_NEXT"},
            )
            rresp.raise_for_status()
            rowset = rresp.json()
            ms = int((time.monotonic() - start) * 1000)
            return {
                "rows": rowset.get("rows", []),
                "row_count": rowset.get("rowCount", 0),
                "schema": schema,
                "ms": ms,
                "engine": "spark",
            }
        finally:
            try:
                await client.delete(f"{KYUUBI_REST_URL}/api/v1/sessions/{session_id}")
            except Exception as e:
                log.warning("session close failed: %s", e)


def _classify_error(e: Exception) -> CapabilityResponse:
    if isinstance(e, TimeoutError):
        return CapabilityResponse(
            status="error", error_code="query_timeout", message=str(e),
        )
    if isinstance(e, httpx.HTTPError):
        return CapabilityResponse(
            status="error", error_code="kyuubi_unreachable", message=str(e),
        )
    return CapabilityResponse(
        status="error", error_code="query_failed", message=str(e),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.post(
    "/query.sql",
    summary="SQL 실행 (read)",
    description=(
        "Iceberg(Polaris) 테이블에 SQL 을 실행해 rows + schema 를 반환한다. "
        "DDL/DML 은 OOS — 모든 호출이 Kyuubi 서버 단일 자격으로 실행되므로 "
        "권한 분리 도입 전까지 read 만 사용한다."
    ),
    openapi_extra={"x-side-effects": "read-only", "x-requires-approval": False},
)
async def query_sql(req: SqlRequest) -> CapabilityResponse:
    sql = (req.sql or "").strip().rstrip(";")
    if not sql:
        return CapabilityResponse(
            status="error", error_code="invalid_request", message="sql is required.",
        )
    max_rows = req.limit if req.limit and req.limit > 0 else DEFAULT_LIMIT
    max_rows = min(max_rows, MAX_LIMIT)
    try:
        result = await _run_statement(sql, max_rows=max_rows)
    except Exception as e:
        return _classify_error(e)
    return CapabilityResponse(status="ok", data=result)


@app.post(
    "/query.tables",
    summary="namespace / table 목록",
    openapi_extra={"x-side-effects": "read-only", "x-requires-approval": False},
)
async def query_tables(req: TablesRequest) -> CapabilityResponse:
    if req.namespace:
        sql = f"SHOW TABLES IN {req.catalog}.{req.namespace}"
    else:
        sql = f"SHOW NAMESPACES IN {req.catalog}"
    try:
        result = await _run_statement(sql, max_rows=MAX_LIMIT)
    except Exception as e:
        return _classify_error(e)
    return CapabilityResponse(status="ok", data=result)


@app.post(
    "/query.describe",
    summary="테이블 스키마 / 메타데이터",
    openapi_extra={"x-side-effects": "read-only", "x-requires-approval": False},
)
async def query_describe(req: DescribeRequest) -> CapabilityResponse:
    table = (req.table or "").strip()
    if not table:
        return CapabilityResponse(
            status="error", error_code="invalid_request", message="table is required.",
        )
    sql = f"DESCRIBE TABLE EXTENDED {table}"
    try:
        result = await _run_statement(sql, max_rows=MAX_LIMIT)
    except Exception as e:
        return _classify_error(e)
    return CapabilityResponse(status="ok", data=result)
