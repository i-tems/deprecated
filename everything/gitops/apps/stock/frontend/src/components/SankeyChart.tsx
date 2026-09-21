"use client";

import { useMemo } from "react";

import { Plot } from "@/components/Plot";
import type { SankeyLink, SankeyNode } from "@/lib/types";

type Props = {
  nodes: SankeyNode[];
  links: SankeyLink[];
  mode: "absolute" | "ratio";
  onSelect: (sel: { kind: "node"; id: string } | { kind: "link"; source: string; target: string } | null) => void;
};

function colorFor(key: string): string {
  switch (key) {
    case "rev":
      return "steelblue";
    case "profit_pos":
      return "limegreen";
    case "profit_neg":
      return "red";
    case "exp":
      return "pink";
    case "seg":
      return "steelblue";
    default:
      return "#64748b";
  }
}

export function SankeyChart({ nodes, links, mode, onSelect }: Props) {
  const { labels, nodeColors, sourceIdx, targetIdx, values, linkColors } = useMemo(() => {
    const idToIdx = new Map<string, number>();
    nodes.forEach((n, i) => idToIdx.set(n.id, i));
    const idToNode = new Map<string, SankeyNode>();
    nodes.forEach((n) => idToNode.set(n.id, n));

    const denom =
      links.filter((l) => l.source === "rev").reduce((acc, l) => acc + (l.value ?? 0), 0) ||
      links.reduce((acc, l) => acc + (l.value ?? 0), 0) ||
      1;
    const v = links.map((l) => (mode === "ratio" ? (l.value / denom) * 100 : l.value));

    return {
      labels: nodes.map((n) => n.label),
      nodeColors: nodes.map((n) => colorFor(n.colorKey)),
      sourceIdx: links.map((l) => idToIdx.get(l.source) ?? 0),
      targetIdx: links.map((l) => idToIdx.get(l.target) ?? 0),
      values: v,
      linkColors: links.map((l) => {
        const s = idToNode.get(l.source);
        const t = idToNode.get(l.target);
        // mimic Python draw_sankey intent:
        // - expenses are pink
        // - inflows (non-op incomes) are steelblue
        // - profits are green/red
        if (t?.group === "expense") return "pink";
        if (s?.group === "inflow") return "steelblue";
        if (t?.group === "profit") return colorFor(t.colorKey);
        return "rgba(0,0,0,0.15)";
      }),
    };
  }, [nodes, links, mode]);

  return (
    <div className="h-[800px] w-full rounded-2xl border border-zinc-200 bg-white">
      <Plot
        data={[
          {
            type: "sankey",
            arrangement: "snap",
            node: {
              label: labels,
              pad: 15,
              thickness: 8,
              color: nodeColors,
              line: { color: "black", width: 0.5 },
              hovertemplate: "%{label}<extra></extra>",
            },
            link: {
              source: sourceIdx,
              target: targetIdx,
              value: values,
              color: linkColors,
            },
            hovertemplate:
              mode === "ratio"
                ? "%{source.label} → %{target.label}<br>%{value:.2f}%<extra></extra>"
                : "₩ %{value:,.0f}<extra></extra>",
          } satisfies Record<string, unknown>,
        ]}
        layout={{
          margin: { l: 10, r: 10, t: 10, b: 10 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          hovermode: "x",
          font: { family: "var(--font-geist-sans)", size: 15, color: "black" },
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%", height: "100%" }}
        onClick={(e: unknown) => {
          const p = (e as { points?: unknown[] } | null | undefined)?.points?.[0] as
            | { pointNumber?: unknown; source?: { label?: unknown } | null; target?: { label?: unknown } | null; label?: unknown }
            | undefined;
          if (!p) return;
          if (typeof p.pointNumber === "number" && p.source?.label && p.target?.label) {
            // react-plotly doesn't expose original ids; we approximate with labels is too lossy.
            // For MVP selection, use link indices (we'll map via current links array index).
            const idx = p.pointNumber;
            const l = links[idx];
            if (l) onSelect({ kind: "link", source: l.source, target: l.target });
            return;
          }
          if (typeof p.pointNumber === "number" && p.label) {
            // node pointNumber maps to node index
            const idx = p.pointNumber;
            const n = nodes[idx];
            if (n) onSelect({ kind: "node", id: n.id });
          }
        }}
        onDoubleClick={() => onSelect(null)}
      />
    </div>
  );
}


