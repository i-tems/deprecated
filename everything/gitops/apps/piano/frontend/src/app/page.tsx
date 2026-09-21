"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import api from "@/lib/api";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

export default function LandingPage() {
  const { user, loading, login } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) {
      router.push("/my");
    }
  }, [user, loading, router]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (code) {
      window.history.replaceState({}, "", "/");
      (async () => {
        try {
          const res = await api.post("/api/auth/google", {
            code,
            redirect_uri: window.location.origin,
          });
          await login(res.data.access_token);
          router.push("/my");
        } catch (e) {
          console.error("Login failed", e);
        }
      })();
    }
  }, [login, router]);

  const handleGoogleLogin = () => {
    const params = new URLSearchParams({
      client_id: GOOGLE_CLIENT_ID,
      redirect_uri: window.location.origin,
      response_type: "code",
      scope: "openid email profile",
      access_type: "offline",
      prompt: "consent",
    });
    window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-card">
        <div className="animate-pulse text-toss-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen px-4 bg-card">
      <div className="max-w-lg w-full text-center space-y-10">
        {/* Piano icon */}
        <div className="flex justify-center">
          <div className="w-20 h-20 rounded-3xl bg-toss-blue flex items-center justify-center shadow-lg shadow-toss-blue/20">
            <svg viewBox="0 0 24 24" fill="none" className="w-10 h-10 text-white" stroke="currentColor" strokeWidth={1.5}>
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <rect x="5" y="4" width="2" height="8" fill="currentColor" rx="0.5" />
              <rect x="9" y="4" width="2" height="8" fill="currentColor" rx="0.5" />
              <rect x="13" y="4" width="2" height="8" fill="currentColor" rx="0.5" />
              <rect x="17" y="4" width="2" height="8" fill="currentColor" rx="0.5" />
            </svg>
          </div>
        </div>

        <div className="space-y-3">
          <h1 className="text-[32px] font-semibold tracking-tight text-toss-gray-900 leading-tight">
            피아노 연습,<br />한눈에 관리하세요
          </h1>
          <p className="text-base text-toss-gray-500 leading-relaxed">
            10가지 속성으로 연주를 평가하고<br />
            시각적으로 성장을 추적할 수 있어요
          </p>
        </div>

        {/* Features */}
        <div className="grid grid-cols-3 gap-3">
          <div className="p-4 rounded-xl bg-toss-gray-50">
            <div className="w-10 h-10 rounded-xl bg-toss-blue-light flex items-center justify-center mx-auto mb-3">
              <svg className="w-5 h-5 text-toss-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5" />
              </svg>
            </div>
            <div className="text-sm font-semibold text-toss-gray-900">레이더 차트</div>
            <div className="text-xs text-toss-gray-500 mt-0.5">한눈에 파악</div>
          </div>
          <div className="p-4 rounded-xl bg-toss-gray-50">
            <div className="w-10 h-10 rounded-xl bg-toss-blue-light flex items-center justify-center mx-auto mb-3">
              <svg className="w-5 h-5 text-toss-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
              </svg>
            </div>
            <div className="text-sm font-semibold text-toss-gray-900">성장 기록</div>
            <div className="text-xs text-toss-gray-500 mt-0.5">시간별 추이</div>
          </div>
          <div className="p-4 rounded-xl bg-toss-gray-50">
            <div className="w-10 h-10 rounded-xl bg-toss-blue-light flex items-center justify-center mx-auto mb-3">
              <svg className="w-5 h-5 text-toss-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
              </svg>
            </div>
            <div className="text-sm font-semibold text-toss-gray-900">곡 분석</div>
            <div className="text-xs text-toss-gray-500 mt-0.5">연습 팁 제공</div>
          </div>
        </div>

        <Button
          size="lg"
          onClick={handleGoogleLogin}
          className="w-full bg-toss-gray-900 text-white hover:bg-toss-gray-800 h-14 text-base font-semibold rounded-xl shadow-none transition-all active:scale-[0.98]"
        >
          <svg className="w-5 h-5 mr-2.5" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
          </svg>
          Google로 시작하기
        </Button>
      </div>
    </div>
  );
}
