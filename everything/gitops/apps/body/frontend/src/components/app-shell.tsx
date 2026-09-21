"use client";

import { Suspense } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth-context";
import Sidebar from "@/components/sidebar";

function AppShellInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { user, loading } = useAuth();

  const isLoginPage = pathname === "/login";

  // If Google redirects back to root with ?code=, forward to /login
  useEffect(() => {
    const code = searchParams.get("code");
    if (code && pathname === "/") {
      router.replace(`/login?code=${encodeURIComponent(code)}`);
    }
  }, [pathname, searchParams, router]);

  useEffect(() => {
    if (!loading && !user && !isLoginPage) {
      const code = searchParams.get("code");
      if (!code) {
        router.push("/login");
      }
    }
  }, [user, loading, isLoginPage, router, searchParams]);

  if (isLoginPage) {
    return <>{children}</>;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-400 text-sm animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <>
      <Sidebar />
      <main className="md:ml-56 min-h-screen">
        <div className="px-5 py-6 md:px-8 md:py-8 max-w-5xl mx-auto">
          {children}
        </div>
      </main>
    </>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-screen">
          <div className="text-gray-400 text-sm animate-pulse">Loading...</div>
        </div>
      }
    >
      <AppShellInner>{children}</AppShellInner>
    </Suspense>
  );
}
