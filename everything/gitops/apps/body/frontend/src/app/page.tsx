"use client";

import { useQuery } from "@tanstack/react-query";
import { getOverview } from "@/lib/api";
import BodyRadarChart from "@/components/body-radar-chart";
import SkillRadarChart from "@/components/skill-radar-chart";
import StatCard from "@/components/stat-card";
import Card from "@/components/card";
import { Zap, TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";

export default function DashboardPage() {
  const { data: overview, isLoading, error } = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-text-tertiary text-sm">로딩 중...</div>
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <p className="text-text-secondary mb-2">데이터를 불러올 수 없습니다</p>
          <p className="text-xs text-text-tertiary">
            백엔드 연결을 확인하세요
          </p>
        </div>
      </div>
    );
  }

  const positiveChanges = overview.recent_changes.filter((c) => c.change > 0);
  const negativeChanges = overview.recent_changes.filter((c) => c.change < 0);

  return (
    <div className="space-y-6">
      <h1 className="text-[22px] font-bold text-text-primary">대시보드</h1>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard
          title="전투력"
          value={overview.total_score.toFixed(1)}
          subtitle="전체 합산 점수"
          icon={<Zap className="w-5 h-5 text-brand" />}
        />
        <StatCard
          title="마지막 평가"
          value={overview.last_evaluation_date || "-"}
          subtitle="최근 평가 일자"
        />
        <StatCard
          title="평가된 부위"
          value={`${overview.part_scores.filter((p) => p.total > 0).length} / ${overview.part_scores.length}`}
          subtitle="활성 부위 수"
        />
      </div>

      {/* Radar Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <h2 className="text-[15px] font-semibold text-text-primary mb-1">
            전신 레이더
          </h2>
          <p className="text-[12px] text-text-tertiary mb-2">
            10부위 속성별 분포
          </p>
          <BodyRadarChart partScores={overview.part_scores} />
        </Card>

        <Card>
          <h2 className="text-[15px] font-semibold text-text-primary mb-1">
            기초 스킬
          </h2>
          <p className="text-[12px] text-text-tertiary mb-2">
            5가지 기초 운동 능력
          </p>
          <SkillRadarChart skillScores={overview.skill_scores} />
        </Card>
      </div>

      {/* Changes & Weaknesses */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <h2 className="text-[15px] font-semibold text-text-primary mb-4">
            최근 변화
          </h2>
          {overview.recent_changes.length === 0 ? (
            <p className="text-sm text-text-tertiary py-4 text-center">
              아직 변화 기록이 없습니다
            </p>
          ) : (
            <div className="space-y-2">
              {positiveChanges.map((c, i) => (
                <div
                  key={`pos-${i}`}
                  className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-emerald-50 border border-emerald-100"
                >
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-brand" />
                    <span className="text-[13px] font-medium text-text-primary">
                      {c.part_name}
                    </span>
                    <span className="text-[11px] text-text-tertiary">
                      {c.attribute}
                    </span>
                  </div>
                  <span className="text-[13px] font-mono font-semibold text-brand">
                    {c.old_value.toFixed(1)} → {c.new_value.toFixed(1)}
                  </span>
                </div>
              ))}
              {negativeChanges.map((c, i) => (
                <div
                  key={`neg-${i}`}
                  className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-red-50 border border-red-100"
                >
                  <div className="flex items-center gap-2">
                    <TrendingDown className="w-4 h-4 text-danger" />
                    <span className="text-[13px] font-medium text-text-primary">
                      {c.part_name}
                    </span>
                    <span className="text-[11px] text-text-tertiary">
                      {c.attribute}
                    </span>
                  </div>
                  <span className="text-[13px] font-mono font-semibold text-danger">
                    {c.old_value.toFixed(1)} → {c.new_value.toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <h2 className="text-[15px] font-semibold text-text-primary mb-4 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-warning" />
            약점 알림
          </h2>
          {overview.weakest.length === 0 ? (
            <p className="text-sm text-text-tertiary py-4 text-center">
              데이터가 부족합니다
            </p>
          ) : (
            <div className="space-y-2.5">
              {overview.weakest.map((w, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between px-3.5 py-3 rounded-xl bg-amber-50 border border-amber-100"
                >
                  <div>
                    <span className="text-[13px] font-medium text-text-primary">
                      {w.part_name}
                    </span>
                    <span className="text-[11px] text-text-tertiary ml-2">
                      {w.attribute}
                    </span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <div className="w-20 h-2 bg-amber-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-warning rounded-full"
                        style={{ width: `${(w.value / 5) * 100}%` }}
                      />
                    </div>
                    <span className="text-[13px] font-mono font-semibold text-amber-600 w-8 text-right">
                      {w.value.toFixed(1)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
