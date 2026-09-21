"use client";

import { useMemo } from "react";

import { Plot } from "@/components/Plot";
import type { TimePoint } from "@/lib/types";

type Props = {
  title: string;
  points: TimePoint[];
  selectedQuarter: string;
  onSelectQuarter: (q: string) => void;
  valueFormatter?: (v: number) => string;
};

export function Sparkline({
  title,
  points,
  selectedQuarter,
  onSelectQuarter,
  valueFormatter,
}: Props) {
  const { x, y, selectedIndex } = useMemo(() => {
    const xs = points.map((p) => p.quarter);
    const ys = points.map((p) => p.value);
    const idx = xs.indexOf(selectedQuarter);
    return { x: xs, y: ys, selectedIndex: idx };
  }, [points, selectedQuarter]);

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">{title}</div>
        <div className="text-xs text-zinc-500">{points.length}q</div>
      </div>
      <div className="mt-2 h-24">
        <Plot
          data={[
            {
              type: "scatter",
              mode: "lines+markers",
              x,
              y,
              line: { color: "#0a0a0a", width: 2 },
              marker: {
                color: x.map((q) => (q === selectedQuarter ? "#2563eb" : "rgba(0,0,0,0.25)")),
                size: x.map((q) => (q === selectedQuarter ? 8 : 5)),
              },
              hovertemplate: valueFormatter
                ? "%{x}<br>%{customdata}<extra></extra>"
                : "%{x}<br>%{y:,.0f}<extra></extra>",
              customdata: valueFormatter ? y.map((v) => valueFormatter(v)) : undefined,
            } satisfies Record<string, unknown>,
          ]}
          layout={{
            margin: { l: 10, r: 10, t: 6, b: 18 },
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)",
            xaxis: { showgrid: false, showticklabels: false, zeroline: false },
            yaxis: { showgrid: false, showticklabels: false, zeroline: false },
          }}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: "100%", height: "100%" }}
          onClick={(e: unknown) => {
            const p = (e as { points?: unknown[] } | null | undefined)?.points?.[0] as { x?: unknown } | undefined;
            const q = typeof p?.x === "string" ? p.x : undefined;
            if (q) onSelectQuarter(q);
          }}
        />
      </div>
      {selectedIndex >= 0 && (
        <div className="mt-2 text-xs text-zinc-600">
          선택: <span className="font-medium text-zinc-900">{selectedQuarter}</span>
        </div>
      )}
    </div>
  );
}


