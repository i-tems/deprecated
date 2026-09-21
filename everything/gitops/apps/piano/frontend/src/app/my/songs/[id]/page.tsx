"use client";

import { useState, use } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import api, {
  ATTRIBUTES,
  STATUS_LABELS,
  STATUS_COLORS,
  type UserSong,
  type Evaluation,
  type SongStatus,
} from "@/lib/api";
import { SkillRadarChart } from "@/components/radar-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import Link from "next/link";

const ATTR_COLORS = [
  "#7B86E0", "#E5707B", "#54C295", "#E0A85A", "#A992E6",
  "#E08AB8", "#5FBFD2", "#E0976A", "#A6C56F", "#8A90E8",
];

export default function MySongDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const queryClient = useQueryClient();

  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState("");
  const [editingStatus, setEditingStatus] = useState(false);

  const { data: userSong } = useQuery<UserSong>({
    queryKey: ["my-song", id],
    queryFn: () => api.get(`/api/my/songs/${id}`).then((r) => r.data),
  });

  const { data: evaluations = [] } = useQuery<Evaluation[]>({
    queryKey: ["evaluations", id],
    queryFn: () =>
      api.get(`/api/my/songs/${id}/evaluations`).then((r) => r.data),
  });

  const submitEval = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post(`/api/my/songs/${id}/evaluations`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-song", id] });
      queryClient.invalidateQueries({ queryKey: ["evaluations", id] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["my-songs"] });
      setScores({});
      setComment("");
    },
  });

  const updateStatus = useMutation({
    mutationFn: (status: SongStatus) =>
      api.patch(`/api/my/songs/${id}`, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-song", id] });
      queryClient.invalidateQueries({ queryKey: ["my-songs"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      setEditingStatus(false);
    },
  });

  if (!userSong) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-toss-gray-400">Loading...</div>
      </div>
    );
  }

  const latestEval = userSong.latest_evaluation;
  const currentScores: Record<string, number> = {};
  if (latestEval) {
    ATTRIBUTES.forEach((a) => {
      currentScores[a.key] = latestEval[a.key as keyof Evaluation] as number;
    });
  }

  const isFormValid =
    ATTRIBUTES.every((a) => scores[a.key] >= 1 && scores[a.key] <= 5);

  const handleSubmitEval = () => {
    if (!isFormValid) return;
    submitEval.mutate({ ...scores, comment: comment || null });
  };

  const prefillFromLatest = () => {
    if (latestEval) {
      const s: Record<string, number> = {};
      ATTRIBUTES.forEach((a) => {
        s[a.key] = latestEval[a.key as keyof Evaluation] as number;
      });
      setScores(s);
    }
  };

  const chartData = [...evaluations].reverse().map((ev) => {
    const d: Record<string, unknown> = {
      date: new Date(ev.created_at).toLocaleDateString("ko-KR", {
        month: "short",
        day: "numeric",
      }),
      comment: ev.comment,
    };
    ATTRIBUTES.forEach((a) => {
      d[a.key] = ev[a.key as keyof Evaluation];
    });
    return d;
  });

  const statuses: SongStatus[] = [
    "NOT_STARTED",
    "PRACTICING",
    "POLISHING",
    "COMPLETED",
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link
            href="/my/songs"
            className="text-sm text-toss-gray-500 hover:text-toss-gray-700 mb-2 inline-flex items-center gap-1 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
            내 곡 목록
          </Link>
          <h1 className="text-2xl font-semibold text-toss-gray-900">{userSong.song.title}</h1>
          <p className="text-sm text-toss-gray-500 mt-1">
            {userSong.song.composer} · 난이도 {userSong.song.difficulty}/10
          </p>
          <div className="flex items-center gap-2 mt-3">
            {editingStatus ? (
              <div className="flex items-center gap-2">
                {statuses.map((s) => (
                  <Button
                    key={s}
                    size="sm"
                    variant={userSong.status === s ? "default" : "outline"}
                    onClick={() => updateStatus.mutate(s)}
                    className={`text-xs rounded-lg ${userSong.status === s ? "bg-toss-blue text-white" : ""}`}
                  >
                    {STATUS_LABELS[s]}
                  </Button>
                ))}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditingStatus(false)}
                  className="text-toss-gray-500"
                >
                  취소
                </Button>
              </div>
            ) : (
              <>
                <Badge
                  className={`${STATUS_COLORS[userSong.status]} text-white`}
                >
                  {STATUS_LABELS[userSong.status]}
                </Badge>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-xs text-toss-gray-500 hover:text-toss-gray-700"
                  onClick={() => setEditingStatus(true)}
                >
                  변경
                </Button>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Link href={`/my/songs/${id}/practice`}>
            <Button size="sm" className="rounded-xl bg-toss-blue hover:bg-toss-blue-dark text-white">
              연습 시작
            </Button>
          </Link>
          <Link href={`/songs/${userSong.song.id}`}>
            <Button variant="outline" size="sm" className="rounded-xl border-toss-gray-200 text-toss-gray-700">
              곡 분석 보기
            </Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Current Radar */}
        <div className="bg-card rounded-xl border border-border p-6">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">현재 평가</h2>
          {latestEval ? (
            <SkillRadarChart
              scores={currentScores}
              requiredSkills={userSong.song.required_skills}
              size={350}
            />
          ) : (
            <div className="h-[350px] flex items-center justify-center text-toss-gray-400 text-sm">
              아직 평가가 없습니다. 아래에서 첫 평가를 해보세요.
            </div>
          )}
        </div>

        {/* New Evaluation Form */}
        <div className="bg-card rounded-xl border border-border p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-toss-gray-900">새 평가 기록</h2>
            {latestEval && (
              <Button
                size="sm"
                variant="outline"
                onClick={prefillFromLatest}
                className="text-xs rounded-lg border-toss-gray-200 text-toss-gray-600"
              >
                이전 평가 불러오기
              </Button>
            )}
          </div>
          <div className="space-y-4">
            {ATTRIBUTES.map((attr) => {
              const selected = scores[attr.key];
              return (
                <div key={attr.key} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-toss-gray-700">
                      {attr.label}
                    </span>
                    {latestEval && (
                      <span className="text-xs text-toss-gray-400">
                        현재 {latestEval[attr.key as keyof Evaluation] as number}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-toss-gray-400">
                    {attr.description}
                  </p>
                  <div className="flex gap-1.5">
                    {([1, 2, 3, 4, 5] as const).map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() =>
                          setScores((prev) => ({ ...prev, [attr.key]: v }))
                        }
                        className={`flex-1 h-9 rounded-lg text-sm font-semibold transition-all ${
                          selected === v
                            ? "bg-toss-blue text-white"
                            : selected > v
                              ? "bg-toss-blue-light text-toss-blue"
                              : "bg-toss-gray-100 text-toss-gray-400 hover:bg-toss-gray-200"
                        }`}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                  <p className="text-xs leading-relaxed text-toss-gray-500 min-h-[2.5em]">
                    {selected ? (
                      <>
                        <span className="font-semibold text-toss-gray-700">Lv.{selected}</span>
                        {" · "}
                        {attr.criteria[selected as 1 | 2 | 3 | 4 | 5]}
                      </>
                    ) : (
                      <span className="text-toss-gray-400">레벨을 눌러 기준을 확인하세요</span>
                    )}
                  </p>
                </div>
              );
            })}
            <Separator className="my-4" />
            <Textarea
              placeholder="메모 (선택사항) - 예: 오늘 왼손 옥타브 연습 집중함"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="resize-none"
              rows={2}
            />
            <Button
              className="w-full bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md h-9 text-sm font-medium"
              onClick={handleSubmitEval}
              disabled={!isFormValid || submitEval.isPending}
            >
              {submitEval.isPending ? "저장 중..." : "평가 저장"}
            </Button>
          </div>
        </div>
      </div>

      {/* History Chart */}
      {evaluations.length > 1 && (
        <div className="bg-card rounded-xl border border-border p-6">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">시간 추이</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#26272B" />
              <XAxis dataKey="date" tick={{ fill: "#8A8F98", fontSize: 12 }} />
              <YAxis domain={[0, 5]} tick={{ fill: "#8A8F98", fontSize: 12 }} />
              <RechartsTooltip
                contentStyle={{
                  backgroundColor: "#0F1011",
                  border: "1px solid #26272B",
                  borderRadius: "8px",
                  color: "#F7F8F8",
                  boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                }}
              />
              <Legend />
              {ATTRIBUTES.map((attr, i) => (
                <Line
                  key={attr.key}
                  type="monotone"
                  dataKey={attr.key}
                  name={attr.label}
                  stroke={ATTR_COLORS[i]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Evaluation History / Change Log */}
      {evaluations.length > 0 && (
        <div className="bg-card rounded-xl border border-border p-6">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">변경 로그</h2>
          <div className="space-y-3">
            {evaluations.map((ev, idx) => {
              const prev = evaluations[idx + 1];
              const avg =
                ATTRIBUTES.reduce(
                  (sum, a) =>
                    sum + (ev[a.key as keyof Evaluation] as number),
                  0
                ) / ATTRIBUTES.length;

              return (
                <div
                  key={ev.id}
                  className="p-4 rounded-lg border border-border bg-toss-gray-100"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-toss-gray-700">
                      {new Date(ev.created_at).toLocaleString("ko-KR")}
                    </span>
                    <span className="text-sm font-semibold text-toss-blue">
                      평균 {avg.toFixed(1)}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-sm">
                    {ATTRIBUTES.map((a) => {
                      const val = ev[a.key as keyof Evaluation] as number;
                      const prevVal = prev
                        ? (prev[a.key as keyof Evaluation] as number)
                        : null;
                      const diff =
                        prevVal !== null ? val - prevVal : null;
                      return (
                        <div key={a.key} className="flex items-center gap-1">
                          <span className="text-toss-gray-500 truncate">
                            {a.label}:
                          </span>
                          <span className="font-medium text-toss-gray-900">{val}</span>
                          {diff !== null && diff !== 0 && (
                            <span
                              className={
                                diff > 0
                                  ? "text-toss-green text-xs font-medium"
                                  : "text-toss-red text-xs font-medium"
                              }
                            >
                              {diff > 0 ? `+${diff}` : diff}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {ev.comment && (
                    <div className="mt-2 text-sm text-toss-gray-500 italic">
                      &quot;{ev.comment}&quot;
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
