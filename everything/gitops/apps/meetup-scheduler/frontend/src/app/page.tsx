"use client";

import { useAuth } from "@/lib/auth-context";
import { LoginPage } from "@/components/login-page";
import { AppShell } from "@/components/app-shell";
import { ScheduleView } from "@/components/schedule-view";

export default function Home() {
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
      <ScheduleView />
    </AppShell>
  );
}
