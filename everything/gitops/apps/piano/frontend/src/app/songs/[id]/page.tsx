"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { ATTRIBUTES, type Song } from "@/lib/api";
import { SkillRadarChart } from "@/components/radar-chart";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { SheetMusicSection } from "@/components/sheet-music";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";
import { extractYouTubeId, buildEmbedUrl } from "@/lib/youtube";
import { MeasureTimestampsEditor } from "@/components/measure-timestamps-editor";
import Link from "next/link";

const difficultyColor = (d: number) => {
  if (d <= 3) return "bg-emerald-50 text-toss-green";
  if (d <= 6) return "bg-orange-50 text-toss-orange";
  return "bg-red-50 text-toss-red";
};

const difficultyLabel = (d: number) => {
  if (d <= 2) return "입문";
  if (d <= 4) return "초급";
  if (d <= 6) return "중급";
  if (d <= 8) return "상급";
  return "최상급";
};

export default function SongDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [editingYoutube, setEditingYoutube] = useState(false);
  const [youtubeDraft, setYoutubeDraft] = useState("");
  const [editingAnchors, setEditingAnchors] = useState(false);
  const [editingFullAbc, setEditingFullAbc] = useState(false);
  const [fullAbcDraft, setFullAbcDraft] = useState("");
  const [editingPageBreaks, setEditingPageBreaks] = useState(false);
  const [pageBreaksDraft, setPageBreaksDraft] = useState("");

  const { data: song } = useQuery<Song>({
    queryKey: ["song", id],
    queryFn: () => api.get(`/api/songs/${id}`).then((r) => r.data),
  });

  const saveYoutube = useMutation({
    mutationFn: (url: string | null) =>
      api.put(`/api/admin/songs/${id}`, { youtube_url: url }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["song", id] });
      setEditingYoutube(false);
    },
  });

  const saveFullAbc = useMutation({
    mutationFn: (abc: string | null) =>
      api.put(`/api/admin/songs/${id}`, { full_abc: abc }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["song", id] });
      setEditingFullAbc(false);
    },
  });

  const savePageBreaks = useMutation({
    mutationFn: (breaks: number[] | null) =>
      api.put(`/api/admin/songs/${id}`, { page_breaks: breaks }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["song", id] });
      setEditingPageBreaks(false);
    },
  });

  if (!song) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-toss-gray-400">Loading...</div>
      </div>
    );
  }

  const reqSkills = song.required_skills;
  const avgRequired = reqSkills
    ? (
        Object.values(reqSkills).reduce((a, b) => a + b, 0) /
        Object.values(reqSkills).length
      ).toFixed(1)
    : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          href="/songs"
          className="text-sm text-toss-gray-500 hover:text-toss-gray-700 mb-2 inline-flex items-center gap-1 transition-colors"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15.75 19.5L8.25 12l7.5-7.5"
            />
          </svg>
          곡 카탈로그
        </Link>
        <h1 className="text-2xl font-semibold text-toss-gray-900">{song.title}</h1>
        <p className="text-base text-toss-gray-500 mt-1">{song.composer}</p>
        <div className="flex items-center gap-2 mt-3 flex-wrap">
          <Badge className={difficultyColor(song.difficulty)}>
            난이도 {song.difficulty}/10 · {difficultyLabel(song.difficulty)}
          </Badge>
          {song.genre && (
            <Badge
              variant="outline"
              className="border-toss-gray-200 text-toss-gray-600"
            >
              {song.genre}
            </Badge>
          )}
          {song.estimated_weeks && (
            <Badge
              variant="outline"
              className="border-toss-gray-200 text-toss-gray-600"
            >
              약 {song.estimated_weeks}주
            </Badge>
          )}
        </div>
      </div>

      {/* Overview Cards */}
      {reqSkills && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-card rounded-xl p-4 border border-border text-center">
            <div className="text-2xl font-semibold text-toss-blue">
              {avgRequired}
            </div>
            <div className="text-xs text-toss-gray-500 mt-1">평균 요구 수준</div>
          </div>
          <div className="bg-card rounded-xl p-4 border border-border text-center">
            <div className="text-2xl font-semibold text-toss-red">
              {Math.max(...Object.values(reqSkills))}
            </div>
            <div className="text-xs text-toss-gray-500 mt-1">최고 요구 수준</div>
          </div>
          <div className="bg-card rounded-xl p-4 border border-border text-center">
            <div className="text-2xl font-semibold text-toss-green">
              {Math.min(...Object.values(reqSkills))}
            </div>
            <div className="text-xs text-toss-gray-500 mt-1">최저 요구 수준</div>
          </div>
          <div className="bg-card rounded-xl p-4 border border-border text-center">
            <div className="text-2xl font-semibold text-toss-orange">
              {song.estimated_weeks || "—"}
              <span className="text-sm font-normal text-toss-gray-400">주</span>
            </div>
            <div className="text-xs text-toss-gray-500 mt-1">예상 학습 기간</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Required Skills Radar */}
        {reqSkills && (
          <div className="bg-card rounded-xl p-6 border border-border lg:col-span-1">
            <h2 className="text-base font-semibold text-toss-gray-900 mb-4">
              요구 역량 분석
            </h2>
            <SkillRadarChart scores={reqSkills} size={280} />
            <div className="space-y-2.5 mt-5">
              {ATTRIBUTES.map((attr) => {
                const level = reqSkills[attr.key] || 0;
                const pct = (level / 5) * 100;
                return (
                  <div key={attr.key} className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-toss-gray-600">
                        {attr.label}
                      </span>
                      <span className="text-xs font-semibold text-toss-gray-700">
                        {level}/5
                      </span>
                    </div>
                    <div className="h-1.5 bg-toss-gray-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          level >= 4
                            ? "bg-toss-blue"
                            : level >= 3
                              ? "bg-toss-green"
                              : "bg-toss-gray-300"
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Analysis */}
        <div
          className={`bg-card rounded-xl p-6 border border-border ${reqSkills ? "lg:col-span-2" : "lg:col-span-3"}`}
        >
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">
            곡 분석
          </h2>
          {song.analysis_text ? (
            <MarkdownRenderer content={song.analysis_text} />
          ) : (
            <p className="text-sm text-toss-gray-400">
              분석 정보가 없습니다.
            </p>
          )}
        </div>
      </div>

      {/* Practice Tips */}
      {song.practice_tips && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">
            연습 가이드
          </h2>
          <MarkdownRenderer content={song.practice_tips} />
        </div>
      )}

      {/* Sheet Music Snippets */}
      {song.sheet_snippets && song.sheet_snippets.length > 0 && (
        <SheetMusicSection snippets={song.sheet_snippets} />
      )}

      {/* 전체 악보 ABC (연습 화면 마디 선택용) */}
      {(song.full_abc || user?.is_admin) && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-toss-gray-900">
              전체 악보 ABC
            </h2>
            {user?.is_admin && !editingFullAbc && (
              <Button
                size="sm"
                variant="ghost"
                className="text-xs text-toss-gray-500 hover:text-toss-gray-700"
                onClick={() => {
                  setFullAbcDraft(song.full_abc ?? "");
                  setEditingFullAbc(true);
                }}
              >
                {song.full_abc ? "편집" : "추가"}
              </Button>
            )}
          </div>
          {editingFullAbc ? (
            <div className="space-y-3">
              <textarea
                value={fullAbcDraft}
                onChange={(e) => setFullAbcDraft(e.target.value)}
                placeholder={"X:1\nT:Title\nM:4/4\nL:1/8\nK:C\n|GABc dedB|...|"}
                className="w-full h-64 text-xs font-mono border border-toss-gray-200 rounded-md p-3"
              />
              <p className="text-xs text-toss-gray-500">
                ABC notation 표준. 연습 화면에서 이 악보를 클릭해 마디 범위를 선택할 수 있습니다.
              </p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  className="bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md"
                  onClick={() => {
                    const v = fullAbcDraft.trim();
                    saveFullAbc.mutate(v === "" ? null : v);
                  }}
                  disabled={saveFullAbc.isPending}
                >
                  {saveFullAbc.isPending ? "저장 중..." : "저장"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-md border-toss-gray-200 text-toss-gray-600"
                  onClick={() => setEditingFullAbc(false)}
                  disabled={saveFullAbc.isPending}
                >
                  취소
                </Button>
                {song.full_abc && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="rounded-md border-toss-red text-toss-red ml-auto"
                    onClick={() => saveFullAbc.mutate(null)}
                    disabled={saveFullAbc.isPending}
                  >
                    제거
                  </Button>
                )}
              </div>
            </div>
          ) : song.full_abc ? (
            <p className="text-sm text-toss-gray-600">
              등록됨 · 연습 화면에서 마디 클릭 선택 가능
            </p>
          ) : (
            <p className="text-sm text-toss-gray-400">
              전체 악보 ABC가 없습니다. 추가하면 연습 시 마디를 악보에서 직접 클릭해 선택할 수 있습니다.
            </p>
          )}

          {/* 페이지 분할 — full_abc 가 있을 때만 의미 있음 */}
          {song.full_abc && (
            <div className="mt-4 pt-4 border-t border-toss-gray-100">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-toss-gray-800">
                  페이지 분할
                </h3>
                {user?.is_admin && !editingPageBreaks && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-xs text-toss-gray-500 hover:text-toss-gray-700"
                    onClick={() => {
                      setPageBreaksDraft(
                        song.page_breaks ? song.page_breaks.join(",") : "",
                      );
                      setEditingPageBreaks(true);
                    }}
                  >
                    {song.page_breaks ? "편집" : "추가"}
                  </Button>
                )}
              </div>
              {editingPageBreaks ? (
                <div className="space-y-2">
                  <Input
                    value={pageBreaksDraft}
                    onChange={(e) => setPageBreaksDraft(e.target.value)}
                    placeholder="예: 6,7,7,6"
                    className="text-sm"
                  />
                  <p className="text-xs text-toss-gray-500">
                    페이지별 system(줄) 개수를 쉼표로 구분. 합이 총 system 수보다
                    적으면 남는 system 은 마지막 페이지에 모입니다. 비우면 페이지
                    분할 없이 한 SVG 로 렌더됩니다.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md"
                      onClick={() => {
                        const trimmed = pageBreaksDraft.trim();
                        if (trimmed === "") {
                          savePageBreaks.mutate(null);
                          return;
                        }
                        const parts = trimmed.split(",").map((s) => s.trim());
                        const nums: number[] = [];
                        for (const p of parts) {
                          const n = Number(p);
                          if (!Number.isInteger(n) || n < 1) {
                            alert(`잘못된 값: "${p}" — 1 이상의 정수만 허용됩니다.`);
                            return;
                          }
                          nums.push(n);
                        }
                        savePageBreaks.mutate(nums);
                      }}
                      disabled={savePageBreaks.isPending}
                    >
                      {savePageBreaks.isPending ? "저장 중..." : "저장"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-md border-toss-gray-200 text-toss-gray-600"
                      onClick={() => setEditingPageBreaks(false)}
                      disabled={savePageBreaks.isPending}
                    >
                      취소
                    </Button>
                    {song.page_breaks && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="rounded-md border-toss-red text-toss-red ml-auto"
                        onClick={() => savePageBreaks.mutate(null)}
                        disabled={savePageBreaks.isPending}
                      >
                        제거
                      </Button>
                    )}
                  </div>
                </div>
              ) : song.page_breaks ? (
                <p className="text-sm text-toss-gray-600">
                  {song.page_breaks.join(" + ")} ={" "}
                  {song.page_breaks.reduce((a, b) => a + b, 0)} systems ·{" "}
                  {song.page_breaks.length} 페이지
                </p>
              ) : (
                <p className="text-sm text-toss-gray-400">
                  페이지 분할 없음 — 전체를 한 SVG 로 렌더합니다.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* YouTube 기준 음원 */}
      {(song.youtube_url || user?.is_admin) && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-toss-gray-900">
              기준 음원
            </h2>
            {user?.is_admin && !editingYoutube && (
              <Button
                size="sm"
                variant="ghost"
                className="text-xs text-toss-gray-500 hover:text-toss-gray-700"
                onClick={() => {
                  setYoutubeDraft(song.youtube_url ?? "");
                  setEditingYoutube(true);
                }}
              >
                {song.youtube_url ? "변경" : "추가"}
              </Button>
            )}
          </div>
          {editingYoutube ? (
            <div className="space-y-3">
              <Input
                placeholder="https://www.youtube.com/watch?v=..."
                value={youtubeDraft}
                onChange={(e) => setYoutubeDraft(e.target.value)}
              />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  className="bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md"
                  onClick={() => {
                    const v = youtubeDraft.trim();
                    saveYoutube.mutate(v === "" ? null : v);
                  }}
                  disabled={saveYoutube.isPending}
                >
                  {saveYoutube.isPending ? "저장 중..." : "저장"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-md border-toss-gray-200 text-toss-gray-600"
                  onClick={() => setEditingYoutube(false)}
                  disabled={saveYoutube.isPending}
                >
                  취소
                </Button>
                {song.youtube_url && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="rounded-md border-toss-red text-toss-red"
                    onClick={() => saveYoutube.mutate(null)}
                    disabled={saveYoutube.isPending}
                  >
                    제거
                  </Button>
                )}
              </div>
            </div>
          ) : song.youtube_url ? (
            (() => {
              const vid = extractYouTubeId(song.youtube_url);
              return vid ? (
                <div className="aspect-video w-full overflow-hidden rounded-lg">
                  <iframe
                    src={buildEmbedUrl(vid)}
                    title="YouTube reference recording"
                    className="w-full h-full"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                </div>
              ) : (
                <a
                  href={song.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-toss-blue hover:underline break-all"
                >
                  {song.youtube_url}
                </a>
              );
            })()
          ) : (
            <p className="text-sm text-toss-gray-400">
              YouTube URL이 설정되지 않았습니다.
            </p>
          )}
        </div>
      )}

      {/* 마디 timestamp 앵커 */}
      {((song.measure_timestamps && song.measure_timestamps.length > 0) ||
        user?.is_admin) && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-toss-gray-900">
              마디 timestamp
            </h2>
            {user?.is_admin && !editingAnchors && (
              <Button
                size="sm"
                variant="ghost"
                className="text-xs text-toss-gray-500 hover:text-toss-gray-700"
                onClick={() => setEditingAnchors(true)}
              >
                편집
              </Button>
            )}
          </div>
          {editingAnchors ? (
            <MeasureTimestampsEditor
              songId={id}
              initial={song.measure_timestamps}
              onDone={() => setEditingAnchors(false)}
            />
          ) : song.measure_timestamps && song.measure_timestamps.length > 0 ? (
            <p className="text-sm text-toss-gray-600">
              {song.measure_timestamps.length}개 마디 timestamp 설정됨 ·{" "}
              <span className="text-toss-gray-400">
                {Math.min(...song.measure_timestamps.map((a) => a.measure))}–
                {Math.max(...song.measure_timestamps.map((a) => a.measure))}마디
              </span>
            </p>
          ) : (
            <p className="text-sm text-toss-gray-400">
              마디 timestamp가 설정되지 않았습니다. 연습 시 음원 자동 구간 산출이 불가합니다.
            </p>
          )}
        </div>
      )}

      {/* Reference URLs */}
      {song.reference_urls && song.reference_urls.length > 0 && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">
            참고 자료
          </h2>
          <div className="space-y-2">
            {song.reference_urls.map((ref, i) => (
              <a
                key={i}
                href={ref.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 p-3 rounded-xl bg-toss-gray-50 hover:bg-toss-blue-light transition-colors group"
              >
                <svg
                  className="w-4 h-4 text-toss-gray-400 group-hover:text-toss-blue shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m9.07-9.07l4.5-4.5a4.5 4.5 0 016.364 6.364l-1.757 1.757"
                  />
                </svg>
                <span className="text-sm text-toss-gray-600 group-hover:text-toss-blue truncate">
                  {ref.label}
                </span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
