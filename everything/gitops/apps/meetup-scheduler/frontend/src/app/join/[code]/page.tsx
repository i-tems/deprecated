"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { LoginPage } from "@/components/login-page";

export default function JoinPage() {
  const { code } = useParams<{ code: string }>();
  const router = useRouter();
  const { user, loading } = useAuth();
  const [error, setError] = useState("");

  const joinMutation = useMutation({
    mutationFn: () => api.post(`/api/groups/join/${code}`),
    onSuccess: (res) => {
      router.push(`/groups/${res.data.id}`);
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || "가입에 실패했어요";
      setError(msg);
    },
  });

  useEffect(() => {
    if (user && !joinMutation.isPending && !joinMutation.isSuccess && !error) {
      joinMutation.mutate();
    }
  }, [user]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-dvh">
        <div className="w-8 h-8 border-3 rounded-full animate-spin"
          style={{ borderColor: "var(--primary)", borderTopColor: "transparent" }} />
      </div>
    );
  }

  if (!user) return <LoginPage />;

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-dvh px-6">
        <p className="text-lg font-medium mb-2">가입 실패</p>
        <p className="text-sm mb-6" style={{ color: "var(--text-sub)" }}>{error}</p>
        <button onClick={() => router.push("/groups")} className="btn-primary" style={{ maxWidth: 320 }}>
          그룹 목록으로
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-dvh">
      <div className="w-8 h-8 border-3 rounded-full animate-spin mb-4"
        style={{ borderColor: "var(--primary)", borderTopColor: "transparent" }} />
      <p style={{ color: "var(--text-sub)" }}>그룹에 가입하는 중...</p>
    </div>
  );
}
