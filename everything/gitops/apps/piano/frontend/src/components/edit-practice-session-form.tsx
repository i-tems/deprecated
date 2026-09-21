"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api, { ATTRIBUTES, type PracticeSession } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { formatSeconds } from "@/lib/youtube";
import {
  paddedMeasureStartToAudio,
  type MeasureAnchor,
} from "@/lib/measure-timing";
import { SheetMusicMeasurePicker } from "@/components/sheet-music-picker";

// datetime-local input expects "YYYY-MM-DDTHH:MM" in the browser's local timezone.
// We convert ISO to local, and back to ISO on submit.
function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function localInputToIso(s: string): string | null {
  if (s === "") return null;
  const d = new Date(s);
  if (isNaN(d.getTime())) return null;
  return d.toISOString();
}

interface Props {
  userSongId: string;
  session: PracticeSession;
  hasYoutube: boolean;
  anchors: MeasureAnchor[] | null;
  fullAbc: string | null;
  pageBreaks: number[] | null;
  onClose: () => void;
}

export function EditPracticeSessionForm({
  userSongId,
  session,
  hasYoutube,
  anchors,
  fullAbc,
  pageBreaks,
  onClose,
}: Props) {
  const queryClient = useQueryClient();

  const [metrics, setMetrics] = useState<Set<string>>(
    () => new Set(session.metrics)
  );
  const [wholeSong, setWholeSong] = useState(
    session.measure_start === null && session.measure_end === null
  );
  const [measureStart, setMeasureStart] = useState(
    session.measure_start?.toString() ?? ""
  );
  const [measureEnd, setMeasureEnd] = useState(
    session.measure_end?.toString() ?? ""
  );
  const [scores, setScores] = useState<Record<string, number>>(
    () => ({ ...(session.scores ?? {}) })
  );
  const [comment, setComment] = useState(session.comment ?? "");
  const [startedAtLocal, setStartedAtLocal] = useState(
    isoToLocalInput(session.started_at)
  );
  const [completedAtLocal, setCompletedAtLocal] = useState(
    isoToLocalInput(session.completed_at)
  );

  const toggleMetric = (key: string) => {
    setMetrics((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
        setScores((s) => {
          const ns = { ...s };
          delete ns[key];
          return ns;
        });
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const measureValid =
    wholeSong ||
    (measureStart !== "" &&
      measureEnd !== "" &&
      Number(measureStart) >= 1 &&
      Number(measureEnd) >= Number(measureStart));

  // 시작 마디 → 음원 시작 (앞 1마디 lead-in). end 는 열어둠.
  const derivedStart =
    !wholeSong && measureValid
      ? paddedMeasureStartToAudio(Number(measureStart), anchors)
      : null;
  const audioStartSec =
    derivedStart === null ? null : Math.max(0, Math.round(derivedStart));

  const startedIso = localInputToIso(startedAtLocal);
  const completedIso = localInputToIso(completedAtLocal);
  const timeValid =
    startedIso !== null &&
    (completedIso === null ||
      new Date(completedIso).getTime() >= new Date(startedIso).getTime());

  const formValid = measureValid && timeValid;

  const updateMut = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch(
        `/api/my/songs/${userSongId}/practice-sessions/${session.id}`,
        body
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["practice-sessions", userSongId],
      });
      onClose();
    },
  });

  const handleSave = () => {
    if (!formValid) return;
    const scoresPayload = Object.keys(scores).length > 0 ? scores : null;
    updateMut.mutate({
      metrics: Array.from(metrics),
      measure_start: wholeSong ? null : Number(measureStart),
      measure_end: wholeSong ? null : Number(measureEnd),
      audio_start_seconds: audioStartSec,
      audio_end_seconds: null,
      scores: scoresPayload,
      comment: comment === "" ? null : comment,
      started_at: startedIso,
      completed_at: completedIso,
    });
  };

  return (
    <div className="mt-3 p-4 rounded-lg border border-toss-blue/30 bg-toss-blue-light/30 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-toss-gray-900 mb-2">메트릭</h3>
        <div className="flex flex-wrap gap-1.5">
          {ATTRIBUTES.map((a) => {
            const on = metrics.has(a.key);
            return (
              <button
                key={a.key}
                type="button"
                onClick={() => toggleMetric(a.key)}
                className={`px-2.5 h-7 rounded-md text-[12px] font-medium transition-all ${
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
      </div>

      <Separator />

      <div>
        <h3 className="text-sm font-semibold text-toss-gray-900 mb-2">
          마디 범위
        </h3>
        <div className="flex items-center gap-2 mb-2">
          <button
            type="button"
            onClick={() => setWholeSong(true)}
            className={`px-2.5 h-7 rounded-md text-[12px] font-medium transition-all ${
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
            className={`px-2.5 h-7 rounded-md text-[12px] font-medium transition-all ${
              !wholeSong
                ? "bg-toss-blue text-white"
                : "bg-toss-gray-100 text-toss-gray-500 hover:bg-toss-gray-200"
            }`}
          >
            마디 지정
          </button>
        </div>
        {!wholeSong && (
          <div className="space-y-2">
            {fullAbc && (
              <SheetMusicMeasurePicker
                abc={fullAbc}
                pageBreaks={pageBreaks}
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
                placeholder="시작"
                value={measureStart}
                onChange={(e) => setMeasureStart(e.target.value)}
                className="flex-1 min-w-0"
              />
              <span className="text-toss-gray-400">–</span>
              <Input
                type="number"
                inputMode="numeric"
                min={1}
                placeholder="끝"
                value={measureEnd}
                onChange={(e) => setMeasureEnd(e.target.value)}
                className="flex-1 min-w-0"
              />
            </div>
          </div>
        )}
      </div>

      {hasYoutube && audioStartSec != null && (
        <p className="text-xs text-toss-gray-500">
          음원 시작 (앞 1마디 lead-in):{" "}
          <span className="font-medium text-toss-gray-700 tabular-nums">
            {formatSeconds(audioStartSec)}
          </span>
        </p>
      )}

      {metrics.size > 0 && (
        <>
          <Separator />
          <div>
            <h3 className="text-sm font-semibold text-toss-gray-900 mb-2">
              점수
            </h3>
            <div className="space-y-2">
              {ATTRIBUTES.filter((a) => metrics.has(a.key)).map((a) => {
                const cur = scores[a.key];
                return (
                  <div key={a.key} className="flex items-center gap-2">
                    <span className="text-xs text-toss-gray-600 w-20 shrink-0">
                      {a.label}
                    </span>
                    <div className="flex gap-1 flex-1">
                      {([1, 2, 3, 4, 5] as const).map((v) => (
                        <button
                          key={v}
                          type="button"
                          onClick={() =>
                            setScores((s) => ({ ...s, [a.key]: v }))
                          }
                          className={`flex-1 h-7 rounded-md text-xs font-semibold transition-all ${
                            cur === v
                              ? "bg-toss-blue text-white"
                              : "bg-toss-gray-100 text-toss-gray-400 hover:bg-toss-gray-200"
                          }`}
                        >
                          {v}
                        </button>
                      ))}
                      <button
                        type="button"
                        onClick={() =>
                          setScores((s) => {
                            const ns = { ...s };
                            delete ns[a.key];
                            return ns;
                          })
                        }
                        className="px-2 h-7 rounded-md text-xs text-toss-gray-400 hover:bg-toss-gray-100"
                        disabled={cur === undefined}
                      >
                        지우기
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      <Separator />

      <div>
        <h3 className="text-sm font-semibold text-toss-gray-900 mb-2">시간</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className="space-y-1">
            <span className="text-xs text-toss-gray-500">시작</span>
            <Input
              type="datetime-local"
              value={startedAtLocal}
              onChange={(e) => setStartedAtLocal(e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-toss-gray-500">완료</span>
            <Input
              type="datetime-local"
              value={completedAtLocal}
              onChange={(e) => setCompletedAtLocal(e.target.value)}
            />
          </label>
        </div>
        {!timeValid && (
          <p className="text-xs text-toss-red mt-1.5">
            시작 시각이 비었거나 완료가 시작보다 빠릅니다.
          </p>
        )}
      </div>

      <Textarea
        placeholder="메모"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        className="resize-none"
        rows={2}
      />

      <div className="flex gap-2">
        <Button
          variant="outline"
          className="flex-1 rounded-md h-9 border-toss-gray-200 text-toss-gray-600"
          onClick={onClose}
          disabled={updateMut.isPending}
        >
          취소
        </Button>
        <Button
          className="flex-1 bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md h-9 text-sm font-medium"
          onClick={handleSave}
          disabled={!formValid || updateMut.isPending}
        >
          {updateMut.isPending ? "저장 중..." : "저장"}
        </Button>
      </div>
    </div>
  );
}
