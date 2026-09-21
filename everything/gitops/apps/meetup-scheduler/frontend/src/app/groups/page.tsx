"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Plus, Users, ChevronRight, X } from "lucide-react";
import api, { getErrorMessage, type GroupSummary } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth-context";
import { LoginPage } from "@/components/login-page";

export default function GroupsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [groupName, setGroupName] = useState("");

  const { data: groups = [] } = useQuery({
    queryKey: ["groups"],
    queryFn: async () => {
      const res = await api.get("/api/groups");
      return res.data as GroupSummary[];
    },
    enabled: !!user,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => api.post("/api/groups", { name }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      setShowCreate(false);
      setGroupName("");
      router.push(`/groups/${res.data.id}`);
    },
    onError: (err) => alert(getErrorMessage(err, "그룹 생성 실패")),
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-dvh">
        <div className="w-8 h-8 border-3 rounded-full animate-spin"
          style={{ borderColor: "var(--primary)", borderTopColor: "transparent" }} />
      </div>
    );
  }

  if (!user) return <LoginPage />;

  return (
    <AppShell>
      <div className="page-header">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold">내 그룹</h1>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1 font-medium"
            style={{ fontSize: 14, color: "var(--primary)", background: "none", border: "none", cursor: "pointer" }}
          >
            <Plus size={18} /> 그룹 만들기
          </button>
        </div>
      </div>

      {groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center page-enter" style={{ padding: "80px 16px", color: "var(--text-dim)" }}>
          <Users size={48} className="empty-icon" style={{ opacity: 0.3, marginBottom: 16 }} />
          <p style={{ fontSize: 16 }}>아직 그룹이 없어요</p>
          <p style={{ fontSize: 14, marginTop: 4 }}>그룹을 만들어 친구들을 초대해보세요</p>
        </div>
      ) : (
        <div style={{ padding: 16 }} className="space-y-3">
          {groups.map((group) => (
            <button
              key={group.id}
              onClick={() => router.push(`/groups/${group.id}`)}
              className="card-interactive w-full flex items-center justify-between list-enter"
              style={{ textAlign: "left" }}
            >
              <div>
                <div className="font-semibold" style={{ fontSize: 16 }}>{group.name}</div>
                <div className="text-sm" style={{ color: "var(--text-dim)", marginTop: 2 }}>
                  멤버 {group.member_count}명
                </div>
              </div>
              <ChevronRight size={20} style={{ color: "var(--text-dim)", transition: "transform 0.2s" }} />
            </button>
          ))}
        </div>
      )}

      {showCreate && (
        <div className="modal-backdrop">
          <div className="modal-overlay" onClick={() => setShowCreate(false)} />
          <div className="modal-content">
            <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
              <h3 className="text-lg font-bold">새 그룹 만들기</h3>
              <button onClick={() => setShowCreate(false)} className="btn-ghost" style={{ padding: 4 }}>
                <X size={20} />
              </button>
            </div>
            <input
              type="text" className="input" placeholder="그룹 이름 (예: 대학 동기)"
              value={groupName} onChange={(e) => setGroupName(e.target.value)} autoFocus
              style={{ marginBottom: 16 }}
            />
            <button className="btn-primary"
              disabled={!groupName.trim() || createMutation.isPending}
              onClick={() => createMutation.mutate(groupName.trim())}
            >
              {createMutation.isPending ? "만드는 중..." : "만들기"}
            </button>
          </div>
        </div>
      )}
    </AppShell>
  );
}
