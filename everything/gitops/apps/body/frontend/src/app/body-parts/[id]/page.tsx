"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getConfig, getOverview, getEvaluations, type AppConfig } from "@/lib/api";
import AttributeBarChart from "@/components/attribute-bar-chart";
import HistoryLineChart from "@/components/history-line-chart";
import { formatDate } from "@/lib/utils";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

const ATTR_LABELS: Record<string, string> = {
  strength: "근력",
  development: "발달도",
  mmc: "MMC",
};

function getLevelGuide(config: AppConfig | undefined): Record<string, Record<string, string>> {
  if (!config) return {};
  const guide: Record<string, Record<string, string>> = {};
  config.attributes.forEach((attr) => {
    if (attr.levels) guide[attr.id] = attr.levels;
  });
  return guide;
}

export default function BodyPartDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: overview } = useQuery({ queryKey: ["overview"], queryFn: getOverview });
  const { data: evaluations } = useQuery({
    queryKey: ["evaluations", id],
    queryFn: () => getEvaluations({ part: id }),
  });

  const bodyPart = config?.body_parts.find((bp) => bp.id === id);
  const partScore = overview?.part_scores.find((ps) => ps.part_id === id);

  if (!config || !overview) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-text-tertiary text-sm">로딩 중...</div>
      </div>
    );
  }

  if (!bodyPart) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <p className="text-text-tertiary">부위를 찾을 수 없습니다</p>
      </div>
    );
  }

  const current = {
    strength: partScore?.strength ?? 0,
    development: partScore?.development ?? 0,
    mmc: partScore?.mmc ?? 0,
  };

  const sortedEvals = [...(evaluations || [])].sort(
    (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
  );

  const historyData = [...(evaluations || [])]
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
    .map((e) => ({
      date: e.date,
      strength: e.strength,
      development: e.development,
      mmc: e.mmc,
    }));

  const levelGuide = getLevelGuide(config);
  const lowScoreGuides: { attr: string; level: string; guide: string }[] = [];
  Object.entries(current).forEach(([attr, val]) => {
    if (val <= 2 && val > 0) {
      const level = Math.floor(val).toString();
      const guide = levelGuide[attr]?.[level];
      if (guide) {
        lowScoreGuides.push({ attr: ATTR_LABELS[attr], level, guide });
      }
    }
  });

  return (
    <div className="space-y-5 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href="/body-parts"
          className="p-2 rounded-xl hover:bg-surface-secondary transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-text-tertiary" />
        </Link>
        <div>
          <h1 className="text-[22px] font-bold text-text-primary">
            {bodyPart.name}
          </h1>
          <p className="text-[13px] text-text-secondary">
            대표 종목: {bodyPart.representative_exercise}
          </p>
        </div>
      </div>

      {/* Strength Standards */}
      {Object.keys(bodyPart.strength_standards).length > 0 && (
        <div className="rounded-2xl bg-surface border border-border p-5">
          <h2 className="text-sm font-semibold text-text-primary mb-3">
            근력 기준표 (체중 대비)
          </h2>
          <div className="grid grid-cols-5 gap-2">
            {Object.entries(bodyPart.strength_standards).map(
              ([level, standard]) => (
                <div
                  key={level}
                  className="px-3 py-2 rounded-xl bg-surface-secondary border border-border-light text-center"
                >
                  <span className="text-[11px] text-text-tertiary block">Lv.{level}</span>
                  <span className="text-[13px] font-semibold text-text-primary">{standard}</span>
                </div>
              )
            )}
          </div>
        </div>
      )}

      {/* Bar Chart */}
      <div className="rounded-2xl bg-surface border border-border p-5">
        <h2 className="text-[15px] font-semibold text-text-primary mb-4">
          현재 속성
        </h2>
        <AttributeBarChart current={current} />
      </div>

      {/* History Line Chart */}
      {historyData.length > 0 && (
        <div className="rounded-2xl bg-surface border border-border p-5">
          <h2 className="text-[15px] font-semibold text-text-primary mb-4">
            변화 추이
          </h2>
          <HistoryLineChart data={historyData} />
        </div>
      )}

      {/* Improvement Guide */}
      {lowScoreGuides.length > 0 && (
        <div className="rounded-2xl bg-amber-50 border border-amber-200 p-5">
          <h2 className="text-[15px] font-semibold text-amber-700 mb-3">
            개선 가이드
          </h2>
          <div className="space-y-2.5">
            {lowScoreGuides.map((g, i) => (
              <div key={i} className="flex gap-3">
                <span className="text-[11px] text-amber-600 bg-amber-100 px-2 py-1 rounded-lg font-medium whitespace-nowrap h-fit">
                  {g.attr} Lv.{g.level}
                </span>
                <p className="text-[13px] text-text-secondary">{g.guide}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Evaluation Log */}
      <div className="rounded-2xl bg-surface border border-border p-5">
        <h2 className="text-[15px] font-semibold text-text-primary mb-4">
          평가 기록
        </h2>
        {sortedEvals.length === 0 ? (
          <p className="text-[13px] text-text-tertiary">아직 평가 기록이 없습니다</p>
        ) : (
          <div className="space-y-2">
            {sortedEvals.map((ev, i) => (
              <div
                key={i}
                className="flex flex-col sm:flex-row sm:items-center gap-2 px-4 py-3 rounded-xl bg-surface-secondary border border-border-light"
              >
                <span className="text-[13px] font-mono font-semibold text-brand-dark w-24 shrink-0">
                  {formatDate(ev.date)}
                </span>
                <div className="flex gap-3 flex-wrap flex-1">
                  <span className="text-[12px] text-text-secondary">
                    근력 {ev.strength.toFixed(1)}
                  </span>
                  <span className="text-[12px] text-text-secondary">
                    발달 {ev.development.toFixed(1)}
                  </span>
                  <span className="text-[12px] text-text-secondary">
                    MMC {ev.mmc.toFixed(1)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
