"""Metric — 운영 지표 집계 (read-only).

metrics 웨어하우스 collector (cell-infra/data-product/metrics/*) 가 호출하는
일별 집계 read 표면. 이벤트 row 를 entity 별로 N+1 조회하는 대신, events·
inbox_events 를 일자×(type, principal_type, subtype) 로 server-side GROUP BY
해 반환한다. cell-scoped (X-Cell-Id).

human_attention 도메인이 첫 소비자:
- 핸드오프(AI→사람)   = type=comment, principal_type=worker, subtype in (handoff, halt)
- 사람 응답           = type=comment, principal_type=user
- inbox 적재          = inbox_events
collector 가 이 raw 집계에서 위 지표를 derive 한다 (산식은 cell 쪽에).
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from capability_framework import CapabilityResponse
from ..config import get_cell_paths
from ..db import get_engine

# 워커 세션 JSONL 루트 (NFS, hub 마운트). dir = cwd slug
# `-data-workspaces-<cell>-<entity_id>-cell`.
_WORKER_PROJECTS_ROOT = os.environ.get("CLAUDE_PROJECTS_ROOT", "/data/shared/.claude/projects")
_WS_DIR_RE = re.compile(r"^-data-workspaces-(?P<cell>[^-]+)-(?P<eid>.+)-cell$")
_KST = _dt.timezone(_dt.timedelta(hours=9))

router = APIRouter()


class EventsDailyRequest(BaseModel):
    date_from: str | None = None  # YYYY-MM-DD (inclusive)
    date_to: str | None = None    # YYYY-MM-DD (inclusive)


@router.post("/metric.events_daily", openapi_extra={"x-side-effects": "read-only"})
def events_daily(req: EventsDailyRequest, request: Request) -> CapabilityResponse:
    """events·inbox_events 일별 집계. cell-scoped.

    반환:
      events: [{ts_date, type, principal_type, subtype, n, chars}]
              chars = data.text 의 문자수 합 (사람이 읽을/쓴 분량).
      inbox:  [{ts_date, n}]
    """
    cp = get_cell_paths(request)
    params: dict = {"cid": cp.cell_id}
    where = "cell_id = :cid"
    if req.date_from:
        where += " AND ts_date >= :df"
        params["df"] = req.date_from
    if req.date_to:
        where += " AND ts_date <= :dt"
        params["dt"] = req.date_to

    ev_sql = text(
        "SELECT ts_date, type, principal_type, "
        "JSON_UNQUOTE(JSON_EXTRACT(data, '$.data.subtype')) AS subtype, "
        "COUNT(*) AS n, "
        "COALESCE(SUM(CHAR_LENGTH(JSON_UNQUOTE(JSON_EXTRACT(data, '$.data.text')))), 0) AS chars "
        f"FROM events WHERE {where} "
        "GROUP BY ts_date, type, principal_type, subtype"
    )
    ib_sql = text(
        f"SELECT ts_date, COUNT(*) AS n FROM inbox_events WHERE {where} "
        "GROUP BY ts_date"
    )
    # status 전이 to-state (lifecycle 도메인용). status_change 의 to 는
    # 레코드의 payload(data.data) 안 → $.data.to.
    tr_sql = text(
        "SELECT ts_date, entity_type, principal_type, "
        "JSON_UNQUOTE(JSON_EXTRACT(data, '$.data.to')) AS to_state, "
        "COUNT(*) AS n "
        f"FROM events WHERE {where} AND type = 'status_change' "
        "GROUP BY ts_date, entity_type, principal_type, to_state"
    )

    eng = get_engine()
    with eng.connect() as conn:
        events = [dict(r._mapping) for r in conn.execute(ev_sql, params).fetchall()]
        inbox = [dict(r._mapping) for r in conn.execute(ib_sql, params).fetchall()]
        transitions = [dict(r._mapping) for r in conn.execute(tr_sql, params).fetchall()]

    for r in events:
        r["n"] = int(r["n"])
        r["chars"] = int(r["chars"] or 0)
    for r in inbox:
        r["n"] = int(r["n"])
    for r in transitions:
        r["n"] = int(r["n"])

    return CapabilityResponse(
        status="ok",
        data={"events": events, "inbox": inbox, "transitions": transitions},
    )


class HandoffLatencyRequest(BaseModel):
    date_from: str | None = None  # YYYY-MM-DD (inclusive)
    date_to: str | None = None    # YYYY-MM-DD (inclusive)


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


@router.post("/metric.handoff_latency", openapi_extra={"x-side-effects": "read-only"})
def handoff_latency(req: HandoffLatencyRequest, request: Request) -> CapabilityResponse:
    """핸드오프(AI→사람) → 사람 첫 응답까지의 지연(초)을 일별 집계. cell-scoped.

    핸드오프 = worker comment subtype in (handoff, halt). 응답 = 같은 entity 의
    그 이후 첫 user comment. latency = 응답 ts − 핸드오프 ts (핸드오프 날짜로 귀속).
    윈도우 내 응답이 없으면 unresolved. p50/p90 은 hub 에서 계산.

    반환: [{ts_date, handoffs, resolved, latency_avg_s, latency_p50_s, latency_p90_s}]
    """
    import datetime as _dt

    cp = get_cell_paths(request)
    params: dict = {"cid": cp.cell_id}
    where = "cell_id = :cid AND type = 'comment'"
    if req.date_from:
        where += " AND ts_date >= :df"
        params["df"] = req.date_from
    if req.date_to:
        where += " AND ts_date <= :dt"
        params["dt"] = req.date_to

    sql = text(
        "SELECT entity_type, entity_id, ts, principal_type, "
        "JSON_UNQUOTE(JSON_EXTRACT(data, '$.data.subtype')) AS subtype "
        f"FROM events WHERE {where} "
        "ORDER BY entity_type, entity_id, ts"
    )
    eng = get_engine()
    with eng.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(sql, params).fetchall()]

    def _parse(ts: str):
        try:
            return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    # entity 별로 시간순 순회 — pending 핸드오프를 다음 user comment 와 페어링.
    by_day: dict[str, dict] = {}
    cur_key = None
    pending_ts = None  # 미해소 핸드오프의 (datetime, date_str)
    pending_day = None
    for r in rows:
        key = (r["entity_type"], r["entity_id"])
        if key != cur_key:
            cur_key = key
            pending_ts = None
            pending_day = None
        ts = _parse(r.get("ts") or "")
        if ts is None:
            continue
        is_handoff = r.get("principal_type") == "worker" and r.get("subtype") in ("handoff", "halt")
        is_user = r.get("principal_type") == "user"
        if is_handoff:
            # 연속 핸드오프면 가장 최근 것으로 갱신 (직전 미해소는 unresolved 로 남김 — 다음 user 가 최신 것만 해소).
            pending_ts = ts
            pending_day = ts.strftime("%Y-%m-%d")
            d = by_day.setdefault(pending_day, {"handoffs": 0, "lat": []})
            d["handoffs"] += 1
        elif is_user and pending_ts is not None:
            lat = (ts - pending_ts).total_seconds()
            if lat >= 0:
                by_day[pending_day]["lat"].append(lat)
            pending_ts = None
            pending_day = None

    out = []
    for day in sorted(by_day):
        lat = sorted(by_day[day]["lat"])
        out.append({
            "ts_date": day,
            "handoffs": by_day[day]["handoffs"],
            "resolved": len(lat),
            "latency_avg_s": round(sum(lat) / len(lat), 1) if lat else 0.0,
            "latency_p50_s": round(_percentile(lat, 0.5), 1),
            "latency_p90_s": round(_percentile(lat, 0.9), 1),
        })

    return CapabilityResponse(status="ok", data={"latency": out})


class WorkerDailyRequest(BaseModel):
    date_from: str | None = None  # YYYY-MM-DD (inclusive)
    date_to: str | None = None    # YYYY-MM-DD (inclusive)


def _worker_day(ts: str) -> str | None:
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(_KST).strftime("%Y-%m-%d")
    except Exception:
        return None


@router.post("/metric.worker_daily", openapi_extra={"x-side-effects": "read-only"})
def worker_daily(req: WorkerDailyRequest, request: Request) -> CapabilityResponse:
    """워커 세션(NFS JSONL) 의 일별×엔티티 활동 집계. cell-scoped.

    SDK 세션 JSONL 을 파싱해 (ts_date, entity_id) 별 sessions/turns/tool_calls/
    tokens_in/tokens_out/active_seconds 를 낸다 — metrics 웨어하우스의 worker
    도메인 collector 가 소비. ai_usage(Langfuse)와 보완: 여기는 세션·턴·툴콜·활성
    시간(운영 깊이)까지.

    반환: [{ts_date, entity_id, entity_type, sessions, turns, tool_calls,
            tokens_in, tokens_out, active_seconds}]
    """
    cp = get_cell_paths(request)
    cell = cp.cell_id
    df_lo = req.date_from
    df_hi = req.date_to

    # (day, entity) → 누적
    agg: dict = {}
    # (entity, sid) → [min_ts, max_ts, first_day]
    sess: dict = {}

    try:
        dirs = os.listdir(_WORKER_PROJECTS_ROOT)
    except OSError:
        dirs = []

    for d in dirs:
        m = _WS_DIR_RE.match(d)
        if not m or m.group("cell") != cell:
            continue
        eid = m.group("eid")
        etype = ("issue" if "-ISSUE-" in eid else "project" if "-PROJECT-" in eid
                 else "initiative" if "-INITIATIVE-" in eid else "other")
        for path in glob.glob(os.path.join(_WORKER_PROJECTS_ROOT, d, "*.jsonl")):
            sid = os.path.basename(path)[:-6]
            try:
                fh = open(path, encoding="utf-8", errors="ignore")
            except OSError:
                continue
            with fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    typ = o.get("type")
                    if typ not in ("user", "assistant"):
                        continue
                    day = _worker_day(o.get("timestamp") or "")
                    if not day:
                        continue
                    if df_lo and day < df_lo:
                        continue
                    if df_hi and day > df_hi:
                        continue
                    key = (day, eid, etype)
                    a = agg.setdefault(key, {"sessions": set(), "turns": 0, "tool_calls": 0,
                                             "tokens_in": 0, "tokens_out": 0})
                    a["sessions"].add(sid)
                    msg = o.get("message") or {}
                    if typ == "assistant":
                        a["turns"] += 1
                        for b in (msg.get("content") or []):
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                a["tool_calls"] += 1
                        u = msg.get("usage") or {}
                        a["tokens_in"] += (int(u.get("input_tokens") or 0)
                                           + int(u.get("cache_read_input_tokens") or 0)
                                           + int(u.get("cache_creation_input_tokens") or 0))
                        a["tokens_out"] += int(u.get("output_tokens") or 0)
                    # active span (세션 단위, 첫 메시지 day 귀속)
                    try:
                        t = _dt.datetime.fromisoformat((o.get("timestamp") or "").replace("Z", "+00:00"))
                    except Exception:
                        t = None
                    if t:
                        srec = sess.setdefault((eid, sid), [t, t, day])
                        if t < srec[0]:
                            srec[0] = t
                            srec[2] = day
                        if t > srec[1]:
                            srec[1] = t

    active_by = {}
    for (eid, _sid), (lo, hi, day) in sess.items():
        if df_lo and day < df_lo:
            continue
        if df_hi and day > df_hi:
            continue
        active_by[(day, eid)] = active_by.get((day, eid), 0.0) + (hi - lo).total_seconds()

    out = []
    for (day, eid, etype), a in sorted(agg.items()):
        out.append({
            "ts_date": day, "entity_id": eid, "entity_type": etype,
            "sessions": len(a["sessions"]), "turns": a["turns"],
            "tool_calls": a["tool_calls"], "tokens_in": a["tokens_in"],
            "tokens_out": a["tokens_out"],
            "active_seconds": round(active_by.get((day, eid), 0.0), 1),
        })
    return CapabilityResponse(status="ok", data={"workers": out})
