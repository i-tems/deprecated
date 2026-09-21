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
} from "recharts";
import api, { type UserSkill, type SkillEvaluation } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import Link from "next/link";

export default function MySkillDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const queryClient = useQueryClient();

  const [selectedLevel, setSelectedLevel] = useState<number | null>(null);
  const [comment, setComment] = useState("");

  const { data: userSkill } = useQuery<UserSkill>({
    queryKey: ["my-skill", id],
    queryFn: () => api.get(`/api/my/skills/${id}`).then((r) => r.data),
  });

  const { data: evaluations = [] } = useQuery<SkillEvaluation[]>({
    queryKey: ["skill-evaluations", id],
    queryFn: () =>
      api.get(`/api/my/skills/${id}/evaluations`).then((r) => r.data),
  });

  const submitEval = useMutation({
    mutationFn: (data: { level: number; comment: string | null }) =>
      api.post(`/api/my/skills/${id}/evaluations`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-skill", id] });
      queryClient.invalidateQueries({ queryKey: ["skill-evaluations", id] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["my-skills"] });
      setSelectedLevel(null);
      setComment("");
    },
  });

  if (!userSkill) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-toss-gray-400">Loading...</div>
      </div>
    );
  }

  const currentLevel = userSkill.latest_evaluation?.level;
  const levels = userSkill.skill.levels;

  const chartData = [...evaluations].reverse().map((ev) => ({
    date: new Date(ev.created_at).toLocaleDateString("ko-KR", {
      month: "short",
      day: "numeric",
    }),
    level: ev.level,
    comment: ev.comment,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          href="/my/skills"
          className="text-sm text-toss-gray-500 hover:text-toss-gray-700 mb-2 inline-flex items-center gap-1 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
          내 스킬
        </Link>
        <h1 className="text-2xl font-semibold text-toss-gray-900">{userSkill.skill.name}</h1>
        <div className="flex items-center gap-2 mt-2">
          <Badge className="bg-blue-50 text-toss-blue">
            {userSkill.skill.category}
          </Badge>
          {currentLevel && (
            <Badge className="bg-emerald-50 text-toss-green">
              레벨 {currentLevel} / 5
            </Badge>
          )}
        </div>
        {userSkill.skill.description && (
          <p className="text-sm text-toss-gray-500 mt-2">{userSkill.skill.description}</p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Level descriptions */}
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">레벨 기준</h2>
          <div className="space-y-2.5">
            {levels ? (
              Object.entries(levels).map(([lvl, desc]) => (
                <div
                  key={lvl}
                  className={`p-3.5 rounded-xl ${
                    currentLevel && Number(lvl) <= currentLevel
                      ? "bg-toss-blue-light"
                      : "bg-toss-gray-50"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <div
                      className={`w-7 h-7 rounded-lg text-sm flex items-center justify-center font-semibold ${
                        currentLevel && Number(lvl) <= currentLevel
                          ? "bg-toss-blue text-white"
                          : "bg-toss-gray-200 text-toss-gray-500"
                      }`}
                    >
                      {lvl}
                    </div>
                    {currentLevel === Number(lvl) && (
                      <span className="text-xs text-toss-blue font-semibold">현재</span>
                    )}
                  </div>
                  <p className="text-sm text-toss-gray-600">{desc}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-toss-gray-400">레벨 기준 설명이 없습니다.</p>
            )}
          </div>
        </div>

        {/* Evaluation form */}
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">레벨 평가</h2>
          <div className="space-y-4">
            <div className="flex gap-2">
              {[1, 2, 3, 4, 5].map((v) => (
                <button
                  key={v}
                  onClick={() => setSelectedLevel(v)}
                  className={`flex-1 h-14 rounded-xl text-lg font-semibold transition-all ${
                    selectedLevel === v
                      ? "bg-toss-blue text-white scale-105"
                      : selectedLevel && selectedLevel > v
                        ? "bg-toss-blue-light text-toss-blue"
                        : "bg-toss-gray-100 text-toss-gray-400 hover:bg-toss-gray-200"
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
            {currentLevel && (
              <p className="text-sm text-toss-gray-500 text-center">
                현재 레벨: {currentLevel}
              </p>
            )}
            <Separator />
            <Textarea
              placeholder="메모 (선택사항)"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="resize-none"
              rows={2}
            />
            <Button
              className="w-full bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md h-9 text-sm font-medium"
              onClick={() =>
                selectedLevel &&
                submitEval.mutate({ level: selectedLevel, comment: comment || null })
              }
              disabled={!selectedLevel || submitEval.isPending}
            >
              {submitEval.isPending ? "저장 중..." : "평가 저장"}
            </Button>
          </div>
        </div>
      </div>

      {/* History Chart */}
      {evaluations.length > 1 && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">레벨 추이</h2>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#26272B" />
              <XAxis dataKey="date" tick={{ fill: "#8A8F98", fontSize: 12 }} />
              <YAxis domain={[0, 5]} ticks={[1, 2, 3, 4, 5]} tick={{ fill: "#8A8F98", fontSize: 12 }} />
              <RechartsTooltip
                contentStyle={{
                  backgroundColor: "#0F1011",
                  border: "1px solid #26272B",
                  borderRadius: "12px",
                  color: "#F7F8F8",
                  boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
                }}
              />
              <Line
                type="monotone"
                dataKey="level"
                name="레벨"
                stroke="#5E6AD2"
                strokeWidth={2.5}
                dot={{ r: 4, fill: "#5E6AD2" }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Change log */}
      {evaluations.length > 0 && (
        <div className="bg-card rounded-xl p-6 border border-border">
          <h2 className="text-base font-semibold text-toss-gray-900 mb-4">변경 로그</h2>
          <div className="space-y-2.5">
            {evaluations.map((ev, idx) => {
              const prev = evaluations[idx + 1];
              const diff = prev ? ev.level - prev.level : null;
              return (
                <div
                  key={ev.id}
                  className="p-3.5 rounded-xl bg-toss-gray-50 flex items-center justify-between"
                >
                  <div>
                    <span className="text-sm text-toss-gray-600">
                      {new Date(ev.created_at).toLocaleString("ko-KR")}
                    </span>
                    {ev.comment && (
                      <span className="text-sm text-toss-gray-500 italic ml-3">
                        &quot;{ev.comment}&quot;
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-lg text-toss-gray-900">Lv.{ev.level}</span>
                    {diff !== null && diff !== 0 && (
                      <span
                        className={`text-sm font-semibold ${
                          diff > 0 ? "text-toss-green" : "text-toss-red"
                        }`}
                      >
                        {diff > 0 ? `+${diff}` : diff}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
