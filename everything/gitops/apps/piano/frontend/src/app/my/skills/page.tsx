"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { type UserSkill, type Skill } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import Link from "next/link";

const CATEGORY_COLORS: Record<string, string> = {
  "테크닉": "bg-blue-50 text-toss-blue",
  "초견": "bg-emerald-50 text-toss-green",
  "청음": "bg-purple-50 text-[#8B5CF6]",
  "음악 이론": "bg-orange-50 text-toss-orange",
  "리듬 훈련": "bg-red-50 text-toss-red",
  "손가락 독립성": "bg-cyan-50 text-[#06B6D4]",
};

export default function MySkillsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const { data: mySkills = [] } = useQuery<UserSkill[]>({
    queryKey: ["my-skills"],
    queryFn: () => api.get("/api/my/skills").then((r) => r.data),
  });

  const { data: catalog = [] } = useQuery<Skill[]>({
    queryKey: ["skills-catalog"],
    queryFn: () => api.get("/api/skills").then((r) => r.data),
    enabled: open,
  });

  const addSkill = useMutation({
    mutationFn: (skillId: string) =>
      api.post("/api/my/skills", { skill_id: skillId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-skills"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const deleteSkill = useMutation({
    mutationFn: (userSkillId: string) =>
      api.delete(`/api/my/skills/${userSkillId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-skills"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const mySkillIds = new Set(mySkills.map((us) => us.skill.id));

  const grouped = mySkills.reduce(
    (acc, us) => {
      const cat = us.skill.category;
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(us);
      return acc;
    },
    {} as Record<string, UserSkill[]>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-toss-gray-900">내 스킬</h1>
          <p className="text-sm text-toss-gray-500 mt-1">
            {mySkills.length}개 스킬 등록됨
          </p>
        </div>
        <Button
          className="bg-toss-blue hover:bg-toss-blue-dark text-white rounded-md h-9 px-4 text-sm font-medium"
          onClick={() => setOpen(true)}
        >
          <svg className="w-4 h-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          스킬 추가
        </Button>

        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>스킬 추가</DialogTitle>
            </DialogHeader>
            <div className="space-y-2">
              {catalog.map((skill) => {
                const added = mySkillIds.has(skill.id);
                return (
                  <div
                    key={skill.id}
                    className="flex items-center justify-between p-3.5 rounded-xl bg-toss-gray-50 hover:bg-toss-gray-100 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-toss-gray-900">{skill.name}</span>
                        <Badge className={CATEGORY_COLORS[skill.category] || "bg-toss-gray-100 text-toss-gray-600"}>
                          {skill.category}
                        </Badge>
                      </div>
                      {skill.description && (
                        <div className="text-sm text-toss-gray-500 mt-1">
                          {skill.description}
                        </div>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant={added ? "secondary" : "default"}
                      disabled={added || addSkill.isPending}
                      onClick={() => addSkill.mutate(skill.id)}
                      className={added ? "rounded-lg" : "bg-toss-blue hover:bg-toss-blue-dark text-white rounded-lg"}
                    >
                      {added ? "추가됨" : "추가"}
                    </Button>
                  </div>
                );
              })}
              {catalog.length === 0 && (
                <div className="text-center text-toss-gray-400 py-8 text-sm">
                  등록된 스킬이 없습니다
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {mySkills.length === 0 ? (
        <div className="bg-card rounded-xl py-16 text-center text-toss-gray-400 border border-border text-sm">
          아직 등록한 스킬이 없습니다. 스킬을 추가해보세요.
        </div>
      ) : (
        Object.entries(grouped).map(([category, skills]) => (
          <div key={category}>
            <div className="mb-3">
              <Badge className={CATEGORY_COLORS[category] || "bg-toss-gray-100 text-toss-gray-600"}>
                {category}
              </Badge>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {skills.map((us) => {
                const level = us.latest_evaluation?.level;
                return (
                  <Link key={us.id} href={`/my/skills/${us.id}`}>
                    <div className="bg-card rounded-xl p-5 border border-border transition-shadow cursor-pointer h-full">
                      <div className="flex items-center justify-between">
                        <div className="font-semibold text-toss-gray-900">{us.skill.name}</div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-toss-gray-400 hover:text-toss-red hover:bg-red-50 shrink-0"
                          onClick={(e) => {
                            e.preventDefault();
                            if (confirm("이 스킬을 제거할까요?")) {
                              deleteSkill.mutate(us.id);
                            }
                          }}
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </Button>
                      </div>
                      {us.skill.description && (
                        <div className="text-sm text-toss-gray-500 mt-1 line-clamp-2">
                          {us.skill.description}
                        </div>
                      )}
                      <div className="mt-3 flex items-center gap-2">
                        <div className="flex gap-1">
                          {[1, 2, 3, 4, 5].map((v) => (
                            <div
                              key={v}
                              className={`w-7 h-7 rounded-lg text-xs flex items-center justify-center font-semibold ${
                                level && v <= level
                                  ? "bg-toss-blue text-white"
                                  : "bg-toss-gray-100 text-toss-gray-400"
                              }`}
                            >
                              {v}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
