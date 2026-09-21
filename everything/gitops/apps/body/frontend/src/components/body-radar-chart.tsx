"use client";

import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { useState } from "react";
import type { PartScore } from "@/lib/api";

const ATTRIBUTES = [
  { key: "strength", label: "근력", color: "#10b981" },
  { key: "development", label: "발달도", color: "#3b82f6" },
  { key: "mmc", label: "MMC", color: "#f59e0b" },
] as const;

interface Props {
  partScores: PartScore[];
  comparisonScores?: PartScore[];
  height?: number;
}

export default function BodyRadarChart({
  partScores,
  comparisonScores,
  height = 320,
}: Props) {
  const [active, setActive] = useState<Set<string>>(new Set(["strength"]));

  const toggle = (key: string) => {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else next.add(key);
      return next;
    });
  };

  const data = partScores.map((ps) => {
    const entry: Record<string, string | number> = { subject: ps.part_name };
    ATTRIBUTES.forEach((a) => {
      if (active.has(a.key))
        entry[a.key] = ps[a.key as keyof PartScore] as number;
    });
    if (comparisonScores) {
      const comp = comparisonScores.find((c) => c.part_id === ps.part_id);
      if (comp) {
        ATTRIBUTES.forEach((a) => {
          if (active.has(a.key))
            entry[`${a.key}_prev`] = comp[a.key as keyof PartScore] as number;
        });
      }
    }
    return entry;
  });

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {ATTRIBUTES.map((a) => (
          <button
            key={a.key}
            onClick={() => toggle(a.key)}
            className={`px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors ${
              active.has(a.key)
                ? "border-brand/40 bg-brand-light text-brand-dark"
                : "border-border bg-surface-secondary text-text-tertiary hover:text-text-secondary"
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <RadarChart data={data} cx="50%" cy="50%" outerRadius="72%">
          <PolarGrid stroke="#e5e7eb" />
          <PolarAngleAxis
            dataKey="subject"
            tick={{ fill: "#374151", fontSize: 12 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 5]}
            tick={{ fill: "#9ca3af", fontSize: 10 }}
            tickCount={6}
          />
          {ATTRIBUTES.filter((a) => active.has(a.key)).map((a) => (
            <Radar
              key={a.key}
              name={a.label}
              dataKey={a.key}
              stroke={a.color}
              fill={a.color}
              fillOpacity={0.12}
              strokeWidth={2}
            />
          ))}
          {comparisonScores &&
            ATTRIBUTES.filter((a) => active.has(a.key)).map((a) => (
              <Radar
                key={`${a.key}_prev`}
                name={`${a.label} (이전)`}
                dataKey={`${a.key}_prev`}
                stroke={a.color}
                fill="none"
                strokeDasharray="4 4"
                strokeOpacity={0.4}
                strokeWidth={1.5}
              />
            ))}
          <Tooltip
            contentStyle={{
              backgroundColor: "#fff",
              border: "1px solid #e5e7eb",
              borderRadius: "12px",
              fontSize: "12px",
              boxShadow: "0 4px 6px -1px rgb(0 0 0 / .05)",
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
