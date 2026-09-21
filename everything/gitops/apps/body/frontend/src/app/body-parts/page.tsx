"use client";

import { useQuery } from "@tanstack/react-query";
import { getOverview, getConfig } from "@/lib/api";
import Link from "next/link";
import AttributeBarChart from "@/components/attribute-bar-chart";

export default function BodyPartsPage() {
  const { data: overview, isLoading: lo } = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
  });
  const { data: config, isLoading: lc } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });

  if (lo || lc) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-text-tertiary text-sm">로딩 중...</div>
      </div>
    );
  }

  if (!overview || !config) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <p className="text-text-secondary">데이터를 불러올 수 없습니다</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-[22px] font-bold text-text-primary">부위 목록</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {config.body_parts.map((bp) => {
          const score = overview.part_scores.find(
            (ps) => ps.part_id === bp.id
          );
          const current = {
            strength: score?.strength ?? 0,
            development: score?.development ?? 0,
            mmc: score?.mmc ?? 0,
          };

          return (
            <Link
              key={bp.id}
              href={`/body-parts/${bp.id}`}
              className="block bg-white rounded-2xl border border-border p-5 hover:border-text-tertiary hover:shadow-sm transition-all group"
            >
              <div className="flex items-start justify-between mb-4">
                <h3 className="text-[15px] font-semibold text-text-primary group-hover:text-brand transition-colors">
                  {bp.name}
                </h3>
              </div>

              <AttributeBarChart current={current} />

              <div className="mt-3 flex justify-between items-center pt-3 border-t border-border-light">
                <span className="text-[12px] text-text-tertiary">
                  총합 {score?.total.toFixed(1) ?? "0.0"}
                </span>
                <span className="text-[12px] text-text-tertiary group-hover:text-brand transition-colors">
                  상세 보기 →
                </span>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
