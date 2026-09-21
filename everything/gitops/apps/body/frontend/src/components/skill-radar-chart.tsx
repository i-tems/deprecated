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
import type { SkillScore } from "@/lib/api";

interface Props {
  skillScores: SkillScore[];
  comparisonScores?: SkillScore[];
  size?: "sm" | "lg";
}

export default function SkillRadarChart({
  skillScores,
  comparisonScores,
  size = "sm",
}: Props) {
  const data = skillScores.map((ss) => {
    const entry: Record<string, string | number> = {
      subject: ss.skill_name,
      score: ss.score,
    };
    if (comparisonScores) {
      const comp = comparisonScores.find((c) => c.skill_id === ss.skill_id);
      if (comp) entry.prev = comp.score;
    }
    return entry;
  });

  const h = size === "lg" ? 380 : 280;

  return (
    <ResponsiveContainer width="100%" height={h}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="72%">
        <PolarGrid stroke="#e5e7eb" />
        <PolarAngleAxis
          dataKey="subject"
          tick={{ fill: "#374151", fontSize: size === "lg" ? 13 : 12 }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 5]}
          tick={{ fill: "#9ca3af", fontSize: 10 }}
          tickCount={6}
        />
        <Radar
          name="현재"
          dataKey="score"
          stroke="#10b981"
          fill="#10b981"
          fillOpacity={0.12}
          strokeWidth={2}
        />
        {comparisonScores && (
          <Radar
            name="이전"
            dataKey="prev"
            stroke="#10b981"
            fill="none"
            strokeDasharray="4 4"
            strokeOpacity={0.4}
            strokeWidth={1.5}
          />
        )}
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
  );
}
