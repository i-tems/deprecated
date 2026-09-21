"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api, { type Song } from "@/lib/api";
import { MiniRadarChart } from "@/components/radar-chart";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Link from "next/link";

const difficultyColor = (d: number) => {
  if (d <= 3) return "bg-emerald-50 text-toss-green";
  if (d <= 6) return "bg-orange-50 text-toss-orange";
  return "bg-red-50 text-toss-red";
};

export default function SongCatalogPage() {
  const [search, setSearch] = useState("");

  const { data } = useQuery<{ items: Song[]; total: number }>({
    queryKey: ["songs", search],
    queryFn: () =>
      api
        .get("/api/songs", { params: { search: search || undefined, size: 100 } })
        .then((r) => r.data),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-toss-gray-900">곡 카탈로그</h1>
        <p className="text-sm text-toss-gray-500 mt-1">
          곡을 탐색하고 분석 정보를 확인하세요
        </p>
      </div>

      <Input
        placeholder="곡 이름 또는 작곡가 검색..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-md"
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {data?.items.map((song) => (
          <Link key={song.id} href={`/songs/${song.id}`}>
            <div className="bg-card rounded-xl p-5 border border-border transition-shadow cursor-pointer h-full">
              <div className="flex items-start gap-4">
                {song.required_skills &&
                  Object.keys(song.required_skills).length > 0 ? (
                  <div className="shrink-0">
                    <MiniRadarChart scores={song.required_skills} />
                  </div>
                ) : (
                  <div className="w-[100px] h-[100px] flex items-center justify-center text-toss-gray-300 text-xs bg-toss-gray-50 rounded-xl shrink-0">
                    미설정
                  </div>
                )}
                <div className="flex-1 min-w-0 space-y-2">
                  <div>
                    <div className="font-semibold text-base text-toss-gray-900 truncate">
                      {song.title}
                    </div>
                    <div className="text-sm text-toss-gray-500 mt-0.5">
                      {song.composer}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge className={difficultyColor(song.difficulty)}>
                      난이도 {song.difficulty}/10
                    </Badge>
                    {song.genre && (
                      <Badge variant="outline" className="text-xs border-toss-gray-200 text-toss-gray-600">
                        {song.genre}
                      </Badge>
                    )}
                  </div>
                  {song.estimated_weeks && (
                    <div className="text-xs text-toss-gray-500">
                      예상 학습 기간: {song.estimated_weeks}주
                    </div>
                  )}
                </div>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {data?.items.length === 0 && (
        <div className="text-center text-toss-gray-400 py-16 text-sm">
          검색 결과가 없습니다
        </div>
      )}
    </div>
  );
}
