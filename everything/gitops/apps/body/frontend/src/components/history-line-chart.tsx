"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface DataPoint {
  date: string;
  [key: string]: string | number | undefined;
}

interface Props {
  data: DataPoint[];
  availableKeys?: string[];
  height?: number;
}

const COLORS: Record<string, { label: string; color: string }> = {
  strength: { label: "근력", color: "#10b981" },
  development: { label: "발달도", color: "#3b82f6" },
  mmc: { label: "MMC", color: "#f59e0b" },
  score: { label: "점수", color: "#10b981" },
};

export default function HistoryLineChart({
  data,
  availableKeys,
  height = 280,
}: Props) {
  const keys = availableKeys || ["strength", "development", "mmc"];
  const [active, setActive] = useState<Set<string>>(new Set(keys));

  const toggle = (key: string) => {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else next.add(key);
      return next;
    });
  };

  return (
    <div>
      {keys.length > 1 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {keys.map((key) => {
            const cfg = COLORS[key] || { label: key, color: "#10b981" };
            return (
              <button
                key={key}
                onClick={() => toggle(key)}
                className={`px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors ${
                  active.has(key)
                    ? "border-brand/40 bg-brand-light text-brand-dark"
                    : "border-border bg-surface-secondary text-text-tertiary hover:text-text-secondary"
                }`}
              >
                {cfg.label}
              </button>
            );
          })}
        </div>
      )}

      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ left: -10, right: 12, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
          <XAxis
            dataKey="date"
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            tickFormatter={(v) => {
              const d = new Date(v);
              return `${d.getMonth() + 1}/${d.getDate()}`;
            }}
          />
          <YAxis
            domain={[0, 5]}
            tick={{ fill: "#9ca3af", fontSize: 11 }}
            tickCount={6}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#fff",
              border: "1px solid #e5e7eb",
              borderRadius: "12px",
              fontSize: "12px",
              boxShadow: "0 4px 6px -1px rgb(0 0 0 / .05)",
            }}
            labelFormatter={(v) => `날짜: ${v}`}
          />
          {keys.length > 1 && (
            <Legend wrapperStyle={{ fontSize: "12px", color: "#6b7280" }} />
          )}
          {keys
            .filter((k) => active.has(k))
            .map((key) => {
              const cfg = COLORS[key] || { label: key, color: "#10b981" };
              return (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={cfg.label}
                  stroke={cfg.color}
                  strokeWidth={2}
                  dot={{ fill: cfg.color, r: 3 }}
                  activeDot={{ r: 5 }}
                  connectNulls
                />
              );
            })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
