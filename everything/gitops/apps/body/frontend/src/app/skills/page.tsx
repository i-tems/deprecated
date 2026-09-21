"use client";

import { useQuery } from "@tanstack/react-query";
import { getOverview, getConfig, getSkillEvaluations } from "@/lib/api";
import SkillRadarChart from "@/components/skill-radar-chart";
import HistoryLineChart from "@/components/history-line-chart";
import Card from "@/components/card";

export default function SkillsPage() {
  const { data: overview } = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
  });
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });
  const { data: skillEvals } = useQuery({
    queryKey: ["skill-evaluations"],
    queryFn: () => getSkillEvaluations(),
  });

  if (!overview || !config) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-text-tertiary text-sm">로딩 중...</div>
      </div>
    );
  }

  const historyMap: Record<string, { date: string; score: number }[]> = {};
  (skillEvals || []).forEach((se) => {
    if (!historyMap[se.skill_id]) historyMap[se.skill_id] = [];
    historyMap[se.skill_id].push({ date: se.date, score: se.score });
  });
  Object.values(historyMap).forEach((arr) =>
    arr.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
  );

  const allDates = new Set<string>();
  (skillEvals || []).forEach((se) => allDates.add(se.date));
  const sortedDates = Array.from(allDates).sort();

  const growthData = sortedDates.map((date) => {
    const entry: Record<string, string | number | undefined> & {
      date: string;
    } = { date };
    config.skills.forEach((s) => {
      const ev = (skillEvals || []).find(
        (se) => se.date === date && se.skill_id === s.id
      );
      if (ev) entry[s.name] = ev.score;
    });
    return entry;
  });

  return (
    <div className="space-y-6">
      <h1 className="text-[22px] font-bold text-text-primary">기초 스킬</h1>

      <Card>
        <h2 className="text-[15px] font-semibold text-text-primary mb-2">
          스킬 레이더
        </h2>
        <SkillRadarChart skillScores={overview.skill_scores} size="lg" />
      </Card>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {config.skills.map((skill) => {
          const score = overview.skill_scores.find(
            (ss) => ss.skill_id === skill.id
          );
          const history = historyMap[skill.id] || [];
          const currentLevel = Math.floor(score?.score ?? 0).toString();
          const levelDesc = skill.levels?.[currentLevel] || "";

          return (
            <Card key={skill.id}>
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-[14px] font-semibold text-text-primary">
                  {skill.name}
                </h3>
                <span className="text-[18px] font-bold text-brand">
                  {score?.score.toFixed(1) ?? "-"}
                </span>
              </div>
              <p className="text-[12px] text-text-tertiary mb-2">
                {skill.description}
              </p>
              {levelDesc && (
                <p className="text-[12px] text-text-secondary mb-3 px-2.5 py-2 rounded-xl bg-surface-secondary border border-border">
                  Lv.{currentLevel}: {levelDesc}
                </p>
              )}
              {history.length > 1 && (
                <HistoryLineChart
                  data={history}
                  availableKeys={["score"]}
                  height={100}
                />
              )}
            </Card>
          );
        })}
      </div>

      {growthData.length > 1 && (
        <Card>
          <h2 className="text-[15px] font-semibold text-text-primary mb-4">
            성장 추이
          </h2>
          <HistoryLineChart
            data={growthData}
            availableKeys={config.skills.map((s) => s.name)}
            height={320}
          />
        </Card>
      )}
    </div>
  );
}
