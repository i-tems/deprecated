"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { KpiCard } from "@/components/KpiCard";
import { SankeyChart } from "@/components/SankeyChart";
import { Sparkline } from "@/components/Sparkline";
import { ApiError, apiGetJson } from "@/lib/api";
import { formatCompactKRW } from "@/lib/format";
import type {
  Company,
  CompanyQuartersResponse,
  DartParsedSofcAvailableItem,
  DartParsedSofcAvailableResponse,
  DartParsedSofcResponse,
  QuarterPayload,
  QuarterOption,
  SankeyLink,
  SankeyNode,
  TimeSeriesPayload,
} from "@/lib/types";

type Props = { ticker: string };

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}

function formatQuarterLabel(qid: string): string {
  // "2023Q4" -> "2023 Q4"; "2025H1" -> "2025 H1"; "20259M" -> "2025 9M"
  const year = qid.slice(0, 4);
  const rest = qid.slice(4);
  if (/^\d{4}$/.test(year) && rest) return `${year} ${rest}`;
  return qid.replace("Q", " Q");
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null;
}

function toNumber(x: unknown): number {
  const n = typeof x === "number" ? x : Number(x);
  if (!Number.isFinite(n)) throw new Error(`Invalid number: ${String(x)}`);
  return n;
}

function fmtKRW(n: number): string {
  // Keep it simple + deterministic; Plotly supports HTML in labels.
  return `₩ ${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(n)}`;
}

function nodeLabel(name: string, value: number): string {
  return `<b>${name}</b><br>${fmtKRW(value)}`;
}

function profitKey(v: number): "profit_pos" | "profit_neg" {
  return v >= 0 ? "profit_pos" : "profit_neg";
}

function toParsedSofcSankey(data: unknown): { nodes: SankeyNode[]; links: SankeyLink[]; kpi: QuarterPayload["kpi"] } {
  if (!isRecord(data)) throw new Error("Invalid parsed SOFC payload shape");
  const s1 = isRecord(data.stage_1_operating) ? data.stage_1_operating : null;
  const s2 = isRecord(data.stage_2_non_operating) ? data.stage_2_non_operating : null;
  const s3 = isRecord(data.stage_3_tax) ? data.stage_3_tax : null;
  if (!s1 || !s2 || !s3) throw new Error("Invalid parsed SOFC payload shape");

  const revenue = toNumber((isRecord(s1.revenue) ? s1.revenue.value : undefined) ?? undefined);
  const cogs = Math.abs(toNumber((isRecord(s1.cost_of_sales) ? s1.cost_of_sales.value : undefined) ?? undefined));
  const gross = toNumber((isRecord(s1.gross_profit) ? s1.gross_profit.value : undefined) ?? undefined);
  const opIncome = toNumber((isRecord(s1.operating_income) ? s1.operating_income.value : undefined) ?? undefined);

  const opexItemsRaw = Array.isArray(s1.operating_expenses) ? s1.operating_expenses : [];
  const inflowsRaw = Array.isArray(s2.inflows) ? s2.inflows : [];
  const outflowsRaw = Array.isArray(s2.outflows) ? s2.outflows : [];

  // Used only for labeling; flows are built bottom-up.
  const pretax = toNumber((isRecord(s2.pre_tax_income) ? s2.pre_tax_income.value : undefined) ?? undefined);
  const tax = Math.abs(toNumber((isRecord(s3.tax_expense) ? s3.tax_expense.value : undefined) ?? undefined));
  const net = toNumber((isRecord(s3.net_income) ? s3.net_income.value : undefined) ?? undefined);

  const opexItems = opexItemsRaw.map((it: unknown, i: number) => {
    const r = isRecord(it) ? it : {};
    return {
      id: `opex_${(r.index as string | number | undefined) ?? i}`,
      label: (typeof r.label === "string" ? r.label : undefined) ?? "판매비와관리비",
      value: Math.abs(toNumber(r.value)),
    };
  });
  const inflows = inflowsRaw.map((it: unknown, i: number) => {
    const r = isRecord(it) ? it : {};
    return {
      id: `in_${(r.index as string | number | undefined) ?? i}`,
      label: (typeof r.label === "string" ? r.label : undefined) ?? "기타수익",
      value: Math.abs(toNumber(r.value)),
    };
  });
  const outflows = outflowsRaw.map((it: unknown, i: number) => {
    const r = isRecord(it) ? it : {};
    return {
      id: `out_${(r.index as string | number | undefined) ?? i}`,
      label: (typeof r.label === "string" ? r.label : undefined) ?? "기타비용",
      value: Math.abs(toNumber(r.value)),
    };
  });

  const nodes: SankeyNode[] = [
    {
      id: "rev",
      label: nodeLabel(
        (isRecord(s1.revenue) && typeof s1.revenue.label === "string" ? s1.revenue.label : undefined) ?? "매출액",
        revenue,
      ),
      group: "total",
      colorKey: "rev",
    },
    {
      id: "cogs",
      label: nodeLabel(
        (isRecord(s1.cost_of_sales) && typeof s1.cost_of_sales.label === "string" ? s1.cost_of_sales.label : undefined) ??
          "매출원가",
        cogs,
      ),
      group: "expense",
      colorKey: "exp",
    },
    {
      id: "gross",
      label: nodeLabel(
        (isRecord(s1.gross_profit) && typeof s1.gross_profit.label === "string" ? s1.gross_profit.label : undefined) ??
          "매출총이익",
        gross,
      ),
      group: "profit",
      colorKey: profitKey(gross),
    },
    {
      id: "op",
      label: nodeLabel(
        (isRecord(s1.operating_income) && typeof s1.operating_income.label === "string" ? s1.operating_income.label : undefined) ??
          "영업이익",
        opIncome,
      ),
      group: "profit",
      colorKey: profitKey(opIncome),
    },
    {
      id: "pretax",
      label: nodeLabel(
        (isRecord(s2.pre_tax_income) && typeof s2.pre_tax_income.label === "string" ? s2.pre_tax_income.label : undefined) ??
          "법인세비용차감전순이익",
        pretax,
      ),
      group: "profit",
      colorKey: profitKey(pretax),
    },
    {
      id: "tax",
      label: nodeLabel(
        (isRecord(s3.tax_expense) && typeof s3.tax_expense.label === "string" ? s3.tax_expense.label : undefined) ??
          "법인세비용",
        tax,
      ),
      group: "expense",
      colorKey: "exp",
    },
    {
      id: "net",
      label: nodeLabel(
        (isRecord(s3.net_income) && typeof s3.net_income.label === "string" ? s3.net_income.label : undefined) ??
          "당기순이익",
        net,
      ),
      group: "profit",
      colorKey: profitKey(net),
    },
  ];

  for (const it of opexItems) {
    nodes.push({ id: it.id, label: nodeLabel(it.label, it.value), group: "expense", colorKey: "exp" });
  }
  for (const it of inflows) {
    nodes.push({ id: it.id, label: nodeLabel(it.label, it.value), group: "inflow", colorKey: "seg" });
  }
  for (const it of outflows) {
    nodes.push({ id: it.id, label: nodeLabel(it.label, it.value), group: "expense", colorKey: "exp" });
  }

  const links: SankeyLink[] = [];
  if (revenue > 0) {
    if (cogs > 0) links.push({ source: "rev", target: "cogs", value: cogs });
    if (gross > 0) links.push({ source: "rev", target: "gross", value: gross });
  }
  for (const it of opexItems) {
    if (it.value > 0) links.push({ source: "gross", target: it.id, value: it.value });
  }
  if (opIncome > 0) links.push({ source: "gross", target: "op", value: opIncome });

  const outflowsTotal = outflows.reduce((acc: number, it) => acc + it.value, 0);
  const opRemaining = Math.max(0, opIncome - outflowsTotal);
  for (const it of outflows) {
    if (it.value > 0) links.push({ source: "op", target: it.id, value: it.value });
  }
  if (opRemaining > 0) links.push({ source: "op", target: "pretax", value: opRemaining });
  for (const it of inflows) {
    if (it.value > 0) links.push({ source: it.id, target: "pretax", value: it.value });
  }

  if (tax > 0) links.push({ source: "pretax", target: "tax", value: tax });
  if (net > 0) links.push({ source: "pretax", target: "net", value: net });

  return {
    nodes,
    links,
    kpi: {
      revenue: { value: revenue, qoqPct: null, yoyPct: null },
      opIncome: { value: opIncome, qoqPct: null, yoyPct: null },
      netIncome: { value: net, qoqPct: null, yoyPct: null },
    },
  };
}

export function CompanyDetail({ ticker }: Props) {
  const [company, setCompany] = useState<Company | null>(null);
  const [quarters, setQuarters] = useState<CompanyQuartersResponse | null>(null);
  const [selectedQuarter, setSelectedQuarter] = useState<string | null>(null);
  const [availableItems, setAvailableItems] = useState<DartParsedSofcAvailableItem[] | null>(null);
  const [noData, setNoData] = useState(false);

  const [mode, setMode] = useState<"absolute" | "ratio">("absolute");
  const [topN, setTopN] = useState<number>(12);
  const [otherThreshold, setOtherThreshold] = useState<number>(0.03);

  const [quarterPayload, setQuarterPayload] = useState<QuarterPayload | null>(null);
  const [timeseries, setTimeseries] = useState<TimeSeriesPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selection, setSelection] = useState<
    | { kind: "node"; id: string }
    | { kind: "link"; source: string; target: string }
    | null
  >(null);

  const playRef = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setNoData(false);
        setError(null);
        const [c, avail] = await Promise.all([
          apiGetJson<Company>(`/companies/${encodeURIComponent(ticker)}`),
          apiGetJson<DartParsedSofcAvailableResponse>(
            `/companies/${encodeURIComponent(
              ticker,
            )}/dart/parsed_state_of_comprehensive_income/available`,
          ),
        ]);
        if (cancelled) return;
        setCompany(c);
        setAvailableItems(avail.items ?? []);
        const qs: QuarterOption[] = (avail.items ?? []).map((it) => ({
          id: it.id,
          label: formatQuarterLabel(it.id),
        }));
        setQuarters({ ticker, quarters: qs });
        if (!qs.length) {
          setNoData(true);
          setTimeseries(null);
          setSelectedQuarter(null);
          setQuarterPayload(null);
          setSelection(null);
        } else {
          setSelectedQuarter((prev) => prev ?? qs[qs.length - 1]?.id ?? null);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setNoData(true);
          setAvailableItems([]);
          setQuarters({ ticker, quarters: [] });
          setTimeseries(null);
          setSelectedQuarter(null);
          setQuarterPayload(null);
          setSelection(null);
          return;
        }
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      if (playRef.current) {
        window.clearInterval(playRef.current);
        playRef.current = null;
        setPlaying(false);
      }
    };
  }, [ticker]);

  const quarterIndex = useMemo(() => {
    if (!quarters || !selectedQuarter) return -1;
    return quarters.quarters.findIndex((q) => q.id === selectedQuarter);
  }, [quarters, selectedQuarter]);

  const quarterLabel = useMemo(() => {
    if (!quarters || !selectedQuarter) return "";
    return quarters.quarters.find((q) => q.id === selectedQuarter)?.label ?? selectedQuarter;
  }, [quarters, selectedQuarter]);

  useEffect(() => {
    if (!selectedQuarter || noData) return;
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const meta = (availableItems ?? []).find((it) => it.id === selectedQuarter);
        if (!meta) {
          if (!cancelled) setQuarterPayload(null);
          return;
        }
        const parsed = await apiGetJson<DartParsedSofcResponse>(
          `/companies/${encodeURIComponent(
            ticker,
          )}/dart/parsed_state_of_comprehensive_income/${meta.year}/${meta.quarter}`,
        );
        const sankey = toParsedSofcSankey(parsed.data);
        const qp: QuarterPayload = {
          ticker,
          quarter: selectedQuarter,
          label: formatQuarterLabel(selectedQuarter),
          currency: company?.currency ?? "KRW",
          unit: company?.unit ?? "KRW",
          kpi: sankey.kpi,
          sankey: { nodes: sankey.nodes, links: sankey.links },
        };
        if (!cancelled) {
          setQuarterPayload(qp);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, selectedQuarter, noData, availableItems, company?.currency, company?.unit]);

  // Build sparklines strictly from parsed JSON (no generated timeseries).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (noData) return;
        if (!availableItems || availableItems.length === 0) return;
        const ts = await apiGetJson<TimeSeriesPayload>(
          `/companies/${encodeURIComponent(ticker)}/timeseries?metrics=revenue&metrics=op_income&metrics=net_income`,
        );
        if (!cancelled) setTimeseries(ts);
      } catch {
        // Timeseries is non-blocking for the detail page; ignore failures.
        if (!cancelled) setTimeseries(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, noData, availableItems]);

  const displaySankey = useMemo(() => {
    if (!quarterPayload) return null;

    // MVP: keep structure, only apply simple "Top N links" + "Other threshold" grouping.
    const nodes = [...quarterPayload.sankey.nodes];
    let links = [...quarterPayload.sankey.links];

    // sort by absolute value, keep topN; group rest into "Other"
    const sorted = [...links].sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
    const keep = sorted.slice(0, clamp(topN, 1, 50));
    const dropped = sorted.slice(clamp(topN, 1, 50));
    const total = links.reduce((acc, l) => acc + (l.value ?? 0), 0) || 1;
    const thresholdValue = total * clamp(otherThreshold, 0, 1);
    const reallyDropped = dropped.filter((l) => (l.value ?? 0) >= thresholdValue);
    const grouped = dropped.filter((l) => (l.value ?? 0) < thresholdValue);

    if (grouped.length > 0) {
      const otherId = "other";
      if (!nodes.some((n) => n.id === otherId)) {
        nodes.push({ id: otherId, label: "Other", group: "other", colorKey: "seg" });
      }
      // Group "small links" by moving their target into Other (visual approximation)
      const bySource = new Map<string, number>();
      for (const l of grouped) {
        bySource.set(l.source, (bySource.get(l.source) ?? 0) + l.value);
      }
      for (const [source, value] of bySource.entries()) {
        keep.push({ source, target: otherId, value });
      }
    }

    links = [...keep, ...reallyDropped];
    return { nodes, links };
  }, [quarterPayload, topN, otherThreshold]);

  const selectedDetail = useMemo(() => {
    if (!selection || !displaySankey) return null;
    const denom =
      displaySankey.links
        .filter((l) => l.source === "rev")
        .reduce((acc, l) => acc + (l.value ?? 0), 0) ||
      displaySankey.links.reduce((acc, l) => acc + (l.value ?? 0), 0) ||
      1;
    if (selection.kind === "node") {
      const node = displaySankey.nodes.find((n) => n.id === selection.id);
      if (!node) return null;
      const inSum = displaySankey.links
        .filter((l) => l.target === node.id)
        .reduce((a, l) => a + l.value, 0);
      const outSum = displaySankey.links
        .filter((l) => l.source === node.id)
        .reduce((a, l) => a + l.value, 0);
      return { kind: "node" as const, title: node.label, subtitle: "Node", inSum, outSum };
    }
    const link = displaySankey.links.find(
      (l) => l.source === selection.source && l.target === selection.target,
    );
    if (!link) return null;
    const s = displaySankey.nodes.find((n) => n.id === selection.source)?.label ?? selection.source;
    const t = displaySankey.nodes.find((n) => n.id === selection.target)?.label ?? selection.target;
    const ratioValue = (link.value / denom) * 100;
    return {
      kind: "link" as const,
      title: `${s} → ${t}`,
      subtitle: "Link",
      value: link.value,
      ratioValue,
    };
  }, [selection, displaySankey]);

  function stopPlay() {
    if (playRef.current) {
      window.clearInterval(playRef.current);
      playRef.current = null;
    }
    setPlaying(false);
  }

  function togglePlay() {
    if (!quarters || quarterIndex < 0) return;
    if (playRef.current) {
      stopPlay();
      return;
    }
    setPlaying(true);
    playRef.current = window.setInterval(() => {
      setSelectedQuarter((cur) => {
        if (!cur || !quarters) return cur;
        const idx = quarters.quarters.findIndex((q) => q.id === cur);
        const nextIdx = idx + 1;
        if (nextIdx >= quarters.quarters.length) {
          stopPlay();
          return cur;
        }
        return quarters.quarters[nextIdx].id;
      });
    }, 900);
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4">
        <Link href="/" className="text-sm text-zinc-600 hover:text-zinc-900">
          ← 목록으로
        </Link>
      </div>

      {error && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          오류: {error}
        </div>
      )}

      {noData && (
        <div className="mt-4 rounded-2xl border border-zinc-200 bg-white p-5 text-sm text-zinc-700">
          데이터가 존재하지 않습니다.
        </div>
      )}

      {/* Main area */}
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-8">
          {/* Header: keep in the left column so it aligns with the chart width and scrolls naturally */}
          <div className="mb-5 rounded-2xl border border-zinc-200 bg-white/80 p-4 backdrop-blur">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="text-lg font-semibold">
                  {company?.name ?? "Loading..."}{" "}
                  <span className="text-sm font-medium text-zinc-500">{ticker}</span>
                </div>
                <div className="mt-1 text-xs text-zinc-600">
                  단위: {company?.unit ?? "—"} · 통화: {company?.currency ?? "—"} · 시총:{" "}
                  {company
                    ? `${formatCompactKRW(company.marketCap)} ${company.currency}`
                    : "—"}
                </div>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <div>
                  <div className="text-xs font-medium text-zinc-600">분기</div>
                  <select
                    value={selectedQuarter ?? ""}
                    onChange={(e) => setSelectedQuarter(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm"
                    disabled={!quarters || noData || (quarters?.quarters?.length ?? 0) === 0}
                  >
                    {(quarters?.quarters ?? []).map((q) => (
                      <option key={q.id} value={q.id}>
                        {q.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="min-w-56">
                  <div className="text-xs font-medium text-zinc-600">슬라이더</div>
                  <input
                    type="range"
                    min={0}
                    max={(quarters?.quarters.length ?? 1) - 1}
                    value={Math.max(0, quarterIndex)}
                    onChange={(e) => {
                      if (!quarters) return;
                      const idx = Number(e.target.value);
                      const q = quarters.quarters[idx];
                      if (q) setSelectedQuarter(q.id);
                    }}
                    className="mt-2 w-full"
                    disabled={!quarters || noData || (quarters?.quarters?.length ?? 0) === 0}
                  />
                  <div className="mt-1 text-xs text-zinc-500">{quarterLabel}</div>
                </div>

                <button
                  onClick={togglePlay}
                  className="rounded-xl bg-zinc-950 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-800"
                  disabled={!quarters || noData || (quarters?.quarters?.length ?? 0) === 0}
                >
                  {playing ? "정지" : "재생"}
                </button>
              </div>
            </div>

            {/* Options */}
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2">
                <div className="text-xs font-medium text-zinc-600">표시</div>
                <div className="mt-2 flex gap-2">
                  <button
                    onClick={() => setMode("absolute")}
                    className={`flex-1 rounded-lg px-2 py-1 text-xs font-medium ${
                      mode === "absolute"
                        ? "bg-zinc-950 text-white"
                        : "bg-zinc-100 text-zinc-800"
                    }`}
                  >
                    절대값
                  </button>
                  <button
                    onClick={() => setMode("ratio")}
                    className={`flex-1 rounded-lg px-2 py-1 text-xs font-medium ${
                      mode === "ratio"
                        ? "bg-zinc-950 text-white"
                        : "bg-zinc-100 text-zinc-800"
                    }`}
                  >
                    비중(%)
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2">
                <div className="text-xs font-medium text-zinc-600">Top N (기본 12)</div>
                <input
                  type="number"
                  value={topN}
                  min={1}
                  max={50}
                  onChange={(e) => setTopN(Number(e.target.value || 12))}
                  className="mt-2 w-full rounded-lg border border-zinc-200 bg-white px-2 py-1 text-sm"
                />
              </div>

              <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2">
                <div className="text-xs font-medium text-zinc-600">
                  Other 묶기 임계값 (기본 3%)
                </div>
                <div className="mt-2 flex items-center gap-3">
                  <input
                    type="range"
                    min={0}
                    max={0.2}
                    step={0.01}
                    value={otherThreshold}
                    onChange={(e) => setOtherThreshold(Number(e.target.value))}
                    className="w-full"
                  />
                  <div className="w-16 text-right text-xs font-medium text-zinc-700">
                    {(otherThreshold * 100).toFixed(0)}%
                  </div>
                </div>
              </div>
            </div>
          </div>

          {loading && (
            <div className="mb-3 rounded-xl border border-zinc-200 bg-white p-3 text-sm text-zinc-600">
              적용 중...
            </div>
          )}
          {!noData && displaySankey && (
            <SankeyChart
              nodes={displaySankey.nodes}
              links={displaySankey.links}
              mode={mode}
              onSelect={setSelection}
            />
          )}
        </div>

        {/* Insight panel */}
        <aside className="lg:col-span-4">
          <div className="grid grid-cols-1 gap-3">
            {!noData && quarterPayload ? (
              <>
                <KpiCard title="매출" item={quarterPayload.kpi.revenue} />
                <KpiCard title="영업이익" item={quarterPayload.kpi.opIncome} />
                <KpiCard title="순이익" item={quarterPayload.kpi.netIncome} />
              </>
            ) : noData ? (
              <div className="rounded-2xl border border-zinc-200 bg-white p-4 text-sm text-zinc-700">
                데이터가 존재하지 않습니다.
              </div>
            ) : (
              <div className="rounded-2xl border border-zinc-200 bg-white p-4 text-sm text-zinc-600">
                KPI 로딩 중...
              </div>
            )}

            {!noData && (
              <div className="rounded-2xl border border-zinc-200 bg-white p-4">
              <div className="text-sm font-semibold">선택 항목</div>
              <div className="mt-1 text-xs text-zinc-500">
                Sankey에서 클릭하면 여기 고정 표시 · 더블클릭(차트)로 해제
              </div>
              <div className="mt-3">
                {!selectedDetail && (
                  <div className="text-sm text-zinc-600">아직 선택된 항목이 없어요.</div>
                )}
                {selectedDetail && (
                  <div>
                    <div className="text-sm font-semibold">{selectedDetail.title}</div>
                    <div className="mt-1 text-xs text-zinc-500">{selectedDetail.subtitle}</div>
                    {selectedDetail.kind === "link" ? (
                      <div className="mt-3 text-sm">
                        값:{" "}
                        <span className="font-semibold">
                          {mode === "ratio"
                            ? `${selectedDetail.ratioValue.toFixed(2)}%`
                            : `${selectedDetail.value.toLocaleString("ko-KR")}`}
                        </span>
                      </div>
                    ) : (
                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-zinc-600">
                        <div className="rounded-lg bg-zinc-50 p-2">
                          In:{" "}
                          <span className="font-semibold text-zinc-900">
                            {selectedDetail.inSum.toLocaleString("ko-KR")}
                          </span>
                        </div>
                        <div className="rounded-lg bg-zinc-50 p-2">
                          Out:{" "}
                          <span className="font-semibold text-zinc-900">
                            {selectedDetail.outSum.toLocaleString("ko-KR")}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            )}
          </div>
        </aside>
      </div>

      {/* Overview sparklines */}
      {!noData && (
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Sparkline
          title="매출(필수)"
          points={timeseries?.series?.revenue ?? []}
          selectedQuarter={selectedQuarter ?? ""}
          onSelectQuarter={(q) => setSelectedQuarter(q)}
          valueFormatter={(v) => `${formatCompactKRW(v)} KRW`}
        />
        <Sparkline
          title="영업이익"
          points={timeseries?.series?.op_income ?? []}
          selectedQuarter={selectedQuarter ?? ""}
          onSelectQuarter={(q) => setSelectedQuarter(q)}
          valueFormatter={(v) => `${formatCompactKRW(v)} KRW`}
        />
        </div>
      )}
    </main>
  );
}


