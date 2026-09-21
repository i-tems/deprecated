"use client";

const ATTRS = [
  { key: "strength", label: "근력", color: "#10b981" },
  { key: "development", label: "발달도", color: "#3b82f6" },
  { key: "mmc", label: "MMC", color: "#f59e0b" },
] as const;

interface Props {
  current: {
    strength: number;
    development: number;
    mmc: number;
  };
}

export default function AttributeBarChart({ current }: Props) {
  return (
    <div className="space-y-2.5">
      {ATTRS.map((a) => {
        const val = current[a.key as keyof typeof current];
        const pct = (val / 5) * 100;
        return (
          <div key={a.key}>
            <div className="flex justify-between items-center mb-1">
              <span className="text-[12px] text-text-secondary">{a.label}</span>
              <span className="text-[12px] font-mono font-semibold text-text-primary">
                {val.toFixed(1)}
              </span>
            </div>
            <div className="h-2 bg-surface-tertiary rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${pct}%`, backgroundColor: a.color }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
