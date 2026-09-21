"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calendar, Users, User, RotateCcw, PanelLeftClose, PanelLeft, HelpCircle } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", icon: Calendar, label: "내 스케줄", key: "schedule" },
  { href: "/patterns", icon: RotateCcw, label: "패턴", key: "patterns" },
  { href: "/groups", icon: Users, label: "그룹", key: "groups" },
  { href: "/guide", icon: HelpCircle, label: "사용법", key: "guide" },
  { href: "/my", icon: User, label: "내 정보", key: "my" },
] as const;

function getActiveKey(pathname: string): string {
  if (pathname === "/") return "schedule";
  if (pathname.startsWith("/patterns")) return "patterns";
  if (pathname.startsWith("/groups") || pathname.startsWith("/join")) return "groups";
  if (pathname.startsWith("/guide")) return "guide";
  if (pathname.startsWith("/my")) return "my";
  return "schedule";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const active = getActiveKey(pathname);
  const [collapsed, setCollapsed] = useState(false);

  const sidebarWidth = collapsed ? 64 : 240;

  return (
    <div className="min-h-dvh">
      {/* Desktop Sidebar */}
      <aside
        className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:left-0 lg:z-40"
        style={{
          width: sidebarWidth,
          background: "var(--bg)",
          borderRight: "1px solid var(--border)",
          transition: "width 0.2s ease",
          overflow: "hidden",
        }}
      >
        <div
          className="flex items-center justify-between"
          style={{ padding: collapsed ? "20px 0" : "20px 20px 16px", justifyContent: collapsed ? "center" : "space-between" }}
        >
          {!collapsed && (
            <Link href="/" className="flex items-center gap-2.5">
              <span className="text-2xl leading-none">📅</span>
              <span className="text-base font-bold" style={{ color: "var(--text)", whiteSpace: "nowrap" }}>모임 스케줄러</span>
            </Link>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex items-center justify-center"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--text-sub)",
              padding: 4,
              borderRadius: 6,
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-dim)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "none"; }}
            title={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          >
            {collapsed ? <PanelLeft size={20} /> : <PanelLeftClose size={20} />}
          </button>
        </div>

        <nav className="flex-1" style={{ padding: collapsed ? "4px 8px" : "4px 12px" }}>
          {NAV_ITEMS.map((item) => {
            const isActive = active === item.key;
            return (
              <Link
                key={item.key}
                href={item.href}
                className="flex items-center font-medium"
                style={{
                  padding: collapsed ? "10px 0" : "10px 14px",
                  borderRadius: 10,
                  marginBottom: 2,
                  fontSize: 14,
                  gap: collapsed ? 0 : 12,
                  justifyContent: collapsed ? "center" : "flex-start",
                  color: isActive ? "var(--primary)" : "var(--text-sub)",
                  background: isActive ? "var(--primary-bg)" : "transparent",
                  transition: "all 0.15s",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.background = "var(--bg-sub)";
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.background = "transparent";
                }}
                title={collapsed ? item.label : undefined}
              >
                <item.icon size={18} strokeWidth={isActive ? 2.2 : 1.8} style={{ flexShrink: 0 }} />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Main content area */}
      <div
        className="flex-1"
        style={{ marginLeft: "var(--sidebar-ml, 0px)", transition: "margin-left 0.2s ease" }}
      >
        <style>{`@media (min-width: 1024px) { :root { --sidebar-ml: ${sidebarWidth}px; } }`}</style>
        <div className="min-h-dvh" style={{ paddingBottom: "var(--bottom-nav-h, 72px)", background: "var(--bg)" }}>
          {children}
        </div>
      </div>

      {/* Mobile bottom nav - only on small screens, no sidebar */}
      <nav className="bottom-nav lg:hidden">
        {NAV_ITEMS.map((item) => {
          const isActive = active === item.key;
          return (
            <Link key={item.key} href={item.href} className={isActive ? "active" : ""}>
              <item.icon size={22} strokeWidth={isActive ? 2.2 : 1.6}
                style={{ transition: "transform 0.2s", transform: isActive ? "scale(1.1)" : "scale(1)" }} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
