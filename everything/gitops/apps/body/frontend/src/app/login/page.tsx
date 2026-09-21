"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Dumbbell } from "lucide-react";
import axios from "axios";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function LoginPage() {
  const { user, loading, login } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) {
      router.push("/");
    }
  }, [user, loading, router]);

  // Handle Google OAuth callback (redirected here from root via AppShell, or directly)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (code) {
      window.history.replaceState({}, "", "/login");
      (async () => {
        try {
          const res = await axios.post(`${API_BASE}/api/auth/google`, {
            code,
            redirect_uri: window.location.origin + "/login",
          });
          await login(res.data.access_token);
          router.push("/");
        } catch (e) {
          console.error("Login failed", e);
        }
      })();
    }
  }, [login, router]);

  const handleGoogleLogin = () => {
    const params = new URLSearchParams({
      client_id: GOOGLE_CLIENT_ID,
      redirect_uri: window.location.origin + "/login",
      response_type: "code",
      scope: "openid email profile",
      access_type: "offline",
      prompt: "consent",
    });
    window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-text-tertiary text-sm animate-pulse">
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4">
      <div className="max-w-sm w-full text-center space-y-8">
        <div className="flex justify-center">
          <div className="w-20 h-20 rounded-3xl bg-brand flex items-center justify-center shadow-lg shadow-brand/20">
            <Dumbbell className="w-10 h-10 text-white" />
          </div>
        </div>

        <div className="space-y-2">
          <h1 className="text-[28px] font-bold tracking-tight text-text-primary leading-tight">
            Body Tracker
          </h1>
          <p className="text-[15px] text-text-secondary leading-relaxed">
            10부위 x 4속성으로 신체 능력을
            <br />
            체계적으로 추적하세요
          </p>
        </div>

        <div className="grid grid-cols-3 gap-2.5">
          {[
            { label: "레이더 차트", sub: "전신 한눈에" },
            { label: "성장 기록", sub: "시간별 추이" },
            { label: "약점 분석", sub: "개선 가이드" },
          ].map((f) => (
            <div
              key={f.label}
              className="p-3 rounded-2xl bg-surface-secondary border border-border"
            >
              <div className="text-[12px] font-semibold text-text-primary">
                {f.label}
              </div>
              <div className="text-[11px] text-text-tertiary mt-0.5">
                {f.sub}
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={handleGoogleLogin}
          className="w-full flex items-center justify-center gap-2.5 h-14 rounded-2xl bg-text-primary text-white text-[15px] font-semibold transition-all active:scale-[0.98] hover:opacity-90"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24">
            <path
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
              fill="#4285F4"
            />
            <path
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              fill="#34A853"
            />
            <path
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              fill="#FBBC05"
            />
            <path
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              fill="#EA4335"
            />
          </svg>
          Google로 시작하기
        </button>
      </div>
    </div>
  );
}
