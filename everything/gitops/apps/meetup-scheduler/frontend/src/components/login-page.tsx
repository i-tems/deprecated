"use client";

import { useAuth } from "@/lib/auth-context";
import api from "@/lib/api";
import { useCallback, useEffect, useRef, useState } from "react";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

function getInAppType(): "kakao" | "other" | null {
  if (typeof navigator === "undefined") return null;
  const ua = navigator.userAgent || "";
  if (/KAKAOTALK/i.test(ua)) return "kakao";
  if (/NAVER|Line\/|Instagram|FBAN|FBAV|FB_IAB|Twitter|Snapchat/i.test(ua)) return "other";
  return null;
}

export function LoginPage() {
  const { login } = useAuth();
  const callbackProcessed = useRef(false);
  const [inAppType, setInAppType] = useState<"kakao" | "other" | null>(null);

  useEffect(() => {
    const type = getInAppType();
    setInAppType(type);
    // KakaoTalk: auto-redirect to external browser immediately
    if (type === "kakao") {
      window.location.href = "kakaotalk://web/openExternal?url=" + encodeURIComponent(window.location.href);
    }
  }, []);

  const handleGoogleCallback = useCallback(async () => {
    if (callbackProcessed.current) return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (!code) return;
    callbackProcessed.current = true;
    try {
      const res = await api.post("/api/auth/google", {
        code,
        redirect_uri: window.location.origin,
      });
      await login(res.data.token);
      const redirect = localStorage.getItem("redirect_after_login");
      localStorage.removeItem("redirect_after_login");
      if (redirect) {
        window.location.replace(redirect);
      } else {
        window.history.replaceState({}, "", "/");
      }
    } catch (err) {
      console.error("Login failed:", err);
      callbackProcessed.current = false;
    }
  }, [login]);

  useEffect(() => {
    handleGoogleCallback();
  }, [handleGoogleCallback]);

  const handleLogin = () => {
    // Save current path so we can return after login
    const currentPath = window.location.pathname;
    if (currentPath !== "/" && currentPath !== "") {
      localStorage.setItem("redirect_after_login", currentPath);
    }
    const redirectUri = window.location.origin;
    const scope = "openid email profile";
    const url =
      `https://accounts.google.com/o/oauth2/v2/auth?` +
      `client_id=${GOOGLE_CLIENT_ID}` +
      `&redirect_uri=${encodeURIComponent(redirectUri)}` +
      `&response_type=code` +
      `&scope=${encodeURIComponent(scope)}` +
      `&access_type=offline` +
      `&prompt=consent`;
    window.location.href = url;
  };

  const handleOpenExternal = () => {
    const currentUrl = window.location.href;
    if (inAppType === "kakao") {
      // KakaoTalk specific: open external browser via scheme
      window.location.href = "kakaotalk://web/openExternal?url=" + encodeURIComponent(currentUrl);
      return;
    }
    // Android intent for Chrome
    const intentUrl = `intent://${currentUrl.replace(/^https?:\/\//, "")}#Intent;scheme=https;package=com.android.chrome;end`;
    window.location.href = intentUrl;
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-dvh" style={{ padding: "0 24px" }}>
      <div className="login-enter" style={{ maxWidth: 360, width: "100%", textAlign: "center" }}>
        <div style={{ fontSize: 48, marginBottom: 8 }}>📅</div>
        <h1 className="text-2xl font-bold" style={{ marginBottom: 8 }}>모임 스케줄러</h1>
        <p style={{ color: "var(--text-sub)", marginBottom: 40, fontSize: 15, lineHeight: 1.6 }}>
          교대근무, 일반근무, 프리랜서<br />
          다 달라도 약속은 잡을 수 있어요
        </p>

        {inAppType ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="card" style={{
              padding: "16px 20px", textAlign: "left", fontSize: 14,
              background: "#fff8e1", border: "1px solid #ffe082", lineHeight: 1.6,
            }}>
              <strong style={{ color: "#e65100" }}>인앱 브라우저에서는 Google 로그인이 제한됩니다.</strong>
              <br />
              <span style={{ color: "var(--text-sub)" }}>
                {inAppType === "kakao"
                  ? "외부 브라우저로 자동 이동 중입니다..."
                  : "우측 상단 ⋮ 메뉴에서 '외부 브라우저로 열기'를 선택해주세요."}
              </span>
            </div>
            <button onClick={handleOpenExternal} className="btn-primary">
              외부 브라우저로 열기
            </button>
            <p style={{ fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5 }}>
              자동으로 열리지 않으면 URL을 복사해서<br />Chrome이나 Safari에 직접 붙여넣어 주세요.
            </p>
            <button
              onClick={() => {
                navigator.clipboard.writeText(window.location.href);
                alert("URL이 복사되었습니다. 브라우저에 붙여넣기 해주세요.");
              }}
              className="btn-sub" style={{ fontSize: 13 }}
            >
              URL 복사하기
            </button>
          </div>
        ) : (
          <button onClick={handleLogin} className="btn-primary">
            <svg width="20" height="20" viewBox="0 0 48 48">
              <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
              <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
              <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
              <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
            </svg>
            Google로 시작하기
          </button>
        )}
      </div>
    </div>
  );
}
