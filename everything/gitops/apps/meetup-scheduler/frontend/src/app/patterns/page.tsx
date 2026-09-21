"use client";

import { useAuth } from "@/lib/auth-context";
import { LoginPage } from "@/components/login-page";
import { AppShell } from "@/components/app-shell";
import { PatternManager } from "@/components/pattern-manager";

export default function PatternsPage() {
  const { user, loading } = useAuth();

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
        <h1 className="text-lg font-bold">교대근무 패턴</h1>
      </div>
      <div className="page-enter" style={{ padding: 16 }}>
        <PatternManager />
      </div>
    </AppShell>
  );
}
