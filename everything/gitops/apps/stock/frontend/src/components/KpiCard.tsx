"use client";

import { formatCompactKRW, formatPct } from "@/lib/format";
import type { QuarterKpiItem } from "@/lib/types";

type Props = {
  title: string;
  item: QuarterKpiItem;
};

export function KpiCard({ title, item }: Props) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4">
      <div className="text-xs font-medium text-zinc-500">{title}</div>
      <div className="mt-1 text-lg font-semibold">{formatCompactKRW(item.value)} KRW</div>
      <div className="mt-2 text-xs text-zinc-600">
        QoQ <span className="font-medium text-zinc-900">{formatPct(item.qoqPct)}</span>
        <span className="mx-2 text-zinc-300">|</span>
        YoY <span className="font-medium text-zinc-900">{formatPct(item.yoyPct)}</span>
      </div>
    </div>
  );
}


