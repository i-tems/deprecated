"use client";

import { useState, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  X,
  Check,
  Loader2,
  AlertCircle,
  ImagePlus,
  Trash2,
  Plus,
  Pencil,
  Send,
} from "lucide-react";
import api from "@/lib/api";

interface AiAction {
  type: "add" | "update" | "delete";
  date: string;
  title: string | null;
}

interface AiResult {
  actions: AiAction[];
  summary: string;
  pattern_detected: {
    name: string;
    units: { name: string; is_working: boolean }[];
    sequence: number[];
  } | null;
}

export function AiScheduleModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [result, setResult] = useState<AiResult | null>(null);
  const [selectedActions, setSelectedActions] = useState<Set<number>>(
    new Set()
  );

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      const formData = new FormData();
      formData.append("message", message);
      for (const file of files) {
        formData.append("files", file);
      }
      const res = await api.post("/api/ai-schedule/analyze", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return res.data as AiResult;
    },
    onSuccess: (data) => {
      const filtered = {
        ...data,
        actions: data.actions.filter(
          (a) => !a.title || !/휴무|비번|OFF$/i.test(a.title.trim())
        ),
      };
      setResult(filtered);
      setSelectedActions(new Set(filtered.actions.map((_, i) => i)));
    },
  });

  const [applyResult, setApplyResult] = useState<{
    added: number; updated: number; deleted: number; errors: string[];
  } | null>(null);

  const applyMutation = useMutation({
    mutationFn: async () => {
      if (!result) return;
      const actions = result.actions.filter((_, i) => selectedActions.has(i));
      const res = await api.post("/api/ai-schedule/apply", { actions });
      return res.data as { added: number; updated: number; deleted: number; errors: string[] };
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      if (data?.errors?.length) {
        setApplyResult(data);
      } else {
        onClose();
      }
    },
  });

  const handleFilesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newFiles = Array.from(e.target.files || []);
    if (files.length + newFiles.length > 5) {
      alert("사진은 최대 5장까지 가능합니다");
      return;
    }
    setFiles((prev) => [...prev, ...newFiles]);
    for (const file of newFiles) {
      const reader = new FileReader();
      reader.onload = () =>
        setPreviews((prev) => [...prev, reader.result as string]);
      reader.readAsDataURL(file);
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    setPreviews((prev) => prev.filter((_, i) => i !== idx));
  };

  const toggleAction = (idx: number) => {
    setSelectedActions((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const canSubmit = message.trim() || files.length > 0;

  const ACTION_STYLES: Record<string, { icon: typeof Plus; color: string; bg: string; label: string }> = {
    add: { icon: Plus, color: "#1a73e8", bg: "#e3f2fd", label: "추가" },
    update: { icon: Pencil, color: "#e65100", bg: "#fff3e0", label: "수정" },
    delete: { icon: Trash2, color: "#d32f2f", bg: "#fef2f2", label: "삭제" },
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-overlay" onClick={onClose} />
      <div className="modal-content modal-enter" style={{ maxWidth: 480 }}>
        <div
          className="flex items-center justify-between"
          style={{ marginBottom: 16 }}
        >
          <h3 className="text-lg font-bold">AI 일정 관리</h3>
          <button
            onClick={onClose}
            className="btn-ghost"
            style={{ padding: 4 }}
          >
            <X size={20} />
          </button>
        </div>

        {!result && (
          <>
            {/* Text input */}
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={"일정을 자유롭게 입력하세요\n예: 4/15~18 주간근무, 4/20 야간으로 변경, 근무표 사진의 빨간 동그라미가 내 일정\n\n※ 휴무·비번·OFF는 등록하지 않습니다 — 빈 날짜가 곧 휴무예요"}
              style={{
                width: "100%",
                minHeight: 100,
                padding: 14,
                borderRadius: 12,
                border: "1.5px solid var(--border)",
                background: "var(--bg-sub)",
                color: "var(--text)",
                fontSize: 14,
                lineHeight: 1.6,
                resize: "vertical",
                outline: "none",
                fontFamily: "inherit",
              }}
              onFocus={(e) =>
                (e.currentTarget.style.borderColor = "var(--primary)")
              }
              onBlur={(e) =>
                (e.currentTarget.style.borderColor = "var(--border)")
              }
            />
            <p
              className="text-xs"
              style={{ color: "var(--text-dim)", marginTop: 6, lineHeight: 1.5 }}
            >
              ※ 휴무·비번·OFF는 등록하지 않습니다 — 빈 날짜가 곧 휴무예요
            </p>

            {/* Image previews */}
            {previews.length > 0 && (
              <div
                className="flex gap-2 flex-wrap"
                style={{ marginTop: 12 }}
              >
                {previews.map((src, i) => (
                  <div
                    key={i}
                    style={{ position: "relative", width: 72, height: 72 }}
                  >
                    <img
                      src={src}
                      alt={`사진 ${i + 1}`}
                      style={{
                        width: 72,
                        height: 72,
                        objectFit: "cover",
                        borderRadius: 10,
                        border: "1px solid var(--border)",
                      }}
                    />
                    <button
                      onClick={() => removeFile(i)}
                      style={{
                        position: "absolute",
                        top: -6,
                        right: -6,
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        background: "var(--danger)",
                        color: "#fff",
                        border: "2px solid var(--bg)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        cursor: "pointer",
                        padding: 0,
                      }}
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Action buttons */}
            <div
              className="flex items-center gap-2"
              style={{ marginTop: 14 }}
            >
              <button
                onClick={() => fileRef.current?.click()}
                className="btn-sub"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  flex: "none",
                }}
              >
                <ImagePlus size={16} />
                <span>사진 {files.length > 0 ? `(${files.length})` : ""}</span>
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                multiple
                className="hidden"
                onChange={handleFilesChange}
              />
              <div style={{ flex: 1 }} />
              <button
                onClick={() => analyzeMutation.mutate()}
                disabled={!canSubmit || analyzeMutation.isPending}
                className="btn-primary"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                {analyzeMutation.isPending ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    분석 중...
                  </>
                ) : (
                  <>
                    <Send size={16} />
                    AI 분석
                  </>
                )}
              </button>
            </div>

            {analyzeMutation.isError && (
              <div
                className="flex items-center gap-2"
                style={{
                  padding: 14,
                  borderRadius: 12,
                  background: "#fef2f2",
                  color: "var(--danger)",
                  marginTop: 14,
                }}
              >
                <AlertCircle size={18} />
                <span className="text-sm">
                  {(analyzeMutation.error as any)?.response?.data?.detail ||
                    "분석에 실패했습니다. 다시 시도해주세요."}
                </span>
              </div>
            )}
          </>
        )}

        {result && (
          <div>
            {/* Summary */}
            <div
              style={{
                padding: 14,
                borderRadius: 12,
                background: "var(--primary-bg)",
                marginBottom: 16,
              }}
            >
              <div
                className="text-sm"
                style={{ color: "var(--primary)", fontWeight: 500 }}
              >
                {result.summary}
              </div>
              {result.pattern_detected && (
                <div
                  className="text-xs"
                  style={{ color: "var(--text-sub)", marginTop: 6 }}
                >
                  패턴 감지: {result.pattern_detected.name}
                </div>
              )}
            </div>

            {/* Action list */}
            <div style={{ marginBottom: 16 }}>
              <div
                className="flex items-center justify-between"
                style={{ marginBottom: 8 }}
              >
                <span
                  className="text-sm font-medium"
                  style={{ color: "var(--text-sub)" }}
                >
                  변경 사항 ({result.actions.length}건)
                </span>
                <button
                  onClick={() => {
                    if (selectedActions.size === result.actions.length)
                      setSelectedActions(new Set());
                    else
                      setSelectedActions(
                        new Set(result.actions.map((_, i) => i))
                      );
                  }}
                  style={{
                    fontSize: 12,
                    color: "var(--primary)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  {selectedActions.size === result.actions.length
                    ? "전체 해제"
                    : "전체 선택"}
                </button>
              </div>
              <div
                className="space-y-1.5"
                style={{ maxHeight: 320, overflowY: "auto" }}
              >
                {result.actions.map((action, i) => {
                  const selected = selectedActions.has(i);
                  const style = ACTION_STYLES[action.type];
                  const Icon = style.icon;
                  return (
                    <button
                      key={i}
                      onClick={() => toggleAction(i)}
                      className="w-full flex items-center gap-3 text-left transition-colors"
                      style={{
                        padding: 12,
                        borderRadius: 12,
                        border: "none",
                        cursor: "pointer",
                        background: selected ? style.bg : "var(--bg-sub)",
                        outline: selected
                          ? `1.5px solid ${style.color}`
                          : "1.5px solid transparent",
                      }}
                    >
                      <div
                        className="flex items-center justify-center flex-shrink-0"
                        style={{
                          width: 20,
                          height: 20,
                          borderRadius: 6,
                          border: selected
                            ? "none"
                            : "2px solid var(--border)",
                          background: selected ? style.color : "transparent",
                        }}
                      >
                        {selected && (
                          <Check size={12} style={{ color: "#fff" }} />
                        )}
                      </div>
                      <div
                        className="flex items-center justify-center"
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: 8,
                          background: style.bg,
                          flexShrink: 0,
                        }}
                      >
                        <Icon size={14} style={{ color: style.color }} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="text-sm font-medium">
                          {action.title || "(제목 없음)"}
                        </div>
                        <div
                          className="text-xs"
                          style={{ color: "var(--text-dim)" }}
                        >
                          {action.date} ·{" "}
                          <span style={{ color: style.color }}>
                            {style.label}
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Apply / Back buttons */}
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setResult(null);
                  setSelectedActions(new Set());
                }}
                className="btn-sub"
                style={{ flex: "none" }}
              >
                다시 입력
              </button>
              <button
                onClick={() => applyMutation.mutate()}
                disabled={
                  selectedActions.size === 0 || applyMutation.isPending
                }
                className="btn-primary"
                style={{ flex: 1 }}
              >
                {applyMutation.isPending
                  ? "반영 중..."
                  : `선택한 ${selectedActions.size}건 반영하기`}
              </button>
            </div>

            {applyMutation.isError && (
              <div
                className="flex items-center gap-2"
                style={{
                  padding: 14,
                  borderRadius: 12,
                  background: "#fef2f2",
                  color: "var(--danger)",
                  marginTop: 12,
                }}
              >
                <AlertCircle size={18} />
                <span className="text-sm">
                  {(applyMutation.error as any)?.response?.data?.detail ||
                    "반영에 실패했습니다. 다시 시도해주세요."}
                </span>
              </div>
            )}

            {applyResult?.errors?.length ? (
              <div
                style={{
                  padding: 14,
                  borderRadius: 12,
                  background: "#fff8e1",
                  color: "#e65100",
                  marginTop: 12,
                }}
              >
                <div className="flex items-center gap-2" style={{ marginBottom: 6 }}>
                  <AlertCircle size={16} />
                  <span className="text-sm font-medium">
                    일부 항목 반영 실패 ({applyResult.errors.length}건)
                  </span>
                </div>
                <ul className="text-xs" style={{ margin: 0, paddingLeft: 20 }}>
                  {applyResult.errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
                {(applyResult.added > 0 || applyResult.updated > 0 || applyResult.deleted > 0) && (
                  <div className="text-xs" style={{ marginTop: 8, color: "var(--text-sub)" }}>
                    성공: 추가 {applyResult.added} / 수정 {applyResult.updated} / 삭제 {applyResult.deleted}
                  </div>
                )}
                <button
                  onClick={onClose}
                  className="btn-sub"
                  style={{ marginTop: 10, width: "100%" }}
                >
                  닫기
                </button>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
