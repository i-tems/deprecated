"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getConfig,
  getEvaluations,
  getSkillEvaluations,
  type PartScore,
  type SkillScore,
} from "@/lib/api";
import BodyRadarChart from "@/components/body-radar-chart";
import SkillRadarChart from "@/components/skill-radar-chart";
import HistoryLineChart from "@/components/history-line-chart";
import Card from "@/components/card";
import { getToday } from "@/lib/utils";

type FilterMode = "body" | "skill";

export default function HistoryPage() {
  const today = getToday();
  const ninetyDaysAgo = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 90);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }, []);

  const [fromDate, setFromDate] = useState(ninetyDaysAgo);
  const [toDate, setToDate] = useState(today);
  const [compareDate, setCompareDate] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("body");
  const [selectedPart, setSelectedPart] = useState("");

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });
  const { data: evaluations } = useQuery({
    queryKey: ["evaluations", fromDate, toDate],
    queryFn: () => getEvaluations({ from: fromDate, to: toDate }),
  });
  const { data: skillEvals } = useQuery({
    queryKey: ["skill-evaluations", fromDate, toDate],
    queryFn: () => getSkillEvaluations({ from: fromDate, to: toDate }),
  });

  const evalDates = useMemo(() => {
    const dates = new Set<string>();
    (evaluations || []).forEach((e) => dates.add(e.date));
    return Array.from(dates).sort();
  }, [evaluations]);

  const buildPartScores = (date: string): PartScore[] => {
    if (!config) return [];
    return config.body_parts.map((bp) => {
      const ev = (evaluations || []).find(
        (e) => e.date === date && e.part_id === bp.id
      );
      return {
        part_id: bp.id,
        part_name: bp.name,
        strength: ev?.strength ?? 0,
        development: ev?.development ?? 0,
        mmc: ev?.mmc ?? 0,
        total:
          (ev?.strength ?? 0) +
          (ev?.development ?? 0) +
          (ev?.mmc ?? 0),
      };
    });
  };

  const buildSkillScores = (date: string): SkillScore[] => {
    if (!config) return [];
    return config.skills.map((s) => {
      const ev = (skillEvals || []).find(
        (se) => se.date === date && se.skill_id === s.id
      );
      return {
        skill_id: s.id,
        skill_name: s.name,
        score: ev?.score ?? 0,
      };
    });
  };

  const latestDate = evalDates[evalDates.length - 1] || "";
  const currentPartScores = latestDate ? buildPartScores(latestDate) : [];
  const comparisonPartScores = compareDate
    ? buildPartScores(compareDate)
    : undefined;
  const currentSkillScores = latestDate ? buildSkillScores(latestDate) : [];
  const comparisonSkillScores = compareDate
    ? buildSkillScores(compareDate)
    : undefined;

  const partLineData = useMemo(() => {
    if (!selectedPart || filterMode !== "body") return [];
    return (evaluations || [])
      .filter((e) => e.part_id === selectedPart)
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
      .map((e) => ({
        date: e.date,
        strength: e.strength,
        development: e.development,
        mmc: e.mmc,
      }));
  }, [evaluations, selectedPart, filterMode]);

  if (!config) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-text-tertiary text-sm">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-[22px] font-bold text-text-primary">성장 기록</h1>

      {/* Controls */}
      <Card>
        <div className="flex flex-col sm:flex-row gap-3 items-end">
          <div className="flex-1">
            <label className="block text-[12px] text-text-tertiary font-medium mb-1">
              시작일
            </label>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="w-full px-3 py-2 rounded-xl bg-surface-secondary border border-border text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
            />
          </div>
          <div className="flex-1">
            <label className="block text-[12px] text-text-tertiary font-medium mb-1">
              종료일
            </label>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="w-full px-3 py-2 rounded-xl bg-surface-secondary border border-border text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
            />
          </div>
          <div className="flex-1">
            <label className="block text-[12px] text-text-tertiary font-medium mb-1">
              비교 날짜
            </label>
            <select
              value={compareDate}
              onChange={(e) => setCompareDate(e.target.value)}
              className="w-full px-3 py-2 rounded-xl bg-surface-secondary border border-border text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
            >
              <option value="">선택 안 함</option>
              {evalDates.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-1.5">
            <button
              onClick={() => setFilterMode("body")}
              className={`px-3.5 py-2 rounded-xl text-[13px] font-medium border transition-colors ${
                filterMode === "body"
                  ? "border-brand/40 bg-brand-light text-brand-dark"
                  : "border-border bg-surface-secondary text-text-tertiary"
              }`}
            >
              부위별
            </button>
            <button
              onClick={() => setFilterMode("skill")}
              className={`px-3.5 py-2 rounded-xl text-[13px] font-medium border transition-colors ${
                filterMode === "skill"
                  ? "border-brand/40 bg-brand-light text-brand-dark"
                  : "border-border bg-surface-secondary text-text-tertiary"
              }`}
            >
              스킬별
            </button>
          </div>
        </div>
      </Card>

      {/* Overlay Radar */}
      <Card>
        <h2 className="text-[15px] font-semibold text-text-primary mb-1">
          과거 vs 현재 오버레이
        </h2>
        {compareDate && (
          <p className="text-[12px] text-text-tertiary mb-2">
            {compareDate} → {latestDate}
          </p>
        )}
        {filterMode === "body" ? (
          <BodyRadarChart
            partScores={currentPartScores}
            comparisonScores={comparisonPartScores}
            height={360}
          />
        ) : (
          <SkillRadarChart
            skillScores={currentSkillScores}
            comparisonScores={comparisonSkillScores}
            size="lg"
          />
        )}
      </Card>

      {/* Part Line Chart */}
      {filterMode === "body" && (
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-[15px] font-semibold text-text-primary">
              부위별 추이
            </h2>
            <select
              value={selectedPart}
              onChange={(e) => setSelectedPart(e.target.value)}
              className="px-3 py-1.5 rounded-xl bg-surface-secondary border border-border text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
            >
              <option value="">부위 선택</option>
              {config.body_parts.map((bp) => (
                <option key={bp.id} value={bp.id}>
                  {bp.name}
                </option>
              ))}
            </select>
          </div>
          {selectedPart && partLineData.length > 0 ? (
            <HistoryLineChart data={partLineData} height={320} />
          ) : (
            <p className="text-[13px] text-text-tertiary py-6 text-center">
              {selectedPart
                ? "해당 기간에 평가 데이터가 없습니다"
                : "부위를 선택하세요"}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
