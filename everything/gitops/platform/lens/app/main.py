"""lens — AI 생성 대시보드 플랫폼 (post-BI MVP).

저작시점(B) 모델: 대시보드는 에이전트 세션이 spec(JSON)으로 저작·저장하고,
이 앱은 spec 의 SQL 을 query.sql 로 실행(read-only 가드)해 렌더만 한다.
앱에 LLM/Claude 키 없음 — 생성은 이미 자격증명을 가진 에이전트 세션의 몫.
"""
import json
import os
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .hub_client import HubClient, HubError
from .sql_guard import SqlGuardError, guard_sql

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASH_DIR = pathlib.Path(os.environ.get("LENS_DASHBOARD_DIR", str(ROOT / "dashboards")))
STATIC_DIR = ROOT / "static"

app = FastAPI(title="lens", docs_url="/api/docs", redoc_url=None)
hub = HubClient()


def _load_dashboards() -> dict[str, dict]:
    """dashboards/*.json 을 매 요청 로드 (수 개 규모, freshness 우선)."""
    out: dict[str, dict] = {}
    if not DASH_DIR.is_dir():
        return out
    for p in sorted(DASH_DIR.glob("*.json")):
        try:
            spec = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        spec.setdefault("id", p.stem)
        out[spec["id"]] = spec
    return out


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/dashboards")
def list_dashboards() -> dict:
    items = [
        {
            "id": d["id"],
            "title": d.get("title", d["id"]),
            "description": d.get("description", ""),
            "panel_count": len(d.get("panels", [])),
        }
        for d in _load_dashboards().values()
    ]
    items.sort(key=lambda x: x["title"])
    return {"dashboards": items}


@app.get("/api/dashboards/{dash_id}")
def get_dashboard(dash_id: str) -> dict:
    ds = _load_dashboards()
    if dash_id not in ds:
        raise HTTPException(404, "dashboard not found")
    return ds[dash_id]


class RunRequest(BaseModel):
    sql: str
    limit: int | None = None


@app.post("/api/run")
async def run(req: RunRequest) -> dict:
    try:
        safe = guard_sql(req.sql)
    except SqlGuardError as e:
        raise HTTPException(400, f"sql rejected: {e}")
    try:
        return await hub.run_sql(safe, limit=req.limit)
    except HubError as e:
        raise HTTPException(502, f"query failed: {e}")


# SPA — /api/* 라우트가 먼저 등록되어 우선 매칭, 그 외 경로는 정적 파일.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
