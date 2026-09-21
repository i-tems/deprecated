"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  LayoutDashboard,
  ClipboardEdit,
  Dumbbell,
  Sparkles,
  Clock,
  Settings,
  Menu,
  X,
  LogOut,
  Footprints,
} from "lucide-react";

const navItems = [
  { href: "/", label: "대시보드", icon: LayoutDashboard },
  { href: "/evaluate", label: "평가 입력", icon: ClipboardEdit },
  { href: "/running", label: "달리기", icon: Footprints },
  { href: "/body-parts", label: "부위 목록", icon: Dumbbell },
  { href: "/skills", label: "기초 스킬", icon: Sparkles },
  { href: "/history", label: "성장 기록", icon: Clock },
  { href: "/settings", label: "설정", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  const nav = (
    <aside className="flex flex-col h-full w-56 bg-white border-r border-border">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-border">
        <div className="w-8 h-8 rounded-xl bg-brand flex items-center justify-center">
          <Dumbbell className="w-4 h-4 text-white" />
        </div>
        <span className="text-[15px] font-bold text-text-primary">
          Body Tracker
        </span>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-[13px] font-medium transition-colors ${
                active
                  ? "bg-brand-light text-brand-dark"
                  : "text-text-secondary hover:bg-surface-tertiary hover:text-text-primary"
              }`}
            >
              <Icon className="w-[18px] h-[18px]" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-3 py-3 border-t border-border">
        {user && (
          <div className="flex items-center gap-2.5 px-2 mb-2">
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt=""
                className="w-7 h-7 rounded-full"
              />
            ) : (
              <div className="w-7 h-7 rounded-full bg-surface-tertiary" />
            )}
            <span className="text-[12px] text-text-secondary font-medium truncate flex-1">
              {user.name}
            </span>
          </div>
        )}
        <button
          onClick={() => {
            logout();
            setOpen(false);
          }}
          className="flex items-center gap-2.5 w-full px-3 py-2 rounded-xl text-[12px] font-medium text-text-tertiary hover:bg-surface-tertiary hover:text-danger transition-colors"
        >
          <LogOut className="w-4 h-4" />
          로그아웃
        </button>
      </div>
    </aside>
  );

  return (
    <>
      {/* Desktop */}
      <div className="hidden md:block fixed inset-y-0 left-0 z-30">{nav}</div>

      {/* Mobile toggle */}
      <button
        onClick={() => setOpen(true)}
        className="fixed top-4 left-4 z-50 md:hidden w-10 h-10 flex items-center justify-center rounded-xl bg-white border border-border shadow-sm"
      >
        <Menu className="w-5 h-5 text-text-primary" />
      </button>

      {/* Mobile drawer */}
      {open && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/30"
            onClick={() => setOpen(false)}
          />
          <div className="fixed inset-y-0 left-0 z-50">
            <div className="relative h-full">
              {nav}
              <button
                onClick={() => setOpen(false)}
                className="absolute top-4 right-[-44px] w-9 h-9 flex items-center justify-center rounded-full bg-white shadow-md"
              >
                <X className="w-4 h-4 text-text-secondary" />
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
