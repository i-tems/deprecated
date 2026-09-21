"use client";

import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { ATTRIBUTES } from "@/lib/api";

interface RadarChartData {
  scores: Record<string, number>;
  requiredSkills?: Record<string, number> | null;
  size?: number;
}

export function SkillRadarChart({
  scores,
  requiredSkills,
  size = 300,
}: RadarChartData) {
  const data = ATTRIBUTES.map((attr) => ({
    attribute: attr.label,
    score: scores[attr.key] || 0,
    required: requiredSkills?.[attr.key] || 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={size}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
        <PolarGrid stroke="#26272B" />
        <PolarAngleAxis
          dataKey="attribute"
          tick={{ fill: "#8A8F98", fontSize: 11 }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 5]}
          tick={{ fill: "#6E7178", fontSize: 10 }}
          tickCount={6}
        />
        {requiredSkills && (
          <Radar
            name="요구 수준"
            dataKey="required"
            stroke="#6E7178"
            fill="#6E7178"
            fillOpacity={0.1}
            strokeDasharray="4 4"
          />
        )}
        <Radar
          name="내 점수"
          dataKey="score"
          stroke="#5E6AD2"
          fill="#5E6AD2"
          fillOpacity={0.15}
          strokeWidth={2}
        />
        {requiredSkills && <Legend />}
      </RadarChart>
    </ResponsiveContainer>
  );
}

export function MiniRadarChart({ scores }: { scores: Record<string, number> }) {
  const data = ATTRIBUTES.map((attr) => ({
    attribute: attr.label,
    score: scores[attr.key] || 0,
  }));

  return (
    <ResponsiveContainer width={100} height={100}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
        <PolarGrid stroke="#26272B" />
        <Radar
          dataKey="score"
          stroke="#5E6AD2"
          fill="#5E6AD2"
          fillOpacity={0.2}
          strokeWidth={1.5}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}
