"use client";

import { useState, useCallback, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  format,
  startOfWeek,
  endOfWeek,
  startOfMonth,
  endOfMonth,
  addWeeks,
  subWeeks,
  addMonths,
  subMonths,
  eachDayOfInterval,
  isSameMonth,
  addDays,
  isToday as isDateToday,
} from "date-fns";
import { ko } from "date-fns/locale";
import { ChevronLeft, ChevronRight, Plus, Trash2, MoreVertical, X, Sparkles } from "lucide-react";
import api, { getErrorMessage, type ScheduleBlock } from "@/lib/api";
import { BlockFormModal } from "@/components/block-form-modal";
import { AiScheduleModal } from "@/components/ai-schedule-modal";

export function ScheduleView() {
  const queryClient = useQueryClient();
  const [currentDate, setCurrentDate] = useState(new Date());
  const [viewMode, setViewMode] = useState<"week" | "month">("month");
  const [showModal, setShowModal] = useState(false);
  const [editBlock, setEditBlock] = useState<ScheduleBlock | null>(null);
  const [showOcr, setShowOcr] = useState(false);
  
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [pressedDay, setPressedDay] = useState<string | null>(null);

  const weekStart = startOfWeek(currentDate, { weekStartsOn: 0 });
  const weekEnd = endOfWeek(currentDate, { weekStartsOn: 0 });
  const weekDays = eachDayOfInterval({ start: weekStart, end: weekEnd });
  const monthStart = startOfMonth(currentDate);
  const monthEnd = endOfMonth(currentDate);

  const queryFrom = viewMode === "month"
    ? startOfWeek(monthStart, { weekStartsOn: 0 })
    : weekStart;
  const queryTo = viewMode === "month"
    ? addDays(endOfWeek(monthEnd, { weekStartsOn: 0 }), 1)
    : addDays(weekEnd, 1);

  const { data: blocks = [] } = useQuery({
    queryKey: ["schedules", format(queryFrom, "yyyy-MM-dd"), format(queryTo, "yyyy-MM-dd")],
    queryFn: async () => {
      const res = await api.get("/api/schedules", {
        params: { from: format(queryFrom, "yyyy-MM-dd"), to: format(queryTo, "yyyy-MM-dd") },
      });
      return res.data as ScheduleBlock[];
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/api/schedules/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
    onError: (err) => alert(getErrorMessage(err, "일정 삭제 실패")),
  });

  const deleteAllMutation = useMutation({
    mutationFn: () => api.delete("/api/schedules/all"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      setShowDeleteConfirm(false);
    },
    onError: (err) => alert(getErrorMessage(err, "전체 삭제 실패")),
  });

  const handlePrev = () => {
    if (viewMode === "month") setCurrentDate(subMonths(currentDate, 1));
    else setCurrentDate(subWeeks(currentDate, 1));
  };
  const handleNext = () => {
    if (viewMode === "month") setCurrentDate(addMonths(currentDate, 1));
    else setCurrentDate(addWeeks(currentDate, 1));
  };

  const handleToday = () => setCurrentDate(new Date());

  const getBlockForDay = useCallback((day: Date): ScheduleBlock | undefined => {
    const dateStr = format(day, "yyyy-MM-dd");
    return blocks.find((b) => b.date === dateStr);
  }, [blocks]);

  const handleDayClick = (day: Date) => {
    const existing = getBlockForDay(day);
    if (existing) {
      setEditBlock(existing);
      setShowModal(true);
    } else {
      setEditBlock({
        id: "", user_id: "", title: null,
        date: format(day, "yyyy-MM-dd"),
        pattern_id: null, created_at: "",
      });
      setShowModal(true);
    }
  };

  const DAY_NAMES = ["일", "월", "화", "수", "목", "금", "토"];

  /* ========== Month View ========== */
  const renderMonthView = () => {
    const calStart = startOfWeek(monthStart, { weekStartsOn: 0 });
    const calEnd = endOfWeek(monthEnd, { weekStartsOn: 0 });
    const calDays = eachDayOfInterval({ start: calStart, end: calEnd });
    const weeks: Date[][] = [];
    for (let i = 0; i < calDays.length; i += 7) weeks.push(calDays.slice(i, i + 7));

    return (
      <div>
        <div className="grid grid-cols-7" style={{ borderBottom: "1px solid var(--border)" }}>
          {DAY_NAMES.map((d, i) => (
            <div
              key={d}
              className="text-center text-xs font-medium py-2"
              style={{ color: i === 0 ? "#ea4335" : i === 6 ? "#4285f4" : "var(--text-dim)" }}
            >
              {d}
            </div>
          ))}
        </div>
        {weeks.map((week, wi) => (
          <div key={wi} className="grid grid-cols-7">
            {week.map((day, di) => {
              const block = getBlockForDay(day);
              const isCurrentMonth = isSameMonth(day, currentDate);
              const today = isDateToday(day);
              const isSun = di === 0;
              const isSat = di === 6;
              const isPattern = !!block?.pattern_id;
              const dayKey = day.toISOString();
              const isPressed = pressedDay === dayKey;
              return (
                <button
                  key={dayKey}
                  onClick={() => handleDayClick(day)}
                  onPointerDown={() => setPressedDay(dayKey)}
                  onPointerUp={() => setPressedDay(null)}
                  onPointerLeave={() => setPressedDay(null)}
                  className="cal-day-cell"
                  style={{
                    padding: "4px 6px",
                    minHeight: 80,
                    opacity: isCurrentMonth ? 1 : 0.3,
                    background: today ? "#e8f0fe" : "transparent",
                    border: "none",
                    borderBottom: "1px solid var(--border)",
                    borderRight: di < 6 ? "1px solid var(--border)" : undefined,
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "background 0.15s, transform 0.1s",
                    transform: isPressed ? "scale(0.96)" : "scale(1)",
                  }}
                >
                  <div
                    className="text-xs flex items-center justify-center rounded-full"
                    style={{
                      width: 26, height: 26, marginBottom: 2,
                      fontWeight: today ? 700 : 500,
                      transition: "transform 0.15s",
                      ...(today
                        ? { background: "var(--primary)", color: "#fff" }
                        : { color: isSun ? "#ea4335" : isSat ? "#4285f4" : undefined }),
                    }}
                  >
                    {format(day, "d")}
                  </div>
                  {block && (
                    <div
                      className="truncate block-label-enter"
                      style={{
                        fontSize: 11,
                        lineHeight: 1.4,
                        padding: "2px 6px",
                        borderRadius: 4,
                        borderLeft: `3px solid ${isPattern ? "var(--warning)" : "#1a73e8"}`,
                        background: isPattern ? "#fff3e0" : "#e3f2fd",
                        color: isPattern ? "#e65100" : "#1a73e8",
                        fontWeight: 500,
                      }}
                    >
                      {isPattern && "🔁 "}{block.title || "일정"}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    );
  };

  /* ========== Week View ========== */
  const renderWeekView = () => (
    <div className="grid grid-cols-7" style={{ minHeight: "calc(100dvh - 200px)" }}>
      {weekDays.map((day, di) => {
        const block = getBlockForDay(day);
        const today = isDateToday(day);
        const isSun = di === 0;
        const isSat = di === 6;
        const isPattern = !!block?.pattern_id;
        const dayKey = day.toISOString();
        const isPressed = pressedDay === dayKey;
        return (
          <button
            key={dayKey}
            onClick={() => handleDayClick(day)}
            onPointerDown={() => setPressedDay(dayKey)}
            onPointerUp={() => setPressedDay(null)}
            onPointerLeave={() => setPressedDay(null)}
            className="cal-day-cell"
            style={{
              padding: "12px 4px",
              borderRight: di < 6 ? "1px solid var(--border)" : undefined,
              background: today ? "#e8f0fe" : "transparent",
              border: "none",
              borderRightStyle: di < 6 ? "solid" : undefined,
              borderRightWidth: di < 6 ? 1 : undefined,
              borderRightColor: di < 6 ? "var(--border)" : undefined,
              cursor: "pointer",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
              transition: "background 0.15s, transform 0.1s",
              transform: isPressed ? "scale(0.95)" : "scale(1)",
            }}
          >
            <div
              className="text-xs font-medium"
              style={{ color: today ? "var(--primary)" : isSun ? "#ea4335" : isSat ? "#4285f4" : "var(--text-dim)" }}
            >
              {format(day, "EEE", { locale: ko })}
            </div>
            <div
              className="flex items-center justify-center rounded-full"
              style={{
                width: 40, height: 40, fontSize: 18,
                fontWeight: today ? 600 : 400,
                transition: "transform 0.15s",
                ...(today
                  ? { background: "var(--primary)", color: "#fff" }
                  : { color: isSun ? "#ea4335" : isSat ? "#4285f4" : "var(--text)" }),
              }}
            >
              {format(day, "d")}
            </div>
            {block && (
              <div
                className="w-full truncate block-label-enter"
                style={{
                  fontSize: 12,
                  padding: "6px 8px",
                  borderRadius: 6,
                  borderLeft: `3px solid ${isPattern ? "var(--warning)" : "#1a73e8"}`,
                  background: isPattern ? "#fff3e0" : "#e3f2fd",
                  color: isPattern ? "#e65100" : "#1a73e8",
                  fontWeight: 500,
                  textAlign: "left",
                }}
              >
                {isPattern && "🔁 "}{block.title || "일정"}
              </div>
            )}
            {!block && (
              <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 4 }}>-</div>
            )}
          </button>
        );
      })}
    </div>
  );

  /* ========== Header ========== */
  const headerTitle = viewMode === "month"
    ? format(currentDate, "yyyy년 M월", { locale: ko })
    : `${format(weekStart, "M/d")} - ${format(weekEnd, "M/d")}`;

  const VIEW_LABELS = { month: "월", week: "주" } as const;

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <button
              onClick={handleToday}
              className="btn-today"
            >
              오늘
            </button>
            <div className="flex items-center">
              <button onClick={handlePrev} className="nav-arrow">
                <ChevronLeft size={20} />
              </button>
              <button onClick={handleNext} className="nav-arrow">
                <ChevronRight size={20} />
              </button>
            </div>
            <h2 className="text-lg font-semibold" style={{ color: "var(--text)", whiteSpace: "nowrap" }}>
              {headerTitle}
            </h2>
          </div>

          <div className="flex items-center gap-2">
            {/* Delete all */}
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="nav-arrow"
              title="전체 삭제"
              style={{ color: "var(--text-dim)" }}
            >
              <Trash2 size={18} />
            </button>
            {/* View mode toggle */}
            <div className="view-toggle">
              {(["week", "month"] as const).map((mode) => (
                <button
                  key={mode}
                  className={`view-toggle-btn ${viewMode === mode ? "active" : ""}`}
                  onClick={() => setViewMode(mode)}
                >
                  {VIEW_LABELS[mode]}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Calendar body */}
      <div className="overflow-auto" style={{ maxHeight: "calc(100dvh - 100px - var(--bottom-nav-h, 72px))" }}>
        {viewMode === "month" ? renderMonthView() : renderWeekView()}
      </div>

      {/* AI Schedule FAB */}
      <button
        onClick={() => setShowOcr(true)}
        className="fab-main fixed z-40"
        style={{ bottom: 'calc(var(--bottom-nav-h, 72px) + 16px)', right: 16 }}
      >
        <Sparkles size={24} />
      </button>

      {/* Delete confirm modal */}
      {showDeleteConfirm && (
        <div className="modal-backdrop">
          <div className="modal-overlay" onClick={() => setShowDeleteConfirm(false)} />
          <div className="modal-content modal-enter" style={{ maxWidth: 360, textAlign: "center" }}>
            <div style={{ padding: "8px 0 20px" }}>
              <div className="flex items-center justify-center" style={{
                width: 56, height: 56, borderRadius: "50%", margin: "0 auto 16px",
                background: "#fef2f2",
              }}>
                <Trash2 size={28} style={{ color: "var(--danger)" }} />
              </div>
              <h3 className="text-lg font-bold" style={{ marginBottom: 8 }}>전체 일정 삭제</h3>
              <p className="text-sm" style={{ color: "var(--text-sub)" }}>
                등록된 모든 스케줄이 삭제됩니다.<br />(패턴으로 생성된 일정은 유지됩니다)<br />이 작업은 되돌릴 수 없습니다.
              </p>
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="btn-sub"
                style={{ flex: 1 }}
              >
                취소
              </button>
              <button
                onClick={() => deleteAllMutation.mutate()}
                disabled={deleteAllMutation.isPending}
                className="btn-danger"
                style={{ flex: 1 }}
              >
                {deleteAllMutation.isPending ? "삭제 중..." : "전체 삭제"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showModal && (
        <BlockFormModal
          block={editBlock}
          onClose={() => { setShowModal(false); setEditBlock(null); }}
          onDelete={editBlock?.id ? () => {
            deleteMutation.mutate(editBlock.id);
            setShowModal(false); setEditBlock(null);
          } : undefined}
        />
      )}
      {showOcr && <AiScheduleModal onClose={() => setShowOcr(false)} />}
    </div>
  );
}
