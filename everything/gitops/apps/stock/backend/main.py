from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


QuarterId = str  # e.g. "2023Q4", "2025H1", "20259M"
PeriodFolder = str  # e.g. "Q4", "H1", "9M"

logger = logging.getLogger("dart-web-platform")


def _sql_escape_single_quotes(s: str) -> str:
    # DuckDB SQL string literal escaping
    return s.replace("'", "''")


def _iceberg_duckdb_connection():
    """
    Create a DuckDB connection with the iceberg catalog attached via Iceberg REST.

    Why not use simple_utils.platform.duckdb.DuckDB?
      - It attaches with an empty warehouse string, which results in:
          /v1/config?warehouse=
        and fails for most REST deployments.
      - It also falls back to localhost:8181 which is not reachable from inside a container.
    """
    import duckdb

    endpoint = os.getenv("ICEBERG_REST_ENDPOINT", "http://iceberg-rest:8181").strip()
    warehouse = os.getenv("ICEBERG_WAREHOUSE", "").strip()
    if not warehouse:
        raise ValueError("ICEBERG_WAREHOUSE is empty (required to attach iceberg catalog)")

    # In-container, localhost usually isn't the host. Try a couple common alternatives.
    endpoints_to_try: list[str] = []
    if endpoint:
        endpoints_to_try.append(endpoint)
    if endpoint == "http://iceberg-rest:8181":
        endpoints_to_try += ["http://host.docker.internal:8181"]

    last_exc: Exception | None = None
    for ep in endpoints_to_try:
        try:
            conn = duckdb.connect()
            conn.execute("INSTALL iceberg; LOAD iceberg;")
            wh = _sql_escape_single_quotes(warehouse)
            epp = _sql_escape_single_quotes(ep)
            conn.execute(
                f"""
                ATTACH '{wh}' AS iceberg (
                    TYPE iceberg,
                    ENDPOINT '{epp}',
                    AUTHORIZATION_TYPE 'none'
                )
                """
            )
            return conn
        except Exception as e:
            last_exc = e
            try:
                conn.close()
            except Exception:
                pass
            continue

    raise RuntimeError(f"Failed to attach iceberg catalog (endpoint tried: {endpoints_to_try})") from last_exc


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    market_cap: int  # KRW
    corp_code: str | None = None  # e.g. "00102858" (DART corp_code)
    currency: str = "KRW"
    unit: str = "KRW"


def _seed_int(s: str) -> int:
    # deterministic "random-ish" seed per ticker
    acc = 0
    for ch in s:
        acc = (acc * 131 + ord(ch)) % 10_000_000
    return acc


def _fmt_quarter_label(qid: QuarterId) -> str:
    # "2023Q4" -> "2023 Q4"; "2025H1" -> "2025 H1"; "20259M" -> "2025 9M"
    try:
        year = int(qid[:4])
        period = qid[4:]
        if period:
            return f"{year} {period}"
    except Exception:
        pass
    return qid.replace("Q", " Q")


def _period_rank(period: str) -> int:
    """
    Best-effort ordering across common reporting periods.
    Lower means earlier within the same year.
    """
    p = (period or "").upper()
    if p in ("Q1",):
        return 1
    if p in ("Q2", "H1"):
        return 2
    if p in ("Q3", "9M"):
        return 3
    if p in ("Q4", "FY", "Y", "12M"):
        return 4
    return 99


def _parse_json_maybe_double_encoded(val: Any) -> dict[str, Any]:
    """
    DuckDB might return parsed_json as:
      - dict (already parsed)
      - JSON string (e.g. '{"a":1}')
      - double-encoded JSON string (e.g. '"{\\"a\\":1}"')
    Normalize to dict.
    """
    if isinstance(val, dict):
        return val
    if val is None:
        raise ValueError("parsed_json is null")
    if not isinstance(val, str):
        raise ValueError(f"parsed_json must be str/dict, got {type(val)}")
    obj: Any = json.loads(val)
    if isinstance(obj, str):
        obj = json.loads(obj)
    if not isinstance(obj, dict):
        raise ValueError(f"parsed_json decoded to non-dict: {type(obj)}")
    return obj


def _pct_change(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100.0


DEFAULT_COMPANIES: list[Company] = [
    Company(ticker="005930", name="Samsung Electronics", market_cap=420_000_000_000_000),
    Company(ticker="000660", name="SK hynix", market_cap=110_000_000_000_000),
    Company(ticker="035420", name="NAVER", market_cap=32_000_000_000_000),
    Company(ticker="051910", name="LG Chem", market_cap=40_000_000_000_000),
]


def _load_kospi200_companies() -> list[Company]:
    """
    Load KOSPI200 company list from iceberg-backed DuckDB table.
    Falls back to DEFAULT_COMPANIES if the environment doesn't have the catalog attached.
    """
    try:
        con = _iceberg_duckdb_connection()
        # corp_code column may or may not exist depending on environment/schema.
        # Try the richer query first; fall back to minimal shape.
        try:
            df = con.sql(
                """
                WITH ranked AS (
                  SELECT
                    stock_code,
                    corp_code,
                    corp_name,
                    market_cap,
                    modify_date,
                    ROW_NUMBER() OVER (
                      PARTITION BY stock_code
                      ORDER BY modify_date DESC
                    ) AS rn
                  FROM iceberg.stock.dart_corp
                  WHERE is_k200 = TRUE
                    AND stock_code IS NOT NULL
                    AND stock_code <> ''
                )
                SELECT stock_code, corp_code, corp_name, market_cap
                FROM ranked
                WHERE rn = 1
                ORDER BY market_cap DESC NULLS LAST
                """
            ).df()
        except Exception:
            df = con.sql(
                """
                WITH ranked AS (
                  SELECT
                    stock_code,
                    corp_name,
                    market_cap,
                    modify_date,
                    ROW_NUMBER() OVER (
                      PARTITION BY stock_code
                      ORDER BY modify_date DESC
                    ) AS rn
                  FROM iceberg.stock.dart_corp
                  WHERE is_k200 = TRUE
                    AND stock_code IS NOT NULL
                    AND stock_code <> ''
                )
                SELECT stock_code, corp_name, market_cap
                FROM ranked
                WHERE rn = 1
                ORDER BY market_cap DESC NULLS LAST
                """
            ).df()

        out: list[Company] = []
        for row in df.itertuples(index=False):
            ticker = str(row.stock_code).zfill(6)
            name = str(row.corp_name)
            mcap = int(row.market_cap) if row.market_cap is not None else 0
            corp_code = getattr(row, "corp_code", None)
            if corp_code is not None:
                corp_code = str(corp_code).zfill(8)
            out.append(Company(ticker=ticker, name=name, market_cap=mcap, corp_code=corp_code))
        return out or DEFAULT_COMPANIES
    except Exception:
        logger.warning("Failed to load companies from iceberg; falling back to DEFAULT_COMPANIES", exc_info=True)
        return DEFAULT_COMPANIES


COMPANIES: list[Company] = _load_kospi200_companies()

def _digits_only(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def _resolve_corp_code(ticker: str) -> str:
    """
    Resolve DART corp_code for a given stock ticker.
    Prefers the preloaded company list; falls back to querying the catalog if available.
    """
    t = _digits_only(ticker).zfill(6)
    company = next((c for c in COMPANIES if c.ticker == t), None)
    if company and company.corp_code:
        return company.corp_code

    # Optional fallback: lookup via DuckDB if present.
    try:
        con = _iceberg_duckdb_connection()
        df = con.sql(
            f"""
            SELECT corp_code
            FROM iceberg.stock.dart_corp
            WHERE stock_code = '{t}'
              AND corp_code IS NOT NULL
              AND corp_code <> ''
            ORDER BY modify_date DESC
            LIMIT 1
            """
        ).df()
        if len(df) == 1 and df.iloc[0]["corp_code"] is not None:
            return str(df.iloc[0]["corp_code"]).zfill(8)
    except Exception:
        logger.warning("Failed to resolve corp_code via iceberg; will return 404", exc_info=True)
        pass

    raise HTTPException(status_code=404, detail="corp_code mapping not found for ticker")


def _parsed_sofc_base_dir() -> Path:
    """
    Base directory for parsed 'state of comprehensive income' JSONs.
    Default matches the user's sample path under ~.
    """
    p = os.getenv(
        "DART_PARSED_STATE_OF_COMPREHENSIVE_INCOME_BASE",
        "~/storage/data-product/stock/dart/parsed_state_of_comprehensive_income",
    )
    return Path(p).expanduser()


def _load_parsed_sofc_json(corp_code: str, year: int, period: PeriodFolder) -> tuple[str, dict[str, Any], str | None]:
    """
    Load parsed 'state of comprehensive income' JSON.

    Primary source (preferred):
      iceberg.stock.llm_parsed_comprehensive_income_statement
        company_code, year, ytd, parsed_json, receipt_id

    Fallback source (legacy):
      {BASE}/{corp_code}/{year}/{Qx}/{year}{Qx}.json
    """
    cc = _digits_only(corp_code).zfill(8)

    # 1) Iceberg source
    try:
        con = _iceberg_duckdb_connection()
        df = con.sql(
            f"""
            SELECT parsed_json, receipt_id
            FROM iceberg.stock.llm_parsed_comprehensive_income_statement
            WHERE company_code = '{cc}'
              AND year = {int(year)}
              AND ytd = '{period}'
            ORDER BY receipt_id DESC
            LIMIT 1
            """
        ).df()
        if len(df) == 1:
            parsed = _parse_json_maybe_double_encoded(df.iloc[0]["parsed_json"])
            rid = df.iloc[0]["receipt_id"]
            receipt_id = str(rid) if rid is not None else None
            return "iceberg.stock.llm_parsed_comprehensive_income_statement", parsed, receipt_id
    except Exception:
        logger.warning("Failed to load parsed SOFC JSON from iceberg; falling back to filesystem", exc_info=True)
        # fall back to legacy filesystem source
        pass

    # 2) Legacy filesystem source (only supports Q1..Q4)
    base = _parsed_sofc_base_dir()
    file_path = base / cc / str(year) / period / f"{year}{period}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Parsed SOFC not found for company_code={cc}, year={year}, period={period}")
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read/parse JSON: {e}")
    return str(file_path), payload, None


def _list_available_parsed_sofc_items(corp_code: str) -> list[dict[str, Any]]:
    """
    Returns items in the shape:
      { id: "2025H1", year: 2025, quarter: "H1", sourcePath: "...", receiptId?: "..." }
    Note: the key is still named "quarter" for frontend compatibility; it may contain YTD values like H1/9M.
    """
    cc = _digits_only(corp_code).zfill(8)

    # 1) Iceberg source
    try:
        con = _iceberg_duckdb_connection()
        df = con.sql(
            f"""
            WITH ranked AS (
              SELECT
                year,
                ytd,
                receipt_id,
                ROW_NUMBER() OVER (
                  PARTITION BY company_code, year, ytd
                  ORDER BY receipt_id DESC
                ) AS rn
              FROM iceberg.stock.llm_parsed_comprehensive_income_statement
              WHERE company_code = '{cc}'
            )
            SELECT year, ytd, receipt_id
            FROM ranked
            WHERE rn = 1
            """
        ).df()
        items: list[dict[str, Any]] = []
        for row in df.itertuples(index=False):
            year = int(row.year)
            period = str(row.ytd)
            rid = getattr(row, "receipt_id", None)
            items.append(
                {
                    "id": f"{year}{period}",
                    "year": year,
                    "quarter": period,
                    "sourcePath": "iceberg.stock.llm_parsed_comprehensive_income_statement",
                    "receiptId": str(rid) if rid is not None else None,
                }
            )
        items = sorted(items, key=lambda it: (int(it["year"]), _period_rank(str(it["quarter"])), str(it["quarter"])))
        return items
    except Exception:
        logger.warning("Failed to list available parsed SOFC items from iceberg; falling back to filesystem", exc_info=True)
        # fall back to legacy filesystem source
        pass

    # 2) Legacy filesystem source
    base = _parsed_sofc_base_dir() / cc
    if not base.exists():
        return []
    items2: list[dict[str, Any]] = []
    for year_dir in sorted([p for p in base.iterdir() if p.is_dir() and p.name.isdigit()], key=lambda p: p.name):
        year = int(year_dir.name)
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            fp = year_dir / q / f"{year}{q}.json"
            if fp.exists():
                items2.append({"id": f"{year}{q}", "year": year, "quarter": q, "sourcePath": str(fp)})
    return items2


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except Exception as e:
        raise ValueError(f"Invalid number: {x}") from e


def _sofc_extract_kpis(sofc: dict[str, Any]) -> tuple[float, float, float]:
    s1 = sofc.get("stage_1_operating") or {}
    s3 = sofc.get("stage_3_tax") or {}
    revenue = _to_float(((s1.get("revenue") or {}).get("value")))
    op_income = _to_float(((s1.get("operating_income") or {}).get("value")))
    net_income = _to_float(((s3.get("net_income") or {}).get("value")))
    return revenue, op_income, net_income


def _sofc_to_sankey(sofc: dict[str, Any]) -> dict[str, Any]:
    """
    Convert parsed 'state of comprehensive income' JSON to a sankey graph.
    All values are derived from the JSON (no synthetic generation).
    """
    s1 = sofc.get("stage_1_operating") or {}
    s2 = sofc.get("stage_2_non_operating") or {}
    s3 = sofc.get("stage_3_tax") or {}

    revenue = _to_float(((s1.get("revenue") or {}).get("value")))
    cogs = abs(_to_float(((s1.get("cost_of_sales") or {}).get("value"))))
    gross = _to_float(((s1.get("gross_profit") or {}).get("value")))
    op_income = _to_float(((s1.get("operating_income") or {}).get("value")))

    opex_items = s1.get("operating_expenses") if isinstance(s1.get("operating_expenses"), list) else []
    inflows = s2.get("inflows") if isinstance(s2.get("inflows"), list) else []
    outflows = s2.get("outflows") if isinstance(s2.get("outflows"), list) else []

    tax = abs(_to_float(((s3.get("tax_expense") or {}).get("value"))))
    net = _to_float(((s3.get("net_income") or {}).get("value")))

    def _id(prefix: str, idx: Any, fallback_i: int) -> str:
        try:
            return f"{prefix}_{int(idx)}"
        except Exception:
            return f"{prefix}_{fallback_i}"

    norm_opex = [
        {"id": _id("opex", (it or {}).get("index"), i), "label": (it or {}).get("label") or "판매비와관리비", "value": abs(_to_float((it or {}).get("value")))}
        for i, it in enumerate(opex_items)
    ]
    norm_in = [
        {"id": _id("in", (it or {}).get("index"), i), "label": (it or {}).get("label") or "기타수익", "value": abs(_to_float((it or {}).get("value")))}
        for i, it in enumerate(inflows)
    ]
    norm_out = [
        {"id": _id("out", (it or {}).get("index"), i), "label": (it or {}).get("label") or "기타비용", "value": abs(_to_float((it or {}).get("value")))}
        for i, it in enumerate(outflows)
    ]

    nodes: list[dict[str, Any]] = [
        {"id": "rev", "label": ((s1.get("revenue") or {}).get("label") or "매출액"), "group": "total", "colorKey": "rev"},
        {"id": "cogs", "label": ((s1.get("cost_of_sales") or {}).get("label") or "매출원가"), "group": "expense", "colorKey": "exp"},
        {"id": "gross", "label": ((s1.get("gross_profit") or {}).get("label") or "매출총이익"), "group": "profit", "colorKey": "profit"},
        {"id": "op", "label": ((s1.get("operating_income") or {}).get("label") or "영업이익"), "group": "profit", "colorKey": "profit"},
        {"id": "pretax", "label": ((s2.get("pre_tax_income") or {}).get("label") or "법인세비용차감전순이익"), "group": "profit", "colorKey": "profit"},
        {"id": "tax", "label": ((s3.get("tax_expense") or {}).get("label") or "법인세비용"), "group": "expense", "colorKey": "exp"},
        {"id": "net", "label": ((s3.get("net_income") or {}).get("label") or "당기순이익"), "group": "profit", "colorKey": "profit"},
    ]
    nodes += [{"id": it["id"], "label": it["label"], "group": "expense", "colorKey": "exp"} for it in norm_opex]
    nodes += [{"id": it["id"], "label": it["label"], "group": "inflow", "colorKey": "seg"} for it in norm_in]
    nodes += [{"id": it["id"], "label": it["label"], "group": "expense", "colorKey": "exp"} for it in norm_out]

    links: list[dict[str, Any]] = []
    if revenue > 0:
        if cogs > 0:
            links.append({"source": "rev", "target": "cogs", "value": cogs})
        if gross > 0:
            links.append({"source": "rev", "target": "gross", "value": gross})
    for it in norm_opex:
        if it["value"] > 0:
            links.append({"source": "gross", "target": it["id"], "value": it["value"]})
    if op_income > 0:
        links.append({"source": "gross", "target": "op", "value": op_income})

    out_total = sum(it["value"] for it in norm_out)
    op_remaining = max(0.0, op_income - out_total)
    for it in norm_out:
        if it["value"] > 0:
            links.append({"source": "op", "target": it["id"], "value": it["value"]})
    if op_remaining > 0:
        links.append({"source": "op", "target": "pretax", "value": op_remaining})
    for it in norm_in:
        if it["value"] > 0:
            links.append({"source": it["id"], "target": "pretax", "value": it["value"]})

    if tax > 0:
        links.append({"source": "pretax", "target": "tax", "value": tax})
    if net > 0:
        links.append({"source": "pretax", "target": "net", "value": net})

    return {"nodes": nodes, "links": links}


app = FastAPI(title="DART Web Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@app.get("/companies")
def list_companies() -> dict[str, Any]:
    items = sorted(COMPANIES, key=lambda c: c.market_cap, reverse=True)
    return {
        "items": [
            {
                "ticker": c.ticker,
                "name": c.name,
                "marketCap": c.market_cap,
                "corpCode": c.corp_code,
                "currency": c.currency,
                "unit": c.unit,
            }
            for c in items
        ]
    }


@app.get("/companies/{ticker}")
def get_company(ticker: str) -> dict[str, Any]:
    company = next((c for c in COMPANIES if c.ticker == ticker), None)
    if not company:
        raise HTTPException(status_code=404, detail="Unknown ticker")
    return {
        "ticker": company.ticker,
        "name": company.name,
        "marketCap": company.market_cap,
        "corpCode": company.corp_code,
        "currency": company.currency,
        "unit": company.unit,
    }


@app.get("/companies/{ticker}/quarters")
def list_company_quarters(ticker: str) -> dict[str, Any]:
    cc = _resolve_corp_code(ticker)
    items = _list_available_parsed_sofc_items(cc)
    if not items:
        raise HTTPException(status_code=404, detail="No quarter data available for this company")
    qs = [it["id"] for it in items]
    return {"ticker": _digits_only(ticker).zfill(6), "quarters": [{"id": q, "label": _fmt_quarter_label(q)} for q in qs]}


@app.get("/companies/{ticker}/timeseries")
def get_company_timeseries(
    ticker: str,
    metrics: list[str] = Query(default=["revenue", "op_income", "net_income"]),
) -> dict[str, Any]:
    cc = _resolve_corp_code(ticker)
    items = _list_available_parsed_sofc_items(cc)
    if not items:
        raise HTTPException(status_code=404, detail="No timeseries data available for this company")

    wanted = set(metrics)
    out: dict[str, Any] = {"ticker": _digits_only(ticker).zfill(6), "series": {}}
    for m in ["revenue", "op_income", "net_income"]:
        if m in wanted:
            out["series"][m] = []

    for it in items:
        year = int(it["year"])
        q = str(it["quarter"])
        _, sofc, _ = _load_parsed_sofc_json(cc, year, q)
        revenue, op_income, net_income = _sofc_extract_kpis(sofc)
        qid = it["id"]
        if "revenue" in out["series"]:
            out["series"]["revenue"].append({"quarter": qid, "value": revenue})
        if "op_income" in out["series"]:
            out["series"]["op_income"].append({"quarter": qid, "value": op_income})
        if "net_income" in out["series"]:
            out["series"]["net_income"].append({"quarter": qid, "value": net_income})

    def _qid_key(qid: str) -> tuple[int, int, str]:
        try:
            year = int(qid[:4])
            period = qid[4:]
            return (year, _period_rank(period), period)
        except Exception:
            return (0, 99, qid)

    # ensure stable order (supports Q1..Q4 and YTD like H1/9M)
    for m in out["series"].keys():
        out["series"][m] = sorted(out["series"][m], key=lambda p: _qid_key(str(p["quarter"])))
    return out


@app.get("/companies/{ticker}/quarter/{quarter}")
def get_company_quarter(
    ticker: str,
    quarter: QuarterId,
    mode: Literal["absolute", "ratio"] = "absolute",
    topN: int = 12,
    otherThreshold: float = 0.03,
) -> dict[str, Any]:
    """
    Returns a single-quarter payload for the detail page.
    The mode/topN/otherThreshold params are accepted for compatibility with UI,
    but the server currently returns the base (absolute) graph and leaves
    aggregation/re-scaling to the frontend.
    """
    cc = _resolve_corp_code(ticker)
    items = _list_available_parsed_sofc_items(cc)
    qids = [it["id"] for it in items]

    # Ensure ordering supports both quarterly and YTD ids.
    def _qid_key(qid: str) -> tuple[int, int, str]:
        try:
            year = int(qid[:4])
            period = qid[4:]
            return (year, _period_rank(period), period)
        except Exception:
            return (0, 99, qid)

    qids_sorted = sorted(qids, key=_qid_key)
    if quarter not in qids_sorted:
        raise HTTPException(status_code=404, detail="Unknown quarter")
    idx = qids_sorted.index(quarter)
    prev_qid = qids_sorted[idx - 1] if idx - 1 >= 0 else None

    # YoY for same period (e.g. 2025H1 -> 2024H1) if present.
    try:
        cur_year = int(quarter[:4])
        cur_period = quarter[4:]
        yoy_qid = f"{cur_year - 1}{cur_period}" if cur_period else None
    except Exception:
        yoy_qid = None
    if yoy_qid not in qids_sorted:
        yoy_qid = None

    def _load_by_qid(qid: str | None) -> tuple[float, float, float] | None:
        if qid is None:
            return None
        try:
            year = int(qid[:4])
            q = qid[4:]  # e.g. "Q4", "H1", "9M"
            if not q:
                return None
        except Exception:
            return None
        _, sofc, _ = _load_parsed_sofc_json(cc, year, q)
        return _sofc_extract_kpis(sofc)

    cur = _load_by_qid(quarter)
    if cur is None:
        raise HTTPException(status_code=500, detail="Failed to load quarter data")
    revenue, op_income, net_income = cur
    prev = _load_by_qid(prev_qid)
    yoy = _load_by_qid(yoy_qid)

    rev_prev = prev[0] if prev else None
    rev_yoy = yoy[0] if yoy else None
    op_prev = prev[1] if prev else None
    op_yoy = yoy[1] if yoy else None
    net_prev = prev[2] if prev else None
    net_yoy = yoy[2] if yoy else None

    # load sankey from JSON
    year = int(quarter[:4])
    q = quarter[4:]
    _, sofc, _ = _load_parsed_sofc_json(cc, year, q)
    sankey = _sofc_to_sankey(sofc)

    return {
        "ticker": _digits_only(ticker).zfill(6),
        "quarter": quarter,
        "label": _fmt_quarter_label(quarter),
        "currency": "KRW",
        "unit": "KRW",
        "kpi": {
            "revenue": {"value": revenue, "qoqPct": _pct_change(revenue, rev_prev), "yoyPct": _pct_change(revenue, rev_yoy)},
            "opIncome": {"value": op_income, "qoqPct": _pct_change(op_income, op_prev), "yoyPct": _pct_change(op_income, op_yoy)},
            "netIncome": {"value": net_income, "qoqPct": _pct_change(net_income, net_prev), "yoyPct": _pct_change(net_income, net_yoy)},
        },
        "sankey": sankey,
        "serverEcho": {"mode": mode, "topN": topN, "otherThreshold": otherThreshold},
    }


@app.get("/companies/{ticker}/dart/parsed_state_of_comprehensive_income/{year}/{quarter}")
def get_parsed_state_of_comprehensive_income(
    ticker: str,
    year: int,
    quarter: str,
    corpCode: str | None = None,
) -> dict[str, Any]:
    """
    Reads parsed DART 'state of comprehensive income' JSON.
    Primary source is iceberg table:
      iceberg.stock.llm_parsed_comprehensive_income_statement
    where quarter param maps to the table's ytd field (e.g. Q1/Q2/Q3/Q4 or H1/9M/FY).
    """
    cc = _digits_only(corpCode).zfill(8) if corpCode else _resolve_corp_code(ticker)
    source_path, payload, receipt_id = _load_parsed_sofc_json(cc, year, quarter)
    return {
        "ticker": _digits_only(ticker).zfill(6),
        "corpCode": cc,
        "year": year,
        "quarter": quarter,
        "sourcePath": str(source_path),
        "receiptId": receipt_id,
        "data": payload,
    }


@app.get("/companies/{ticker}/dart/parsed_state_of_comprehensive_income/available")
def list_available_parsed_state_of_comprehensive_income(
    ticker: str,
    corpCode: str | None = None,
) -> dict[str, Any]:
    """
    Lists available (year, quarter) pairs for which the parsed JSON exists for this company.
    Scans only within this corp_code directory.
    """
    cc = _digits_only(corpCode).zfill(8) if corpCode else _resolve_corp_code(ticker)
    items = _list_available_parsed_sofc_items(cc)
    if not items:
        raise HTTPException(status_code=404, detail="No parsed SOFC items available for this company")
    return {"ticker": _digits_only(ticker).zfill(6), "corpCode": cc, "items": items}

