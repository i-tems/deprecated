"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  format, startOfWeek, endOfWeek, startOfMonth, endOfMonth,
  addWeeks, subWeeks, addMonths, subMonths,
  eachDayOfInterval, isSameDay, isSameMonth, addDays,
} from "date-fns";
import { ko } from "date-fns/locale";
import {
  ChevronLeft, ChevronRight, Copy, Check, Settings, ArrowLeft, Users, Trash2, LogOut, X,
} from "lucide-react";
import api, { getErrorMessage, type GroupDetail, type MemberSchedule, type AvailabilitySlot } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { LoginPage } from "@/components/login-page";
import { AppShell } from "@/components/app-shell";

const MEMBER_COLORS = [
  "#3182f6", "#f04452", "#ff9100", "#00c853", "#7c3aed",
  "#ec4899", "#06b6d4", "#f59e0b", "#8b5cf6", "#10b981",
];

export default function GroupDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user, loading } = useAuth();
  const queryClient = useQueryClient();

  const [currentDate, setCurrentDate] = useState(new Date());
  const [viewMode, setViewMode] = useState<"week" | "month">("month");
  const [copied, setCopied] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [minMembers, setMinMembers] = useState(0);
  const [selectedMembers, setSelectedMembers] = useState<Set<string>>(new Set());
  const [hoveredDay, setHoveredDay] = useState<string | null>(null);

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

  const { data: group, isPending: groupPending, error: groupError } = useQuery({
    queryKey: ["group", id],
    queryFn: async () => { const res = await api.get(`/api/groups/${id}`); return res.data as GroupDetail; },
    enabled: !!user && !!id,
  });

  const fromStr = format(queryFrom, "yyyy-MM-dd");
  const toStr = format(queryTo, "yyyy-MM-dd");

  const { data: scheduleData } = useQuery({
    queryKey: ["group-schedules", id, fromStr, toStr],
    queryFn: async () => {
      const res = await api.get(`/api/groups/${id}/schedules`, {
        params: { from: fromStr, to: toStr },
      });
      return res.data as { members: MemberSchedule[] };
    },
    enabled: !!group,
  });

  const { data: availability = [] } = useQuery({
    queryKey: ["availability", id, fromStr, toStr],
    queryFn: async () => {
      const res = await api.get(`/api/groups/${id}/availability`, {
        params: { from: fromStr, to: toStr, min_members: 1 },
      });
      return res.data as AvailabilitySlot[];
    },
    enabled: !!group,
  });

  const isAdmin = group?.members.find((m) => m.user_id === user?.id)?.role === "ADMIN";
  const totalMembers = group?.members.length || 0;
  const members = scheduleData?.members || [];

  // Members who registered schedules for the current month
  const currentMonthPrefix = format(monthStart, "yyyy-MM");
  const registeredMemberIds = new Set<string>();
  for (const member of members) {
    if (member.blocks.some((b) => b.date.startsWith(currentMonthPrefix))) {
      registeredMemberIds.add(member.user_id);
    }
  }

  const filteredTotal = selectedMembers.size > 0
    ? [...selectedMembers].filter((id) => registeredMemberIds.has(id)).length
    : registeredMemberIds.size;

  const deleteMutation = useMutation({
    mutationFn: () => api.delete(`/api/groups/${id}`),
    onSuccess: () => { router.push("/groups"); queryClient.invalidateQueries({ queryKey: ["groups"] }); },
    onError: (err) => alert(getErrorMessage(err, "그룹 삭제 실패")),
  });
  const leaveMutation = useMutation({
    mutationFn: () => api.delete(`/api/groups/${id}/members/${user?.id}`),
    onSuccess: () => { router.push("/groups"); queryClient.invalidateQueries({ queryKey: ["groups"] }); },
    onError: (err) => alert(getErrorMessage(err, "그룹 나가기 실패")),
  });
  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) => api.delete(`/api/groups/${id}/members/${userId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["group", id] });
      queryClient.invalidateQueries({ queryKey: ["group-schedules", id] });
    },
    onError: (err) => alert(getErrorMessage(err, "멤버 제거 실패")),
  });

  const copyInviteLink = async () => {
    if (!group) return;
    await navigator.clipboard.writeText(`${window.location.origin}/join/${group.invite_code}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const toggleMember = (userId: string) => {
    setSelectedMembers((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId); else next.add(userId);
      return next;
    });
  };

  const getAvailabilityForDay = (day: Date): AvailabilitySlot | undefined => {
    const dateStr = format(day, "yyyy-MM-dd");
    const slot = availability.find((a) => a.date === dateStr);
    if (!slot || filteredTotal === 0) return undefined;
    // Filter to selected members, then exclude unregistered members
    const targetMembers = selectedMembers.size > 0 ? selectedMembers : null;
    const filteredAvailable = (targetMembers
      ? slot.available_members.filter((uid) => targetMembers.has(uid))
      : slot.available_members
    ).filter((uid) => registeredMemberIds.has(uid));
    const total = filteredTotal;
    const threshold = minMembers || total;
    if (filteredAvailable.length < threshold) return undefined;
    return {
      ...slot,
      available_count: filteredAvailable.length,
      available_members: filteredAvailable,
      total_members: total,
    };
  };

  const getBusyMembersForDay = (day: Date) => {
    const dateStr = format(day, "yyyy-MM-dd");
    const busyMembers: { userId: string; title: string | null }[] = [];
    for (const member of members) {
      if (selectedMembers.size > 0 && !selectedMembers.has(member.user_id)) continue;
      const block = member.blocks.find((b) => b.date === dateStr);
      if (block) {
        busyMembers.push({ userId: member.user_id, title: block.title });
      }
    }
    return busyMembers;
  };

  const getHeatmapColor = (slot: AvailabilitySlot | undefined, total: number) => {
    if (total === 0) return "var(--bg-sub)";
    if (!slot) return "#fecaca";
    const ratio = slot.available_count / total;
    if (ratio >= 1) return "#a7f3d0";
    if (ratio >= 0.75) return "#d1fae5";
    if (ratio >= 0.5) return "#fef9c3";
    if (ratio >= 0.25) return "#fed7aa";
    return "#fecaca";
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-dvh">
        <div className="w-8 h-8 border-3 rounded-full animate-spin"
          style={{ borderColor: "var(--primary)", borderTopColor: "transparent" }} />
      </div>
    );
  }

  if (!user) return <LoginPage />;

  if (groupError) {
    return (
      <AppShell>
        <div className="flex flex-col items-center justify-center" style={{ minHeight: "60vh", padding: 24, textAlign: "center", gap: 12 }}>
          <h1 className="text-lg font-bold">그룹을 불러오지 못했습니다</h1>
          <p style={{ color: "var(--text-dim)", maxWidth: 320 }}>{getErrorMessage(groupError, "잠시 후 다시 시도해주세요")}</p>
          <button onClick={() => router.push("/groups")} className="btn-primary" style={{ width: "auto", padding: "10px 16px" }}>내 그룹으로 돌아가기</button>
        </div>
      </AppShell>
    );
  }

  if (groupPending || !group) {
    return (
      <div className="flex items-center justify-center min-h-dvh">
        <div className="w-8 h-8 border-3 rounded-full animate-spin"
          style={{ borderColor: "var(--primary)", borderTopColor: "transparent" }} />
      </div>
    );
  }

  return (
    <AppShell>
      {/* Header */}
      <div className="page-header" style={{ paddingBottom: 0 }}>
        {/* Top row */}
        <div className="flex items-center justify-between" style={{ paddingBottom: 12 }}>
          <div className="flex items-center gap-2">
            <button onClick={() => router.push("/groups")} className="btn-ghost" style={{ padding: 4 }}>
              <ArrowLeft size={20} />
            </button>
            <h1 className="text-lg font-bold">{group.name}</h1>
            <span className="text-sm" style={{ color: "var(--text-dim)" }}>{totalMembers}명</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={copyInviteLink} className="btn-sub" style={{ padding: "6px 12px", fontSize: 13 }}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? "복사됨" : "초대"}
            </button>
            <button onClick={() => setShowSettings(!showSettings)} className="btn-ghost" style={{ padding: 6 }}>
              <Settings size={18} />
            </button>
          </div>
        </div>

        {/* Member chips */}
        <div className="flex gap-2 overflow-x-auto" style={{ paddingBottom: 12 }}>
          {group.members.map((member, i) => {
            const color = MEMBER_COLORS[i % MEMBER_COLORS.length];
            const selected = selectedMembers.size === 0 || selectedMembers.has(member.user_id);
            return (
              <button
                key={member.user_id}
                onClick={() => toggleMember(member.user_id)}
                className="chip flex items-center gap-1.5 font-medium whitespace-nowrap"
                style={{
                  padding: "5px 12px", fontSize: 13,
                  background: selected ? `${color}20` : `${color}08`, color,
                  opacity: selected ? 1 : 0.4,
                  transition: "all 0.2s",
                  border: selected ? `1.5px solid ${color}40` : "1.5px solid transparent",
                }}
              >
                <div className="rounded-full" style={{
                  width: 7, height: 7, background: color,
                  transition: "transform 0.2s",
                  transform: selected ? "scale(1)" : "scale(0.7)",
                }} />
                {member.user_name}
                {!registeredMemberIds.has(member.user_id) && (
                  <span style={{ fontSize: 10, opacity: 0.6 }}>미등록</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Date nav */}
        <div className="flex items-center justify-between" style={{ paddingBottom: 10 }}>
          <div className="flex items-center gap-1">
            <button onClick={() => setCurrentDate(viewMode === "month" ? subMonths(currentDate, 1) : subWeeks(currentDate, 1))} className="btn-ghost" style={{ padding: 4 }}>
              <ChevronLeft size={18} />
            </button>
            <span className="text-sm font-medium">
              {viewMode === "month"
                ? format(currentDate, "yyyy년 M월", { locale: ko })
                : `${format(weekStart, "M/d", { locale: ko })} - ${format(weekEnd, "M/d", { locale: ko })}`}
            </span>
            <button onClick={() => setCurrentDate(viewMode === "month" ? addMonths(currentDate, 1) : addWeeks(currentDate, 1))} className="btn-ghost" style={{ padding: 4 }}>
              <ChevronRight size={18} />
            </button>
          </div>
          <div className="flex items-center gap-2">
            <select
              className="input"
              style={{ width: "auto", padding: "4px 8px", fontSize: 13 }}
              value={minMembers}
              onChange={(e) => setMinMembers(Number(e.target.value))}
            >
              <option value={0}>전원</option>
              {Array.from({ length: totalMembers }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>{n}명 이상</option>
              ))}
            </select>
            <div className="view-toggle">
              {(["week", "month"] as const).map((mode) => (
                <button
                  key={mode}
                  className={`view-toggle-btn ${viewMode === mode ? "active" : ""}`}
                  onClick={() => setViewMode(mode)}
                >
                  {mode === "week" ? "주" : "월"}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Day headers (week view) */}
        {viewMode === "week" && (
          <div className="grid grid-cols-7" style={{ borderBottom: "1px solid var(--border)" }}>
            {weekDays.map((day) => {
              const isToday = isSameDay(day, new Date());
              return (
                <div key={day.toISOString()} className="text-center" style={{
                  padding: "4px 0",
                  color: isToday ? "var(--primary)" : undefined,
                  fontWeight: isToday ? 700 : undefined,
                }}>
                  <div className="text-xs" style={{ color: isToday ? "var(--primary)" : "var(--text-dim)" }}>
                    {format(day, "EEE", { locale: ko })}
                  </div>
                  <div className="text-sm">{format(day, "d")}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Calendar grid */}
      <div style={{ padding: "0 4px" }}>
        {viewMode === "week" ? (
          /* Week view */
          <div className="grid grid-cols-7">
            {weekDays.map((day) => {
              const slot = getAvailabilityForDay(day);
              const busyMembers = getBusyMembersForDay(day);
              const bg = getHeatmapColor(slot, filteredTotal);
              const dayStr = format(day, "yyyy-MM-dd");
              return (
                <div
                  key={day.toISOString()}
                  className="relative"
                  style={{
                    minHeight: 120,
                    padding: 6,
                    background: bg,
                    borderBottom: "1px solid var(--border)",
                    borderRight: "1px solid var(--border)",
                    transition: "background 0.3s, transform 0.15s",
                    cursor: "pointer",
                    overflow: "visible",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.transform = "scale(1.02)"; e.currentTarget.style.zIndex = "10"; setHoveredDay(dayStr); }}
                  onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; e.currentTarget.style.zIndex = "0"; setHoveredDay(null); }}
                >
                  <div className="text-center" style={{ marginBottom: 6 }}>
                    <span className="text-xs font-medium" style={{ color: "var(--text-sub)" }}>
                      {filteredTotal === 0 ? "-" : slot ? `${slot.available_count}/${slot.total_members}` : `0/${filteredTotal}`}
                    </span>
                  </div>
                  {busyMembers.length > 0 && (
                    <div className="flex flex-wrap gap-1 justify-center">
                      {busyMembers.map(({ userId }) => {
                        const memberIdx = group.members.findIndex((m) => m.user_id === userId);
                        const color = MEMBER_COLORS[memberIdx % MEMBER_COLORS.length];
                        return (
                          <div key={userId} className="rounded-full" style={{ width: 8, height: 8, background: color }}
                            title={group.members[memberIdx]?.user_name + " (바쁨)"} />
                        );
                      })}
                    </div>
                  )}
                  {slot && slot.available_count === filteredTotal && (
                    <div className="text-center block-label-enter" style={{ marginTop: 4 }}>
                      <span style={{ fontSize: 10, color: "#059669", fontWeight: 600 }}>전원 가능</span>
                    </div>
                  )}
                  {hoveredDay === dayStr && busyMembers.length > 0 && (
                    <div style={{
                      position: 'absolute', bottom: '100%', left: '50%', transform: 'translateX(-50%)',
                      marginBottom: 4, background: 'white', borderRadius: 10, padding: '8px 12px',
                      boxShadow: '0 4px 16px rgba(0,0,0,0.15)', border: '1px solid var(--border)',
                      fontSize: 11, whiteSpace: 'nowrap', zIndex: 50,
                    }}>
                      {busyMembers.map(({ userId, title }) => {
                        const mi = group.members.findIndex((m) => m.user_id === userId);
                        const color = MEMBER_COLORS[mi % MEMBER_COLORS.length];
                        return (
                          <div key={userId} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 0' }}>
                            <div style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
                            <span style={{ fontWeight: 500 }}>{group.members[mi]?.user_name}</span>
                            {title && <span style={{ color: 'var(--text-dim)' }}>{title}</span>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          /* Month view */
          (() => {
            const DAY_NAMES = ["일", "월", "화", "수", "목", "금", "토"];
            const calStart = startOfWeek(monthStart, { weekStartsOn: 0 });
            const calEnd = endOfWeek(monthEnd, { weekStartsOn: 0 });
            const calDays = eachDayOfInterval({ start: calStart, end: calEnd });
            const weeks: Date[][] = [];
            for (let i = 0; i < calDays.length; i += 7) weeks.push(calDays.slice(i, i + 7));

            return (
              <div>
                <div className="grid grid-cols-7" style={{ borderBottom: "1px solid var(--border)" }}>
                  {DAY_NAMES.map((d, i) => (
                    <div key={d} className="text-center text-xs font-medium py-2"
                      style={{ color: i === 0 ? "#ea4335" : i === 6 ? "#4285f4" : "var(--text-dim)" }}>
                      {d}
                    </div>
                  ))}
                </div>
                {weeks.map((week, wi) => (
                  <div key={wi} className="grid grid-cols-7">
                    {week.map((day, di) => {
                      const slot = getAvailabilityForDay(day);
                      const busyMembers = getBusyMembersForDay(day);
                      const isCurrentMonth = isSameMonth(day, currentDate);
                      const isToday = isSameDay(day, new Date());
                      const isSun = di === 0;
                      const isSat = di === 6;
                      const bg = isCurrentMonth ? getHeatmapColor(slot, filteredTotal) : "transparent";
                      const dayStr = format(day, "yyyy-MM-dd");
                      return (
                        <div
                          key={day.toISOString()}
                          onMouseEnter={() => setHoveredDay(dayStr)}
                          onMouseLeave={() => setHoveredDay(null)}
                          style={{
                            position: "relative",
                            minHeight: 72,
                            padding: "4px 4px",
                            opacity: isCurrentMonth ? 1 : 0.25,
                            background: isToday ? "#e8f0fe" : bg,
                            borderBottom: "1px solid var(--border)",
                            borderRight: di < 6 ? "1px solid var(--border)" : undefined,
                            transition: "background 0.3s",
                            overflow: "visible",
                          }}
                        >
                          {/* Day number */}
                          <div className="flex items-center justify-center">
                            <div className="text-xs flex items-center justify-center rounded-full"
                              style={{
                                width: 24, height: 24,
                                fontWeight: isToday ? 700 : 500,
                                ...(isToday
                                  ? { background: "var(--primary)", color: "#fff" }
                                  : { color: isSun ? "#ea4335" : isSat ? "#4285f4" : undefined }),
                              }}>
                              {format(day, "d")}
                            </div>
                          </div>
                          {/* Availability info */}
                          {isCurrentMonth && (
                            <>
                              <div className="text-center" style={{ marginTop: 2 }}>
                                <span style={{ fontSize: 10, color: "var(--text-dim)" }}>
                                  {filteredTotal === 0 ? "-" : slot ? `${slot.available_count}/${slot.total_members}` : `0/${filteredTotal}`}
                                </span>
                              </div>
                              {busyMembers.length > 0 && (
                                <div className="flex flex-wrap gap-0.5 justify-center" style={{ marginTop: 2 }}>
                                  {busyMembers.slice(0, 4).map(({ userId }) => {
                                    const memberIdx = group.members.findIndex((m) => m.user_id === userId);
                                    const color = MEMBER_COLORS[memberIdx % MEMBER_COLORS.length];
                                    return (
                                      <div key={userId} className="rounded-full"
                                        style={{ width: 6, height: 6, background: color }}
                                        title={group.members[memberIdx]?.user_name + " (바쁨)"} />
                                    );
                                  })}
                                  {busyMembers.length > 4 && (
                                    <span style={{ fontSize: 8, color: "var(--text-dim)" }}>+{busyMembers.length - 4}</span>
                                  )}
                                </div>
                              )}
                              {slot && slot.available_count === filteredTotal && (
                                <div className="text-center" style={{ marginTop: 2 }}>
                                  <span style={{ fontSize: 9, color: "#059669", fontWeight: 600 }}>전원 가능</span>
                                </div>
                              )}
                            </>
                          )}
                          {hoveredDay === dayStr && isCurrentMonth && busyMembers.length > 0 && (
                            <div style={{
                              position: 'absolute', bottom: '100%', left: '50%', transform: 'translateX(-50%)',
                              marginBottom: 4, background: 'white', borderRadius: 10, padding: '8px 12px',
                              boxShadow: '0 4px 16px rgba(0,0,0,0.15)', border: '1px solid var(--border)',
                              fontSize: 11, whiteSpace: 'nowrap', zIndex: 50,
                            }}>
                              {busyMembers.map(({ userId, title }) => {
                                const mi = group.members.findIndex((m) => m.user_id === userId);
                                const color = MEMBER_COLORS[mi % MEMBER_COLORS.length];
                                return (
                                  <div key={userId} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 0' }}>
                                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
                                    <span style={{ fontWeight: 500 }}>{group.members[mi]?.user_name}</span>
                                    {title && <span style={{ color: 'var(--text-dim)' }}>{title}</span>}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            );
          })()
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-5 text-xs page-enter" style={{ padding: "12px 16px", color: "var(--text-dim)" }}>
        <div className="flex items-center gap-1.5">
          <div className="rounded" style={{ width: 12, height: 12, background: "#fecaca", border: "1px solid var(--border)" }} />
          적음
        </div>
        <div className="flex items-center gap-1.5">
          <div className="rounded" style={{ width: 12, height: 12, background: "#fef9c3", border: "1px solid var(--border)" }} />
          보통
        </div>
        <div className="flex items-center gap-1.5">
          <div className="rounded" style={{ width: 12, height: 12, background: "#a7f3d0", border: "1px solid var(--border)" }} />
          전원
        </div>
      </div>

      {/* Settings modal */}
      {showSettings && (
        <div className="modal-backdrop">
          <div className="modal-overlay" onClick={() => setShowSettings(false)} />
          <div className="modal-content">
            <div className="flex items-center justify-between" style={{ marginBottom: 20 }}>
              <h3 className="text-lg font-bold">그룹 설정</h3>
              <button onClick={() => setShowSettings(false)} className="btn-ghost" style={{ padding: 4 }}>
                <X size={20} />
              </button>
            </div>

            {/* Members */}
            <div style={{ marginBottom: 24 }}>
              <h4 className="text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 8 }}>
                멤버 ({group.members.length}명)
              </h4>
              <div className="space-y-1">
                {group.members.map((member) => (
                  <div key={member.user_id} className="flex items-center justify-between" style={{ padding: "8px 0" }}>
                    <div className="flex items-center gap-3">
                      {member.user_avatar_url ? (
                        <img src={member.user_avatar_url} alt="" className="rounded-full" style={{ width: 32, height: 32 }} />
                      ) : (
                        <div className="rounded-full flex items-center justify-center"
                          style={{ width: 32, height: 32, background: "var(--bg-dim)" }}>
                          <Users size={14} />
                        </div>
                      )}
                      <div>
                        <div className="text-sm font-medium">{member.user_name}</div>
                        <div className="text-xs" style={{ color: "var(--text-dim)" }}>
                          {member.role === "ADMIN" ? "관리자" : "멤버"}
                        </div>
                      </div>
                    </div>
                    {isAdmin && member.user_id !== user?.id && (
                      <button onClick={() => removeMemberMutation.mutate(member.user_id)}
                        style={{ fontSize: 13, color: "var(--danger)", background: "none", border: "none", cursor: "pointer" }}>
                        내보내기
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Invite link */}
            <div style={{ marginBottom: 24 }}>
              <h4 className="text-sm font-medium" style={{ color: "var(--text-sub)", marginBottom: 8 }}>초대 링크</h4>
              <div className="flex gap-2">
                <input type="text" className="input" readOnly style={{ flex: 1, fontSize: 13 }}
                  value={`${typeof window !== "undefined" ? window.location.origin : ""}/join/${group.invite_code}`} />
                <button onClick={copyInviteLink} className="btn-sub" style={{ padding: "10px 14px" }}>
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                </button>
              </div>
            </div>

            {/* Danger zone */}
            <div className="space-y-2">
              {!isAdmin && (
                <button onClick={() => leaveMutation.mutate()}
                  className="w-full flex items-center justify-center gap-2 font-medium"
                  style={{ padding: 14, color: "var(--danger)", background: "none", border: "none", cursor: "pointer", fontSize: 15 }}>
                  <LogOut size={18} /> 그룹 나가기
                </button>
              )}
              {isAdmin && (
                <button onClick={() => { if (confirm("정말 그룹을 삭제하시겠어요?")) deleteMutation.mutate(); }}
                  className="w-full flex items-center justify-center gap-2 font-medium"
                  style={{ padding: 14, color: "var(--danger)", background: "none", border: "none", cursor: "pointer", fontSize: 15 }}>
                  <Trash2 size={18} /> 그룹 삭제
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
