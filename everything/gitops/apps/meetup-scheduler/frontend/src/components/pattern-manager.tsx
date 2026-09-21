"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { Plus, X, Trash2, ChevronDown, ChevronUp, RotateCcw } from "lucide-react";
import api, { getErrorMessage, type ShiftPattern } from "@/lib/api";

interface ShiftUnit {
  name: string;
  is_working: boolean;
}

interface PatternFormData {
  name: string;
  units: ShiftUnit[];
  sequence: number[];
  start_date: string;
}

function getUpcomingMonday(): string {
  // 월요일이면 오늘, 그 외에는 다음 주 월요일
  const today = new Date();
  const day = today.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat
  let offset: number;
  if (day === 1) offset = 0;
  else if (day === 0) offset = 1;
  else offset = 8 - day;
  const target = new Date(today);
  target.setDate(today.getDate() + offset);
  return format(target, "yyyy-MM-dd");
}

const PRESET_UNITS: ShiftUnit[] = [
  { name: "근무", is_working: true },
  { name: "비번", is_working: false },
];

const PRESET_PATTERNS = [
  { label: "근근비 (3일 주기)", units: PRESET_UNITS, sequence: [0, 0, 1] },
  { label: "근근근비비 (5일 주기)", units: PRESET_UNITS, sequence: [0, 0, 0, 1, 1] },
  { label: "주5근2비 (7일 주기)", units: PRESET_UNITS, sequence: [0, 0, 0, 0, 0, 1, 1] },
  { label: "근비근비 (4일 주기)", units: PRESET_UNITS, sequence: [0, 1, 0, 1] },
];

const UNIT_COLORS = ["var(--primary)", "var(--warning)", "var(--success)", "#7c3aed", "#ec4899"];

function PatternForm({
  initial, onSubmit, onCancel, submitting, errorMessage,
}: {
  initial?: PatternFormData;
  onSubmit: (data: PatternFormData) => void;
  onCancel: () => void;
  submitting: boolean;
  errorMessage?: string | null;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [units, setUnits] = useState<ShiftUnit[]>(
    initial?.units || [
      { name: "근무", is_working: true },
      { name: "비번", is_working: false },
    ]
  );
  const [sequence, setSequence] = useState<number[]>(initial?.sequence || [0, 0, 1, 1, 2, 2]);
  const [startDate, setStartDate] = useState(initial?.start_date || getUpcomingMonday());

  const addUnit = () => setUnits([...units, { name: "", is_working: true }]);
  const removeUnit = (idx: number) => {
    setUnits(units.filter((_, i) => i !== idx));
    setSequence(sequence.filter((s) => s !== idx).map((s) => (s > idx ? s - 1 : s)));
  };
  const updateUnit = (idx: number, field: keyof ShiftUnit, value: string | boolean) => {
    const updated = [...units];
    updated[idx] = { ...updated[idx], [field]: value };
    setUnits(updated);
  };

  const applyPreset = (preset: (typeof PRESET_PATTERNS)[0]) => {
    setName(preset.label.split(" (")[0]);
    setUnits([...preset.units]);
    setSequence([...preset.sequence]);
  };

  return (
    <div className="space-y-5">
      {/* Presets */}
      {!initial && (
        <div>
          <label className="block text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 8 }}>프리셋</label>
          <div className="flex flex-wrap gap-2">
            {PRESET_PATTERNS.map((p) => (
              <button key={p.label} type="button" onClick={() => applyPreset(p)}
                className="btn-sub" style={{ padding: "6px 14px", fontSize: 13, borderRadius: 20 }}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Name */}
      <div>
        <label className="block text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 6 }}>패턴 이름</label>
        <input type="text" className="input" placeholder="예: 3교대" value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      {/* Units */}
      <div>
        <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
          <label className="text-sm font-medium" style={{ color: "var(--text-sub)" }}>근무 단위</label>
          <button type="button" onClick={addUnit} className="flex items-center gap-1"
            style={{ fontSize: 13, color: "var(--primary)", background: "none", border: "none", cursor: "pointer" }}>
            <Plus size={14} /> 추가
          </button>
        </div>
        <div className="space-y-2">
          {units.map((unit, i) => (
            <div key={i} className="flex items-center gap-2" style={{ padding: 10, borderRadius: 12, background: "var(--bg-sub)" }}>
              <input type="text" placeholder="이름" value={unit.name}
                onChange={(e) => updateUnit(i, "name", e.target.value)}
                style={{
                  flex: 1, padding: "8px 10px", border: "1px solid var(--border)",
                  borderRadius: 8, fontSize: 13, outline: "none", background: "var(--bg)",
                }}
              />
              <button type="button"
                onClick={() => updateUnit(i, "is_working", !unit.is_working)}
                className="text-xs font-medium"
                style={{
                  padding: "6px 12px", borderRadius: 8, border: "none", cursor: "pointer",
                  background: unit.is_working ? "var(--primary)" : "var(--bg-dim)",
                  color: unit.is_working ? "#fff" : "var(--text-dim)",
                }}>
                {unit.is_working ? "근무" : "비번"}
              </button>
              {units.length > 1 && (
                <button type="button" onClick={() => removeUnit(i)}
                  style={{ padding: 4, color: "var(--danger)", background: "none", border: "none", cursor: "pointer" }}>
                  <X size={16} />
                </button>
              )}
            </div>
          ))}
        </div>
        <p className="text-xs" style={{ color: "var(--text-dim)", marginTop: 4 }}>근무/비번을 클릭하여 전환할 수 있습니다. 쉬는 날은 단위명을 "휴무"로 짓지 말고 "비번" 토글로 표시하세요 — 빈 날짜가 곧 휴무입니다.</p>
      </div>

      {/* Sequence */}
      <div>
        <label className="block text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 8 }}>패턴 순서 (반복 주기)</label>
        <div className="flex flex-wrap gap-1.5"
          style={{ minHeight: 40, padding: 12, borderRadius: 12, background: "var(--bg-sub)", marginBottom: 8 }}>
          {sequence.length === 0 && (
            <span className="text-sm" style={{ color: "var(--text-dim)" }}>아래 버튼을 눌러 순서를 추가하세요</span>
          )}
          {sequence.map((unitIdx, seqIdx) => (
            <button key={seqIdx} type="button" onClick={() => setSequence(sequence.filter((_, i) => i !== seqIdx))}
              className="text-sm font-medium transition-opacity"
              style={{
                padding: "4px 10px", borderRadius: 8, color: "#fff", border: "none", cursor: "pointer",
                background: UNIT_COLORS[unitIdx % UNIT_COLORS.length],
              }}
              title="클릭하여 제거">
              {units[unitIdx]?.name || `단위${unitIdx}`}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {units.map((unit, i) => (
            <button key={i} type="button" onClick={() => setSequence([...sequence, i])}
              className="btn-sub" style={{ padding: "6px 12px", fontSize: 13, borderRadius: 20 }}>
              + {unit.name || `단위${i}`}
            </button>
          ))}
        </div>
      </div>

      {/* Start date */}
      <div>
        <label className="block text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 6 }}>패턴 시작일</label>
        <input type="date" className="input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        <p className="text-xs" style={{ color: "var(--text-dim)", marginTop: 4 }}>이 날짜부터 패턴이 반복됩니다 (항상 90일 앞까지 자동 연장)</p>
      </div>

      {errorMessage && (
        <div style={{
          padding: "10px 12px", borderRadius: 8,
          background: "#fef2f2", color: "#b91c1c", fontSize: 13, lineHeight: 1.4,
        }}>
          {errorMessage}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3" style={{ paddingTop: 4 }}>
        <button type="button" onClick={onCancel} className="btn-sub" style={{ flex: 1 }}>취소</button>
        <button type="button" className="btn-primary" style={{ flex: 1 }}
          disabled={!name.trim() || sequence.length === 0 || submitting}
          onClick={() => onSubmit({ name: name.trim(), units, sequence, start_date: startDate })}>
          {submitting ? "저장 중..." : initial ? "수정" : "등록"}
        </button>
      </div>
    </div>
  );
}

export function PatternManager() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editPattern, setEditPattern] = useState<ShiftPattern | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: patterns = [] } = useQuery({
    queryKey: ["patterns"],
    queryFn: async () => { const res = await api.get("/api/patterns"); return res.data as ShiftPattern[]; },
  });

  const createMutation = useMutation({
    mutationFn: (data: PatternFormData) => api.post("/api/patterns", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["patterns"] });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      setShowForm(false);
    },
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: PatternFormData }) => api.put(`/api/patterns/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["patterns"] });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      setEditPattern(null);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/api/patterns/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["patterns"] });
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (err) => alert(getErrorMessage(err, "패턴 삭제 실패")),
  });
  const reapplyMutation = useMutation({
    mutationFn: (id: string) => api.post(`/api/patterns/${id}/apply`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
    onError: (err) => alert(getErrorMessage(err, "패턴 재적용 실패")),
  });

  const getSequencePreview = (pattern: ShiftPattern) =>
    pattern.pattern_data.sequence.map((idx) => pattern.pattern_data.units[idx]?.name || "?").join(" → ");

  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
        <h3 className="text-lg font-bold">교대근무 패턴</h3>
        {!showForm && !editPattern && (
          <button onClick={() => setShowForm(true)} className="flex items-center gap-1"
            style={{ fontSize: 14, fontWeight: 600, color: "var(--primary)", background: "none", border: "none", cursor: "pointer" }}>
            <Plus size={18} /> 새 패턴
          </button>
        )}
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h4 className="font-semibold" style={{ marginBottom: 16 }}>새 패턴 등록</h4>
          <PatternForm onSubmit={(data) => createMutation.mutate(data)} onCancel={() => { setShowForm(false); createMutation.reset(); }} submitting={createMutation.isPending} errorMessage={createMutation.isError ? getErrorMessage(createMutation.error, "패턴 저장 실패") : null} />
        </div>
      )}

      {patterns.length === 0 && !showForm ? (
        <div className="text-center page-enter" style={{ padding: "60px 0", color: "var(--text-dim)" }}>
          <RotateCcw size={40} className="empty-icon" style={{ margin: "0 auto 12px", opacity: 0.3 }} />
          <p>등록된 패턴이 없어요</p>
          <p className="text-sm" style={{ marginTop: 4 }}>교대근무 패턴을 등록하면 자동으로 스케줄이 채워집니다</p>
        </div>
      ) : (
        <div className="space-y-3">
          {patterns.map((pattern) => (
            <div key={pattern.id} className="card list-enter">
              {editPattern?.id === pattern.id ? (
                <PatternForm
                  initial={{ name: pattern.name, units: pattern.pattern_data.units, sequence: pattern.pattern_data.sequence, start_date: pattern.start_date }}
                  onSubmit={(data) => updateMutation.mutate({ id: pattern.id, data })}
                  onCancel={() => { setEditPattern(null); updateMutation.reset(); }}
                  submitting={updateMutation.isPending}
                  errorMessage={updateMutation.isError ? getErrorMessage(updateMutation.error, "패턴 수정 실패") : null}
                />
              ) : (
                <div>
                  <div className="flex items-center justify-between cursor-pointer"
                    onClick={() => setExpandedId(expandedId === pattern.id ? null : pattern.id)}>
                    <div>
                      <div className="font-semibold">{pattern.name}</div>
                      <div className="text-sm" style={{ color: "var(--text-dim)", marginTop: 2 }}>시작: {pattern.start_date}</div>
                    </div>
                    {expandedId === pattern.id
                      ? <ChevronUp size={18} style={{ color: "var(--text-dim)" }} />
                      : <ChevronDown size={18} style={{ color: "var(--text-dim)" }} />
                    }
                  </div>

                  {expandedId === pattern.id && (
                    <div className="expand-enter" style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                      <div style={{ marginBottom: 12 }}>
                        <div className="text-xs" style={{ color: "var(--text-dim)", marginBottom: 4 }}>근무 단위</div>
                        <div className="flex flex-wrap gap-2">
                          {pattern.pattern_data.units.map((unit, i) => (
                            <span key={i} className="text-xs font-medium"
                              style={{ padding: "4px 8px", borderRadius: 8, background: "var(--bg-dim)" }}>
                              {unit.name} ({unit.is_working ? "근무" : "비번"})
                            </span>
                          ))}
                        </div>
                      </div>
                      <div style={{ marginBottom: 16 }}>
                        <div className="text-xs" style={{ color: "var(--text-dim)", marginBottom: 4 }}>반복 순서</div>
                        <div className="text-sm">{getSequencePreview(pattern)}</div>
                      </div>
                      <div className="flex gap-2">
                        <button onClick={() => setEditPattern(pattern)} className="btn-sub" style={{ flex: 1, padding: "8px 0", fontSize: 13 }}>수정</button>
                        <button onClick={() => reapplyMutation.mutate(pattern.id)} disabled={reapplyMutation.isPending}
                          className="btn-sub" style={{ flex: 1, padding: "8px 0", fontSize: 13 }}>
                          {reapplyMutation.isPending ? "적용 중..." : "다시 적용"}
                        </button>
                        <button onClick={() => { if (confirm("패턴과 생성된 스케줄을 모두 삭제할까요?")) deleteMutation.mutate(pattern.id); }}
                          style={{ padding: "8px 12px", borderRadius: 10, fontSize: 13, color: "var(--danger)", background: "#fef2f2", border: "none", cursor: "pointer" }}>
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
