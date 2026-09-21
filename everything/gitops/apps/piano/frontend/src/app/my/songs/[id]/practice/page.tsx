"use client";

import { useState, useEffect, use } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, {
  ATTRIBUTES,
  type UserSong,
  type PracticeSession,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { extractYouTubeId, buildEmbedUrl, formatSeconds } from "@/lib/youtube";
import { paddedMeasureStartToAudio } from "@/lib/measure-timing";
import { EditPracticeSessionForm } from "@/components/edit-practice-session-form";
import { SheetMusicMeasurePicker } from "@/components/sheet-music-picker";
import Link from "next/link";

const LABEL: Record<string, string> = Object.fromEntries(
  ATTRIBUTES.map((a) => [a.key, a.label])
);

function fmtDuration(sec: number | null): string {
  if (sec === null) return "-";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}

function rangeText(s: PracticeSession): string {
  if (s.measure_start === null && s.measure_end === null) return "곡 전체";
  if (s.measure_start !== null && s.measure_end !== null)
    return `${s.measure_start}–${s.measure_end}마디`;
  return `${s.measure_start ?? s.measure_end}마디`;
}

function audioStartText(s: PracticeSession): string | null {
  if (s.audio_start_seconds == null) return null;
  return formatSeconds(s.audio_start_seconds);
}

export default function PracticePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const queryClient = useQueryClient();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [wholeSong, setWholeSong] = useState(false);
  const [measureStart, setMeasureStart] = useState("");
  const [measureEnd, setMeasureEnd] = useState("");
  const [comment, setComment] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const { data: userSong } = useQuery<UserSong>({
    queryKey: ["my-song", id],
    queryFn: () => api.get(`/api/my/songs/${id}`).then((r) => r.data),
  });

  const { data: sessions = [] } = useQuery<PracticeSession[]>({
    queryKey: ["practice-sessions", id],
    queryFn: () =>
      api.get(`/api/my/songs/${id}/practice-sessions`).then((r) => r.data),
  });

  const active = sessions.find((s) => s.completed_at === null) ?? null;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["practice-sessions", id] });
  };

  const resetSetup = () => {
    setComment("");
    setSelected(new Set());
    setWholeSong(false);
    setMeasureStart("");
    setMeasureEnd("");
  };

  const startMut = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post(`/api/my/songs/${id}/practice-sessions`, data),
    onSuccess: invalidate,
  });

  const completeMut = useMutation({
    mutationFn: ({
      sessionId,
      data,
    }: {
      sessionId: string;
      data: Record<string, unknown>;
    }) =>
      api.post(
        `/api/my/songs/${id}/practice-sessions/${sessionId}/complete`,
        data
      ),
    onSuccess: () => {
      invalidate();
      resetSetup();
    },
  });

  const cancelMut = useMutation({
    mutationFn: (sessionId: string) =>
      api.delete(`/api/my/songs/${id}/practice-sessions/${sessionId}`),
    onSuccess: () => {
      invalidate();
      resetSetup();
    },
  });

  if (!userSong) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-toss-gray-400">Loading...</div>
      </div>
    );
  }

  const toggleMetric = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const startValid =
    wholeSong ||
    (measureStart !== "" &&
      measureEnd !== "" &&
      Number(measureStart) >= 1 &&
      Number(measureEnd) >= Number(measureStart));

  // 시작 마디 → 음원 시작 (앞 1마디 lead-in 포함). end 는 열어둠 — 구간 지나도
  // 영상이 끊기지 않고 계속 들리도록.
  const anchors = userSong?.song.measure_timestamps ?? null;
  const measureRangeValid =
    !wholeSong &&
    measureStart !== "" &&
    measureEnd !== "" &&
    Number(measureStart) >= 1 &&
    Number(measureEnd) >= Number(measureStart);
  const derivedStart = measureRangeValid
    ? paddedMeasureStartToAudio(Number(measureStart), anchors)
    : null;
  const audioStartSec =
    derivedStart === null ? null : Math.max(0, Math.round(derivedStart));

  const handleStart = () => {
    if (!startValid) return;
    startMut.mutate({
      metrics: Array.from(selected),
      measure_start: wholeSong ? null : Number(measureStart),
      measure_end: wholeSong ? null : Number(measureEnd),
      audio_start_seconds: audioStartSec,
      audio_end_seconds: null,
    });
  };

  const handleComplete = () => {
    if (!active) return;
    completeMut.mutate({
      sessionId: active.id,
      data: { comment: comment || null },
    });
  };

  const elapsed = active
    ? Math.max(
        0,
        Math.floor((now - new Date(active.started_at).getTime()) / 1000)
      )
    : 0;

  const completed = sessions.filter((s) => s.completed_at !== null);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/my/songs/${id}`}
          className="text-sm text-toss-gray-500 hover:text-toss-gray-700 mb-2 inline-flex items-center gap-1 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
          {userSong.song.title}
        </Link>
        <h1 className="text-2xl font-semibold text-toss-gray-900">연습</h1>
        <p className="text-sm text-toss-gray-500 mt-1">
          {userSong.song.composer}
        </p>
      </div>

      {!active ? (
        /* ── 설정 ── */
        <div className="bg-card rounded-xl p-6 border border-border space-y-5">
          <div>
            <h2 className="text-base font-semibold text-toss-gray-900 mb-3">
              연습할 지표
            </h2>
            <div className="flex flex-wrap gap-2">
              {ATTRIBUTES.map((a) => {
                const on = selected.has(a.key);
                return (
                  <button
                    key={a.key}
                    type="button"
                    onClick={() => toggleMetric(a.key)}
                    className={`px-3 h-8 rounded-md text-[13px] font-medium transition-all ${
                      on
                        ? "bg-toss-blue text-white"
                        : "bg-toss-gray-100 text-toss-gray-500 hover:bg-toss-gray-200"
                    }`}
                  >
                    {a.label}
                  </button>
                );
              })}
            </div>
            {selected.size > 0 && (
              <div className="mt-4 space-y-2">
                {ATTRIBUTES.filter((a) => selected.has(a.key)).map((a) => (
                  <div key={a.key}>
                    <span className="text-sm font-medium text-toss-gray-700">
                      {a.label}
                    </span>
                    <p className="text-xs text-toss-gray-400 mt-0.5">
                      {a.description}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <Separator />

          <div>
            <h2 className="text-base font-semibold text-toss-gray-900 mb-3">
              마디 범위
            </h2>
            <div className="flex items-center gap-2 mb-3">
              <button
                type="button"
                onClick={() => setWholeSong(true)}
                className={`px-3 h-8 rounded-md text-[13px] font-medium transition-all ${
                  wholeSong
                    ? "bg-toss-blue text-white"
                    : "bg-toss-gray-100 text-toss-gray-500 hover:bg-toss-gray-200"
                }`}
              >
                곡 전체
              </button>
              <button
                type="button"
                onClick={() => setWholeSong(false)}
                className={`px-3 h-8 rounded-md text-[13px] font-medium transition-all ${
                  !wholeSong
                    ? "bg-toss-blue text-white"
                    : "bg-toss-gray-100 text-toss-gray-500 hover:bg-toss-gray-200"
                }`}
              >
                마디 지정
              </button>
            </div>
            {!wholeSong && (
              <div className="space-y-3">
                {userSong.song.full_abc && (
                  <SheetMusicMeasurePicker
                    abc={userSong.song.full_abc}
                    pageBreaks={userSong.song.page_breaks}
                    value={
                      measureStart !== "" &&
                      measureEnd !== "" &&
                      Number(measureStart) >= 1 &&
                      Number(measureEnd) >= Number(measureStart)
                        ? {
                            start: Number(measureStart),
                            end: Number(measureEnd),
                          }
                        : null
                    }
                    onChange={(range) => {
                      if (range === null) {
                        setMeasureStart("");
                        setMeasureEnd("");
                      } else {
                        setMeasureStart(String(range.start));
                        setMeasureEnd(String(range.end));
                      }
                    }}
                  />
                )}
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    inputMode="numeric"
                    min={1}
                    placeholder="시작 마디"
                    value={measureStart}
                    onChange={(e) => setMeasureStart(e.target.value)}
                    className="flex-1 min-w-0"
                  />
                  <span className="text-toss-gray-400">–</span>
                  <Input
                    type="number"
                    inputMode="numeric"
                    min={1}
                    placeholder="끝 마디"
                    value={measureEnd}
                    onChange={(e) => setMeasureEnd(e.target.value)}
                    className="flex-1 min-w-0"
                  />
                </div>
              </div>
            )}
          </div>

          {userSong.song.youtube_url && !wholeSong && audioStartSec != null && (
            <p className="text-xs text-toss-gray-500">
              음원 시작 (앞 1마디 lead-in):{" "}
              <span className="font-medium text-toss-gray-700 tabular-nums">
                {formatSeconds(audioStartSec)}
              </span>
            </p>
          )}

          {userSong.song.youtube_url &&
            measureRangeValid &&
            derivedStart === null && (
              <p className="text-xs text-toss-orange">
                마디 timestamp가 부족합니다. 곡 상세에서 마디별 시간을 설정하세요.
              </p>
            )}

          <Button
            className="w-full bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md h-9 text-sm font-medium"
            onClick={handleStart}
            disabled={!startValid || startMut.isPending}
          >
            {startMut.isPending ? "시작 중..." : "시작"}
          </Button>
        </div>
      ) : (
        /* ── 진행 중 ── */
        <div className="bg-card rounded-xl p-6 border border-border space-y-5">
          <div className="text-center">
            <p className="text-sm text-toss-gray-500 mb-1">
              {rangeText(active)} ·{" "}
              {active.metrics.length > 0
                ? active.metrics.map((m) => LABEL[m] ?? m).join(", ")
                : "지표 없음"}
            </p>
            <div className="text-5xl font-semibold text-toss-gray-900 tabular-nums tracking-tight">
              {String(Math.floor(elapsed / 60)).padStart(2, "0")}:
              {String(elapsed % 60).padStart(2, "0")}
            </div>
          </div>

          {userSong.song.youtube_url &&
            active.audio_start_seconds != null &&
            (() => {
              const vid = extractYouTubeId(userSong.song.youtube_url);
              if (!vid) return null;
              return (
                <div className="aspect-video w-full overflow-hidden rounded-lg">
                  <iframe
                    src={buildEmbedUrl(vid, {
                      start: active.audio_start_seconds,
                      autoplay: true,
                    })}
                    title="Practice audio segment"
                    className="w-full h-full"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                </div>
              );
            })()}

          <Textarea
            placeholder="메모 (선택사항)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="resize-none"
            rows={2}
          />

          <div className="flex gap-2">
            <Button
              variant="outline"
              className="flex-1 rounded-md h-9 border-toss-gray-200 text-toss-gray-600"
              onClick={() => cancelMut.mutate(active.id)}
              disabled={cancelMut.isPending || completeMut.isPending}
            >
              취소
            </Button>
            <Button
              className="flex-1 bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md h-9 text-sm font-medium"
              onClick={handleComplete}
              disabled={completeMut.isPending}
            >
              {completeMut.isPending ? "저장 중..." : "기록 저장"}
            </Button>
          </div>
        </div>
      )}

      {/* ── 기록 ── */}
      <div className="bg-card rounded-xl p-6 border border-border">
        <h2 className="text-base font-semibold text-toss-gray-900 mb-4">
          연습 기록
        </h2>
        {completed.length === 0 ? (
          <p className="text-sm text-toss-gray-400">아직 연습 기록이 없습니다.</p>
        ) : (
          <div className="space-y-3">
            {completed.map((s) => {
              const audio = audioStartText(s);
              return (
                <div
                  key={s.id}
                  className="py-2 border-b border-toss-gray-100 last:border-0"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-toss-gray-900">
                        {rangeText(s)} ·{" "}
                        {s.metrics.length > 0
                          ? s.metrics.map((m) => LABEL[m] ?? m).join(", ")
                          : "지표 없음"}
                      </p>
                      <p className="text-xs text-toss-gray-500 mt-0.5">
                        {new Date(s.started_at).toLocaleString("ko-KR", {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                        {audio && ` · 음원 ${audio}~`}
                      </p>
                      {s.comment && (
                        <p className="text-xs text-toss-gray-500 mt-0.5">
                          {s.comment}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-sm font-semibold text-toss-blue whitespace-nowrap tabular-nums">
                        {fmtDuration(s.duration_seconds)}
                      </span>
                      <button
                        type="button"
                        onClick={() =>
                          setEditingId((cur) => (cur === s.id ? null : s.id))
                        }
                        className="text-xs text-toss-gray-500 hover:text-toss-gray-700 px-2 h-7 rounded-md hover:bg-toss-gray-100"
                      >
                        {editingId === s.id ? "닫기" : "편집"}
                      </button>
                    </div>
                  </div>
                  {editingId === s.id && (
                    <EditPracticeSessionForm
                      userSongId={id}
                      session={s}
                      hasYoutube={!!userSong.song.youtube_url}
                      anchors={anchors}
                      fullAbc={userSong.song.full_abc}
                      pageBreaks={userSong.song.page_breaks}
                      onClose={() => setEditingId(null)}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
