"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getConfig,
  getOverview,
  getProfile,
  createEvaluation,
  createSkillEvaluation,
  createRunningEvaluation,
  type Evaluation,
  type SkillEvaluation,
  type RunningEvaluation,
  type BodyPartConfig,
} from "@/lib/api";
import { cn, getToday } from "@/lib/utils";
import { Save, Check, ChevronDown, ChevronUp, Footprints } from "lucide-react";

interface PartFormData {
  part_id: string;
  strength: number;
  development: number;
  mmc: number;
  best_5rm: number | null;
}

interface SkillFormData {
  skill_id: string;
  score: number;
}

/**
 * Shared level-description strip rendered below any 1~5 slider.
 * Shows the criterion for the currently-selected integer level from a
 * `{ "1": "...", "2": "..." }` map.
 */
function LevelDescription({
  levels,
  currentValue,
}: {
  levels?: Record<string, string>;
  currentValue: number;
}) {
  if (!levels || Object.keys(levels).length === 0) return null;
  const lv = String(Math.max(1, Math.min(5, Math.round(currentValue))));
  const desc = levels[lv];
  if (!desc) return null;
  return (
    <p className="text-[11px] text-text-secondary mt-1.5 px-2.5 py-1.5 rounded-lg bg-surface-secondary leading-relaxed">
      <span className="font-semibold text-text-primary">Lv.{lv}</span>{" "}
      <span className="text-text-secondary">{desc}</span>
    </p>
  );
}

/**
 * Given a 5RM (kg), bodyweight (kg), and the body part's strength_standards
 * (e.g. {'1':'0.5xBW', '2':'0.75xBW', ...}), derive an estimated strength level.
 * Uses Epley: 1RM ≈ 5RM × (1 + 5/30) = 5RM × 1.1667.
 */
function deriveStrengthLevel(
  best5rm: number | null,
  bodyweight: number,
  bp: BodyPartConfig | undefined
): { level: number; ratio: number; est1rm: number } | null {
  if (!best5rm || best5rm <= 0 || !bodyweight || bodyweight <= 0) return null;
  const standards = bp?.strength_standards ?? {};
  const entries = Object.entries(standards)
    .map(([lv, spec]) => {
      const m = /([\d.]+)\s*x\s*BW/i.exec(spec);
      if (!m) return null;
      return { level: parseInt(lv, 10), ratio: parseFloat(m[1]) };
    })
    .filter((x): x is { level: number; ratio: number } => x !== null)
    .sort((a, b) => a.level - b.level);
  if (entries.length === 0) return null;

  const est1rm = best5rm * (1 + 5 / 30);
  const ratio = est1rm / bodyweight;

  let level: number;
  if (ratio < entries[0].ratio) {
    level = 1.0;
  } else if (ratio >= entries[entries.length - 1].ratio) {
    level = 5.0;
  } else {
    level = entries[entries.length - 1].level;
    for (let i = 0; i < entries.length - 1; i++) {
      const a = entries[i];
      const b = entries[i + 1];
      if (ratio >= a.ratio && ratio < b.ratio) {
        const frac = (ratio - a.ratio) / (b.ratio - a.ratio);
        level = a.level + frac * (b.level - a.level);
        break;
      }
    }
    level = Math.round(level * 2) / 2;
  }
  return { level, ratio, est1rm };
}

export default function EvaluationForm() {
  const queryClient = useQueryClient();
  const [date, setDate] = useState(getToday());
  const [selectedParts, setSelectedParts] = useState<Set<string>>(new Set());
  const [partForms, setPartForms] = useState<Record<string, PartFormData>>({});
  const [skillForms, setSkillForms] = useState<Record<string, SkillFormData>>({});
  const [runningLevels, setRunningLevels] = useState<Record<string, number>>({});
  const [initialRunningLevels, setInitialRunningLevels] = useState<Record<string, number>>({});
  const [showSkills, setShowSkills] = useState(false);
  const [showRunning, setShowRunning] = useState(false);
  const [saved, setSaved] = useState(false);

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: overview } = useQuery({ queryKey: ["overview"], queryFn: getOverview });
  const { data: profile } = useQuery({ queryKey: ["profile"], queryFn: getProfile });

  useEffect(() => {
    if (overview && config) {
      const forms: Record<string, PartFormData> = {};
      config.body_parts.forEach((bp) => {
        const prev = overview.part_scores.find((ps) => ps.part_id === bp.id);
        forms[bp.id] = {
          part_id: bp.id,
          strength: prev?.strength ?? 2.5,
          development: prev?.development ?? 2.5,
          mmc: prev?.mmc ?? 2.5,
          best_5rm: prev?.best_5rm ?? null,
        };
      });
      setPartForms(forms);

      const sForms: Record<string, SkillFormData> = {};
      config.skills.forEach((s) => {
        const prev = overview.skill_scores.find((ss) => ss.skill_id === s.id);
        sForms[s.id] = {
          skill_id: s.id,
          score: prev?.score ?? 2.5,
        };
      });
      setSkillForms(sForms);

      const rLevels: Record<string, number> = {};
      (config.running_metrics ?? []).forEach((m) => {
        const prev = overview.running_scores?.find((rs) => rs.metric_id === m.id);
        rLevels[m.id] = prev?.level && prev.level > 0 ? prev.level : 2.5;
      });
      setRunningLevels(rLevels);
      setInitialRunningLevels(rLevels);
    }
  }, [overview, config]);

  const evalMutation = useMutation({
    mutationFn: (evals: Omit<Evaluation, "id">[]) => createEvaluation(evals),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["evaluations"] });
    },
  });

  const skillMutation = useMutation({
    mutationFn: (evals: Omit<SkillEvaluation, "id">[]) =>
      createSkillEvaluation(evals),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["skill-evaluations"] });
    },
  });

  const runningMutation = useMutation({
    mutationFn: (evals: RunningEvaluation[]) => createRunningEvaluation(evals),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["running-evaluations"] });
    },
  });

  const togglePart = (partId: string) => {
    setSelectedParts((prev) => {
      const next = new Set(prev);
      if (next.has(partId)) next.delete(partId);
      else next.add(partId);
      return next;
    });
  };

  const updatePartForm = (
    partId: string,
    field: keyof PartFormData,
    value: string | number | null
  ) => {
    setPartForms((prev) => ({
      ...prev,
      [partId]: { ...prev[partId], [field]: value },
    }));
  };

  const updateSkillForm = (
    skillId: string,
    field: keyof SkillFormData,
    value: string | number
  ) => {
    setSkillForms((prev) => ({
      ...prev,
      [skillId]: { ...prev[skillId], [field]: value },
    }));
  };

  const runningMetrics = config?.running_metrics ?? [];

  // Running rows whose level slider changed from the initial value.
  const runningPayload: RunningEvaluation[] = showRunning
    ? runningMetrics
        .map((m) => {
          const level = runningLevels[m.id] ?? 0;
          const initialLv = initialRunningLevels[m.id] ?? 0;
          if (level === initialLv) return null;
          return { date, metric_id: m.id, level };
        })
        .filter((x): x is RunningEvaluation => x !== null)
    : [];

  const handleSave = async () => {
    const partEvals = Array.from(selectedParts).map((partId) => ({
      date,
      ...partForms[partId],
    }));

    if (partEvals.length > 0) {
      await evalMutation.mutateAsync(partEvals);
    }

    if (showSkills) {
      const skillEvals = Object.values(skillForms).map((sf) => ({
        date,
        skill_id: sf.skill_id,
        score: sf.score,
      }));
      await skillMutation.mutateAsync(skillEvals);
    }

    if (runningPayload.length > 0) {
      await runningMutation.mutateAsync(runningPayload);
      setInitialRunningLevels({ ...runningLevels });
    }

    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const sliderSteps = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0];

  if (!config) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-text-tertiary text-sm">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Date */}
      <div>
        <label className="block text-[13px] text-text-secondary mb-1.5">날짜</label>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="w-full px-3 py-2 rounded-xl bg-surface border border-border text-text-primary text-sm focus:outline-none focus:border-brand"
        />
      </div>

      {/* Body Part Selection */}
      <div>
        <label className="block text-[13px] text-text-secondary mb-2">
          운동 부위 선택
        </label>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {config.body_parts.map((bp) => (
            <button
              key={bp.id}
              onClick={() => togglePart(bp.id)}
              className={cn(
                "px-3 py-2.5 rounded-xl text-sm font-medium border transition-all",
                selectedParts.has(bp.id)
                  ? "border-brand bg-brand-light text-brand-dark shadow-sm"
                  : "border-border bg-surface-secondary text-text-secondary hover:border-text-tertiary"
              )}
            >
              {bp.name}
            </button>
          ))}
        </div>
      </div>

      {/* Part Evaluation Forms */}
      {Array.from(selectedParts).map((partId) => {
        const bp = config.body_parts.find((b) => b.id === partId);
        const form = partForms[partId];
        if (!bp || !form) return null;

        const hasStandards = Object.keys(bp.strength_standards ?? {}).length > 0;
        const derived = deriveStrengthLevel(
          form.best_5rm,
          profile?.weight ?? 0,
          bp
        );

        return (
          <div
            key={partId}
            className="rounded-2xl bg-surface border border-border p-5"
          >
            <h3 className="text-[17px] font-semibold text-text-primary mb-1">
              {bp.name}
            </h3>
            <p className="text-[11px] text-text-tertiary mb-4">
              대표 종목: {bp.representative_exercise}
            </p>

            {/* 5RM input */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[13px] text-text-secondary">
                  5RM (kg)
                  <span className="text-[10px] text-text-tertiary ml-1">
                    · {bp.representative_exercise}
                  </span>
                </span>
                {derived && hasStandards && (
                  <span className="text-[11px] text-text-tertiary font-mono">
                    est. 1RM {derived.est1rm.toFixed(1)}kg · {derived.ratio.toFixed(2)}xBW
                    <span className="ml-1 text-brand-dark font-semibold">
                      → Lv.{derived.level.toFixed(1)}
                    </span>
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  step="0.5"
                  value={form.best_5rm ?? ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    updatePartForm(
                      partId,
                      "best_5rm",
                      v === "" ? null : parseFloat(v)
                    );
                  }}
                  placeholder="예: 70"
                  className="flex-1 px-3 py-2 rounded-xl bg-white border border-border text-text-primary text-sm focus:outline-none focus:border-brand"
                />
                {derived && (
                  <button
                    type="button"
                    onClick={() =>
                      updatePartForm(partId, "strength", derived.level)
                    }
                    className="px-3 py-2 rounded-xl text-[11px] font-medium bg-brand-light text-brand-dark hover:bg-brand/15 transition-colors whitespace-nowrap"
                    title="근력 슬라이더에 자동 적용"
                  >
                    근력 자동 적용
                  </button>
                )}
              </div>
              {!hasStandards && form.best_5rm && (
                <div className="text-[10px] text-text-tertiary mt-1">
                  이 부위는 BW 기준표가 없어 자동 레벨 환산이 제공되지 않습니다.
                  기록은 저장됩니다.
                </div>
              )}
              {!profile?.weight && form.best_5rm && hasStandards && (
                <div className="text-[10px] text-amber-600 mt-1">
                  설정 페이지에서 체중을 입력하면 자동 레벨이 계산됩니다
                </div>
              )}
            </div>

            {/* Attribute Sliders */}
            {config.attributes.map((attr) => {
              const key = attr.id as keyof PartFormData;
              const value = form[key] as number;

              return (
                <div key={attr.id} className="mb-4">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[13px] text-text-secondary">{attr.name}</span>
                    <span className="text-[13px] font-mono font-semibold text-brand-dark">
                      {value.toFixed(1)}
                    </span>
                  </div>
                  <div className="flex gap-1">
                    {sliderSteps.map((step) => (
                      <button
                        key={step}
                        onClick={() => updatePartForm(partId, key, step)}
                        className={cn(
                          "flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors",
                          value === step
                            ? "bg-brand text-white"
                            : step <= value
                              ? "bg-brand-light text-brand-dark"
                              : "bg-surface-tertiary text-text-tertiary hover:bg-surface-secondary"
                        )}
                      >
                        {step}
                      </button>
                    ))}
                  </div>
                  <LevelDescription levels={attr.levels} currentValue={value} />
                </div>
              );
            })}

          </div>
        );
      })}

      {/* Skills Section */}
      <div className="rounded-2xl bg-surface border border-border">
        <button
          onClick={() => setShowSkills(!showSkills)}
          className={cn(
            "w-full flex items-center justify-between p-4 hover:bg-surface-secondary transition-colors",
            showSkills ? "rounded-t-2xl" : "rounded-2xl"
          )}
        >
          <span className="text-sm font-medium text-text-secondary">
            기초 스킬 평가 (선택)
          </span>
          {showSkills ? (
            <ChevronUp className="w-4 h-4 text-text-tertiary" />
          ) : (
            <ChevronDown className="w-4 h-4 text-text-tertiary" />
          )}
        </button>

        {showSkills && (
          <div className="p-5 pt-0 space-y-5">
            {config.skills.map((skill) => {
              const form = skillForms[skill.id];
              if (!form) return null;
              return (
                <div key={skill.id}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[13px] text-text-secondary">{skill.name}</span>
                    <span className="text-[13px] font-mono font-semibold text-brand-dark">
                      {form.score.toFixed(1)}
                    </span>
                  </div>
                  <div className="flex gap-1">
                    {sliderSteps.map((step) => (
                      <button
                        key={step}
                        onClick={() => updateSkillForm(skill.id, "score", step)}
                        className={cn(
                          "flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors",
                          form.score === step
                            ? "bg-brand text-white"
                            : step <= form.score
                              ? "bg-brand-light text-brand-dark"
                              : "bg-surface-tertiary text-text-tertiary hover:bg-surface-secondary"
                        )}
                      >
                        {step}
                      </button>
                    ))}
                  </div>
                  <LevelDescription levels={skill.levels} currentValue={form.score} />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Running Section */}
      {runningMetrics.length > 0 && (
        <div className="rounded-2xl bg-surface border border-border">
          <button
            onClick={() => setShowRunning(!showRunning)}
            className={cn(
              "w-full flex items-center justify-between p-4 hover:bg-surface-secondary transition-colors",
              showRunning ? "rounded-t-2xl" : "rounded-2xl"
            )}
          >
            <span className="text-sm font-medium text-text-secondary flex items-center gap-2">
              <Footprints className="w-4 h-4 text-brand" />
              달리기 기록 (선택)
            </span>
            {showRunning ? (
              <ChevronUp className="w-4 h-4 text-text-tertiary" />
            ) : (
              <ChevronDown className="w-4 h-4 text-text-tertiary" />
            )}
          </button>

          {showRunning && (
            <div className="p-5 pt-0 space-y-5">
              {runningMetrics.map((m) => {
                const level = runningLevels[m.id] ?? 2.5;
                return (
                  <div key={m.id}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[13px] text-text-secondary">
                        {m.name}
                      </span>
                      <span className="text-[13px] font-mono font-semibold text-brand-dark">
                        {level.toFixed(1)}
                      </span>
                    </div>
                    <div className="flex gap-1">
                      {sliderSteps.map((step) => (
                        <button
                          key={step}
                          onClick={() =>
                            setRunningLevels((prev) => ({ ...prev, [m.id]: step }))
                          }
                          className={cn(
                            "flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors",
                            level === step
                              ? "bg-brand text-white"
                              : step <= level
                                ? "bg-brand-light text-brand-dark"
                                : "bg-surface-tertiary text-text-tertiary hover:bg-surface-secondary"
                          )}
                        >
                          {step}
                        </button>
                      ))}
                    </div>
                    <LevelDescription
                      levels={m.level_standards}
                      currentValue={level}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Save Button */}
      {(() => {
        const hasParts = selectedParts.size > 0;
        const hasRunning = runningPayload.length > 0;
        const canSave = hasParts || showSkills || hasRunning;
        const isPending =
          evalMutation.isPending ||
          skillMutation.isPending ||
          runningMutation.isPending;
        return (
          <button
            onClick={handleSave}
            disabled={!canSave || isPending}
            className={cn(
              "w-full py-3.5 rounded-2xl font-medium text-[15px] flex items-center justify-center gap-2 transition-all",
              !canSave
                ? "bg-surface-tertiary text-text-tertiary cursor-not-allowed"
                : saved
                  ? "bg-brand-dark text-white"
                  : "bg-brand hover:bg-brand-dark text-white shadow-lg shadow-brand/20"
            )}
          >
            {saved ? (
              <>
                <Check className="w-4 h-4" /> 저장 완료!
              </>
            ) : isPending ? (
              "저장 중..."
            ) : (
              <>
                <Save className="w-4 h-4" /> 평가 저장
              </>
            )}
          </button>
        );
      })()}
    </div>
  );
}
