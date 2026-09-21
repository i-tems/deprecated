"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Trash2 } from "lucide-react";
import api, { getErrorMessage, type ScheduleBlock } from "@/lib/api";

interface BlockFormModalProps {
  block: ScheduleBlock | null;
  onClose: () => void;
  onDelete?: () => void;
}

export function BlockFormModal({ block, onClose, onDelete }: BlockFormModalProps) {
  const queryClient = useQueryClient();
  const isNew = !block?.id;

  const defaultDate = block?.date || new Date().toISOString().slice(0, 10);

  const [title, setTitle] = useState(block?.title || "");
  const [date, setDate] = useState(defaultDate);

  const mutation = useMutation({
    mutationFn: async () => {
      const data = {
        title: title || null,
        date,
      };
      if (isNew) return api.post("/api/schedules", data);
      return api.put(`/api/schedules/${block!.id}`, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      onClose();
    },
  });

  const errorMessage = mutation.isError ? getErrorMessage(mutation.error, "저장 중 오류가 발생했습니다") : null;

  return (
    <div className="modal-backdrop">
      <div className="modal-overlay" onClick={onClose} />
      <div className="modal-content">
        <div className="flex items-center justify-between" style={{ marginBottom: 20 }}>
          <h3 className="text-lg font-bold">{isNew ? "일정 추가" : "일정 수정"}</h3>
          <button onClick={onClose} className="btn-ghost" style={{ padding: 4 }}>
            <X size={20} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 6 }}>
              제목 (선택)
            </label>
            <input type="text" className="input" placeholder="예: 야간근무, 회의"
              value={title} onChange={(e) => setTitle(e.target.value)} />
            <p className="text-xs" style={{ color: "var(--text-dim)", marginTop: 4 }}>
              휴무·비번·OFF는 등록하지 않습니다. 빈 날짜가 곧 휴무예요.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 6 }}>날짜</label>
            <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        </div>

        {errorMessage && (
          <div style={{
            marginTop: 12, padding: "10px 12px", borderRadius: 8,
            background: "#fef2f2", color: "#b91c1c", fontSize: 13, lineHeight: 1.4,
          }}>
            {errorMessage}
          </div>
        )}

        <div className="flex gap-3" style={{ marginTop: 24 }}>
          {onDelete && (
            <button onClick={onDelete} className="btn-danger" style={{ flexShrink: 0, width: "auto", padding: "12px 16px" }}>
              <Trash2 size={18} />
            </button>
          )}
          <button onClick={() => mutation.mutate()} disabled={mutation.isPending} className="btn-primary" style={{ flex: 1 }}>
            {mutation.isPending ? "저장 중..." : isNew ? "추가" : "수정"}
          </button>
        </div>
      </div>
    </div>
  );
}
