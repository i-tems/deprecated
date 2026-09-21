"use client";

import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/app-shell";
import { LoginPage } from "@/components/login-page";
import { LogOut } from "lucide-react";

export default function MyPage() {
  const { user, loading, logout } = useAuth();

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
        <h1 className="text-lg font-bold">내 정보</h1>
      </div>

      <div className="page-enter" style={{ padding: 16 }}>
        <div className="card flex items-center gap-4">
          {user.avatar_url ? (
            <img src={user.avatar_url} alt="" className="rounded-full"
              style={{ width: 56, height: 56, transition: "transform 0.2s" }}
              onMouseEnter={(e) => { e.currentTarget.style.transform = "scale(1.08)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
            />
          ) : (
            <div className="rounded-full flex items-center justify-center text-xl"
              style={{ width: 56, height: 56, background: "var(--bg-dim)", transition: "transform 0.2s" }}
              onMouseEnter={(e) => { e.currentTarget.style.transform = "scale(1.08)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
            >
              {user.name[0]}
            </div>
          )}
          <div>
            <div className="font-semibold text-lg">{user.name}</div>
            <div className="text-sm" style={{ color: "var(--text-dim)" }}>{user.email}</div>
          </div>
        </div>

        <button
          onClick={logout}
          className="flex items-center justify-center gap-2 w-full font-medium"
          style={{
            marginTop: 16, padding: "14px 0", color: "var(--danger)", background: "none",
            border: "none", cursor: "pointer", fontSize: 15, borderRadius: 12,
            transition: "all 0.15s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#fef2f2"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
        >
          <LogOut size={18} />
          로그아웃
        </button>
      </div>
    </AppShell>
  );
}
