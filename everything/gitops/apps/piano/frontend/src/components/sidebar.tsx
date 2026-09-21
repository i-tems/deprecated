"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useSidebar } from "@/lib/sidebar-context";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navItems = [
  {
    href: "/my",
    label: "전체 현황",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
  },
  {
    href: "/my/songs",
    label: "내 곡 목록",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 9l10.5-3m0 6.553v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 11-.99-3.467l2.31-.66a2.25 2.25 0 001.632-2.163zm0 0V2.25L9 5.25v10.303m0 0v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 01-.99-3.467l2.31-.66A2.25 2.25 0 009 15.553z" />
      </svg>
    ),
  },
  {
    href: "/my/skills",
    label: "내 스킬",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
      </svg>
    ),
  },
  {
    href: "/my/sight-reading",
    label: "악보 리딩 훈련",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 18V5l12-2v13" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 18a3 3 0 11-6 0 3 3 0 016 0zM21 16a3 3 0 11-6 0 3 3 0 016 0z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 8h10" />
      </svg>
    ),
  },
  {
    href: "/songs",
    label: "곡 카탈로그",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
      </svg>
    ),
  },
];

function LogoMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "rounded-md bg-toss-gray-100 border border-toss-gray-200 flex items-center justify-center",
        className
      )}
    >
      <svg viewBox="0 0 24 24" fill="none" className="w-[58%] h-[58%] text-toss-gray-900" stroke="currentColor" strokeWidth={1.75}>
        <rect x="2" y="4" width="20" height="16" rx="2" />
        <rect x="5" y="4" width="2" height="8" fill="currentColor" rx="0.5" />
        <rect x="11" y="4" width="2" height="8" fill="currentColor" rx="0.5" />
        <rect x="17" y="4" width="2" height="8" fill="currentColor" rx="0.5" />
      </svg>
    </div>
  );
}

export function MobileHeader() {
  const { toggle } = useSidebar();

  return (
    <header className="md:hidden sticky top-0 z-40 flex items-center gap-3 px-4 py-3 bg-card border-b border-border">
      <button
        onClick={toggle}
        className="p-1.5 -ml-1.5 rounded-md text-toss-gray-500 hover:text-toss-gray-900 hover:bg-toss-gray-100 transition-colors"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
        </svg>
      </button>
      <Link href="/my" className="flex items-center gap-2">
        <LogoMark className="w-6 h-6" />
        <span className="text-[15px] font-semibold text-toss-gray-900 tracking-tight">
          피아노
        </span>
      </Link>
    </header>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { isOpen, close } = useSidebar();

  return (
    <>
      {/* 모바일 오버레이 */}
      {isOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity"
          onClick={close}
        />
      )}

      {/* 사이드바 */}
      <aside
        className={cn(
          "fixed md:sticky top-0 left-0 z-50 w-60 bg-sidebar text-sidebar-foreground flex flex-col h-screen border-r border-sidebar-border transition-transform duration-200 ease-in-out",
          isOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        {/* Logo */}
        <div className="h-14 px-4 flex items-center justify-between shrink-0">
          <Link href="/my" className="flex items-center gap-2.5">
            <LogoMark className="w-6 h-6" />
            <span className="text-[15px] font-semibold text-toss-gray-900 tracking-tight">
              피아노
            </span>
          </Link>
          {/* 모바일 닫기 버튼 */}
          <button
            onClick={close}
            className="md:hidden p-1.5 -mr-1.5 rounded-md text-toss-gray-500 hover:text-toss-gray-900 hover:bg-toss-gray-100 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2.5 py-1.5 overflow-y-auto space-y-px">
          {navItems.map((item) => {
            const isActive =
              item.href === "/my"
                ? pathname === "/my"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={close}
                className={cn(
                  "relative flex items-center gap-2.5 h-9 px-2.5 rounded-md text-[13px] font-medium transition-colors",
                  isActive
                    ? "bg-toss-gray-100 text-toss-gray-900 before:absolute before:content-[''] before:left-0 before:top-2 before:bottom-2 before:w-[2px] before:rounded-full before:bg-toss-blue"
                    : "text-toss-gray-500 hover:bg-toss-gray-100 hover:text-toss-gray-900"
                )}
              >
                <span className="shrink-0">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* User */}
        {user && (
          <div className="px-2.5 py-2.5 border-t border-sidebar-border shrink-0">
            <div className="flex items-center gap-2.5 px-1.5">
              <Avatar className="w-7 h-7 shrink-0">
                <AvatarImage src={user.avatar_url || undefined} />
                <AvatarFallback className="bg-toss-blue-light text-toss-blue text-[11px] font-semibold">
                  {user.name?.[0]?.toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 min-w-0 overflow-hidden">
                <div className="text-[13px] font-medium text-toss-gray-900 truncate">
                  {user.name}
                </div>
                <div className="text-[11px] text-toss-gray-500 truncate">
                  {user.email}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={logout}
                className="text-toss-gray-500 hover:text-toss-gray-900 hover:bg-toss-gray-100 shrink-0 w-7 h-7"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
                </svg>
              </Button>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
