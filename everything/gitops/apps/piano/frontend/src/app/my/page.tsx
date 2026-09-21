"use client";

import { useQuery } from "@tanstack/react-query";
import api, { ATTRIBUTES, type Overview, type UserSong } from "@/lib/api";
import { SkillRadarChart, MiniRadarChart } from "@/components/radar-chart";
import { Badge } from "@/components/ui/badge";
import { STATUS_LABELS, STATUS_COLORS } from "@/lib/api";
import Link from "next/link";

export default function OverviewPage() {
  const { data: overview } = useQuery<Overview>({
    queryKey: ["overview"],
    queryFn: () => api.get("/api/my/overview").then((r) => r.data),
  });

  const { data: mySongs } = useQuery<UserSong[]>({
    queryKey: ["my-songs"],
    queryFn: () => api.get("/api/my/songs").then((r) => r.data),
  });

  const attrLabel = (key: string) =>
    ATTRIBUTES.find((a) => a.key === key)?.label || key;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-toss-gray-900">전체 현황</h1>
        <p className="text-sm text-toss-gray-500 mt-1">
          내 모든 곡의 평균 실력을 한눈에 확인하세요
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { value: overview?.total_songs ?? 0, label: "등록한 곡", color: "text-toss-blue" },
          { value: overview?.practicing_songs ?? 0, label: "연습 중", color: "text-toss-orange" },
          { value: overview?.completed_songs ?? 0, label: "완성", color: "text-toss-green" },
          { value: overview?.total_skills ?? 0, label: "등록 스킬", color: "text-[#8B5CF6]" },
        ].map((stat) => (
          <div key={stat.label} className="bg-card rounded-xl p-5 border border-border">
            <div className={`text-3xl font-semibold ${stat.color}`}>
              {stat.value}
            </div>
            <div className="text-sm text-toss-gray-500 mt-1">{stat.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Radar Chart */}
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">전체 평균 레이더</h2>
          {overview && overview.total_songs > 0 ? (
            <SkillRadarChart scores={overview.average_scores} size={350} />
          ) : (
            <div className="h-[350px] flex items-center justify-center text-toss-gray-400 text-sm">
              곡을 등록하고 평가를 시작하세요
            </div>
          )}
        </div>

        {/* Weakness Analysis */}
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">속성 분석</h2>
          {overview && overview.total_songs > 0 ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                {overview.weakest_attribute && (
                  <div className="p-4 rounded-xl bg-red-50">
                    <div className="text-xs font-medium text-toss-red">
                      가장 약한 속성
                    </div>
                    <div className="text-base font-semibold text-toss-gray-900 mt-1">
                      {attrLabel(overview.weakest_attribute)}
                    </div>
                    <div className="text-sm text-toss-gray-500 mt-0.5">
                      평균{" "}
                      {overview.average_scores[overview.weakest_attribute]?.toFixed(1)}{" "}
                      / 5.0
                    </div>
                  </div>
                )}
                {overview.strongest_attribute && (
                  <div className="p-4 rounded-xl bg-blue-50">
                    <div className="text-xs font-medium text-toss-blue">
                      가장 강한 속성
                    </div>
                    <div className="text-base font-semibold text-toss-gray-900 mt-1">
                      {attrLabel(overview.strongest_attribute)}
                    </div>
                    <div className="text-sm text-toss-gray-500 mt-0.5">
                      평균{" "}
                      {overview.average_scores[overview.strongest_attribute]?.toFixed(1)}{" "}
                      / 5.0
                    </div>
                  </div>
                )}
              </div>
              <div className="space-y-2.5 mt-2">
                {ATTRIBUTES.map((attr) => {
                  const score = overview.average_scores[attr.key] || 0;
                  return (
                    <div key={attr.key} className="flex items-center gap-3">
                      <span className="text-sm text-toss-gray-600 w-28 shrink-0">
                        {attr.label}
                      </span>
                      <div className="flex-1 h-2 bg-toss-gray-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-toss-blue rounded-full transition-all"
                          style={{ width: `${(score / 5) * 100}%` }}
                        />
                      </div>
                      <span className="text-sm font-semibold text-toss-gray-800 w-10 text-right">
                        {score.toFixed(1)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-toss-gray-400 text-sm">
              평가 데이터가 없습니다
            </div>
          )}
        </div>
      </div>

      {/* Skill Levels */}
      {overview && Object.keys(overview.skill_levels).length > 0 && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-toss-gray-900">기초 스킬 현황</h2>
            <Link href="/my/skills">
              <span className="text-sm text-toss-blue font-medium">전체 보기</span>
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {Object.entries(overview.skill_levels).map(([name, level]) => (
              <div
                key={name}
                className="p-3.5 rounded-xl bg-toss-gray-50"
              >
                <div className="text-sm font-medium text-toss-gray-900 mb-2">{name}</div>
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <div
                      key={v}
                      className={`w-6 h-1.5 rounded-full ${
                        v <= level ? "bg-toss-blue" : "bg-toss-gray-200"
                      }`}
                    />
                  ))}
                </div>
                <div className="text-xs text-toss-gray-500 mt-1.5">
                  Lv.{level}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Song Progress Cards */}
      {mySongs && mySongs.length > 0 && (
        <div>
          <h2 className="text-base font-semibold text-toss-gray-900 mb-3">곡별 진행 현황</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {mySongs.map((us) => {
              const eval_ = us.latest_evaluation;
              const avg = eval_
                ? ATTRIBUTES.reduce(
                    (sum, a) =>
                      sum + (eval_[a.key as keyof typeof eval_] as number),
                    0
                  ) / ATTRIBUTES.length
                : 0;
              const scores: Record<string, number> = {};
              if (eval_) {
                ATTRIBUTES.forEach((a) => {
                  scores[a.key] = eval_[a.key as keyof typeof eval_] as number;
                });
              }

              return (
                <Link key={us.id} href={`/my/songs/${us.id}`}>
                  <div className="bg-card rounded-xl p-4 border border-border transition-shadow cursor-pointer">
                    <div className="flex gap-4">
                      <div className="shrink-0">
                        {eval_ ? (
                          <MiniRadarChart scores={scores} />
                        ) : (
                          <div className="w-[100px] h-[100px] flex items-center justify-center text-toss-gray-400 text-xs">
                            미평가
                          </div>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-toss-gray-900 truncate">
                          {us.song.title}
                        </div>
                        <div className="text-sm text-toss-gray-500">
                          {us.song.composer}
                        </div>
                        <Badge
                          className={`mt-2 ${STATUS_COLORS[us.status]} text-white text-xs`}
                        >
                          {STATUS_LABELS[us.status]}
                        </Badge>
                        {eval_ && (
                          <div className="mt-2">
                            <div className="flex items-center gap-2">
                              <div className="flex-1 h-1.5 bg-toss-gray-100 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-toss-blue rounded-full"
                                  style={{
                                    width: `${(avg / 5) * 100}%`,
                                  }}
                                />
                              </div>
                              <span className="text-xs font-medium text-toss-gray-600">
                                {avg.toFixed(1)}
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
