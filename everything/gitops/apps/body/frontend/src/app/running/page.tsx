"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getConfig,
  getOverview,
  getRunningEvaluations,
  formatRunningValue,
  parseRunningInput,
  type RunningMetricConfig,
  type RunningScore,
} from "@/lib/api";
import Card from "@/components/card";
import HistoryLineChart from "@/components/history-line-chart";
import { Footprints, Target, ClipboardEdit, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";

/** Given a metric, current value and current level, return the numeric threshold
 *  for the next integer level (ceiling) — i.e. what you have to beat to level up. */
function nextLevelTarget(
  metric: RunningMetricConfig,
  currentLevel: number
): { level: number; threshold: number | null } {
  if (currentLevel >= 5) return { level: 5, threshold: null };
  const nextLv = Math.floor(currentLevel) + 1;
  const raw = metric.level_standards?.[String(nextLv)];
  if (raw == null) return { level: nextLv, threshold: null };
  const thr = parseRunningInput(String(raw), metric.unit);
  return { level: nextLv, threshold: thr };
}

function MetricCard({
  metric,
  score,
  history,
}: {
  metric: RunningMetricConfig;
  score: RunningScore | undefined;
  history: { date: string; score: number }[];
}) {
  const currentLv = score?.level ?? 0;
  const hasLevel = currentLv > 0;
  const hasPR = score?.value != null;
  const { level: nextLv, threshold: nextThr } = nextLevelTarget(metric, currentLv);
  const currentLevelInt = Math.max(1, Math.round(currentLv));

  const standardsEntries = Object.entries(metric.level_standards ?? {}).sort(
    ([a], [b]) => parseInt(a, 10) - parseInt(b, 10)
  );

  return (
    <Card>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-[15px] font-semibold text-text-primary">
            {metric.name}
          </h3>
          <p className="text-[11px] text-text-tertiary mt-0.5">
            {metric.description}
          </p>
        </div>
        <span
          className={cn(
            "text-[11px] font-mono font-bold px-2 py-0.5 rounded shrink-0",
            hasLevel
              ? "bg-brand-light text-brand-dark"
              : "bg-surface-tertiary text-text-tertiary"
          )}
        >
          {hasLevel ? `Lv.${currentLv.toFixed(1)}` : "-"}
        </span>
      </div>

      {/* Current level + Next target */}
      <div className="flex items-end justify-between mb-3 px-3.5 py-2.5 rounded-xl bg-surface-secondary border border-border-light">
        <div>
          <div className="text-[10px] text-text-tertiary font-medium mb-0.5 flex items-center gap-1">
            <Trophy className="w-3 h-3" />
            현재 레벨
          </div>
          <div className="text-[22px] font-mono font-bold text-text-primary leading-none">
            {hasLevel ? currentLv.toFixed(1) : "-"}
          </div>
          {hasPR && (
            <div className="text-[10px] font-mono text-text-tertiary mt-1">
              PR {formatRunningValue(score!.value, metric.unit)}
              {score?.last_date && ` · ${score.last_date}`}
            </div>
          )}
        </div>
        {nextThr != null && hasLevel && (
          <div className="text-right">
            <div className="text-[10px] text-text-tertiary font-medium mb-0.5 flex items-center justify-end gap-1">
              <Target className="w-3 h-3" />
              다음 Lv.{nextLv}
            </div>
            <div className="text-[18px] font-mono font-semibold text-amber-600 leading-none">
              {formatRunningValue(nextThr, metric.unit)}
            </div>
          </div>
        )}
      </div>

      {/* Level ladder */}
      <div className="space-y-1 mb-3">
        {standardsEntries.map(([lv, thr]) => {
          const lvNum = parseInt(lv, 10);
          const thrNum = parseRunningInput(String(thr), metric.unit);
          const isCurrent = lvNum === currentLevelInt && hasLevel;
          const isNext = lvNum === nextLv && !isCurrent && hasLevel;
          return (
            <div
              key={lv}
              className={cn(
                "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] transition-colors",
                isCurrent
                  ? "bg-brand-light border border-brand/30"
                  : isNext
                    ? "bg-amber-50 border border-amber-200"
                    : "bg-surface-secondary border border-transparent"
              )}
            >
              <span
                className={cn(
                  "font-mono font-semibold w-8 shrink-0",
                  isCurrent
                    ? "text-brand-dark"
                    : isNext
                      ? "text-amber-700"
                      : "text-text-tertiary"
                )}
              >
                Lv.{lv}
              </span>
              <span className="font-mono text-text-secondary flex-1">
                {thrNum != null ? formatRunningValue(thrNum, metric.unit) : String(thr)}
              </span>
              {isCurrent && (
                <span className="text-[9px] font-semibold text-brand-dark">
                  현재
                </span>
              )}
              {isNext && (
                <span className="text-[9px] font-semibold text-amber-700">
                  목표
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* History */}
      {history.length > 1 ? (
        <HistoryLineChart
          data={history}
          availableKeys={["score"]}
          height={100}
        />
      ) : (
        <p className="text-[11px] text-text-tertiary text-center py-3">
          {hasLevel ? "기록 1개 — 추이를 보려면 한 번 더 저장" : "기록 없음"}
        </p>
      )}
    </Card>
  );
}

export default function RunningPage() {
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: overview } = useQuery({ queryKey: ["overview"], queryFn: getOverview });
  const { data: runningEvals } = useQuery({
    queryKey: ["running-evaluations"],
    queryFn: () => getRunningEvaluations(),
  });

  const historyByMetric = useMemo(() => {
    const map: Record<string, { date: string; score: number }[]> = {};
    (runningEvals ?? []).forEach((ev) => {
      if (ev.level == null || ev.level <= 0) return;
      if (!map[ev.metric_id]) map[ev.metric_id] = [];
      map[ev.metric_id].push({ date: ev.date, score: ev.level });
    });
    Object.values(map).forEach((arr) =>
      arr.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
    );
    return map;
  }, [runningEvals]);

  if (!config || !overview) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-text-tertiary text-sm">로딩 중...</div>
      </div>
    );
  }

  const metrics = config.running_metrics ?? [];
  const avgLevel =
    metrics.length > 0
      ? overview.running_scores.reduce((a, s) => a + s.level, 0) / metrics.length
      : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[22px] font-bold text-text-primary flex items-center gap-2">
            <Footprints className="w-6 h-6 text-brand" />
            달리기
          </h1>
          <p className="text-[13px] text-text-secondary mt-1">
            거리별 PR과 레벨.{" "}
            <Link href="/evaluate" className="text-brand-dark underline">
              평가 입력
            </Link>
            에서 기록을 갱신하세요.
          </p>
        </div>
        <div className="text-right">
          <div className="text-[10px] text-text-tertiary font-medium uppercase tracking-wide">
            평균 레벨
          </div>
          <div className="text-[28px] font-mono font-bold text-brand-dark leading-none">
            {avgLevel.toFixed(1)}
          </div>
        </div>
      </div>

      {/* Per-metric cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {metrics.map((metric) => (
          <MetricCard
            key={metric.id}
            metric={metric}
            score={overview.running_scores.find((r) => r.metric_id === metric.id)}
            history={historyByMetric[metric.id] ?? []}
          />
        ))}
      </div>

      {/* CTA */}
      <Link
        href="/evaluate"
        className="flex items-center justify-center gap-2 w-full py-3.5 rounded-2xl bg-brand hover:bg-brand-dark text-white font-medium text-[14px] shadow-lg shadow-brand/20 transition-colors"
      >
        <ClipboardEdit className="w-4 h-4" />
        기록 갱신하러 가기
      </Link>
    </div>
  );
}
