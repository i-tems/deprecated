import { useCallback, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'
import {
  PanelLeftClose,
  PanelLeft,
  X,
  HelpCircle,
  Blocks,
  Search,
  Sun,
  Moon,
} from 'lucide-react'
import { SidebarNav } from '@/components/SidebarNav'
import { WorkspaceMenu } from '@/components/WorkspaceMenu'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
  mobileOpen: boolean
  onMobileClose: () => void
  onOpenSearch: () => void
}

function useTheme() {
  const [dark, setDark] = useState(() =>
    typeof document !== 'undefined' && document.documentElement.classList.contains('dark'),
  )
  const toggle = useCallback(() => {
    setDark((prev) => {
      const next = !prev
      document.documentElement.classList.toggle('dark', next)
      try { localStorage.setItem('theme', next ? 'dark' : 'light') } catch { /* SSR/Quota — 무시 */ }
      return next
    })
  }, [])
  return { dark, toggle }
}

// Linear workspace=user / team=cell 매핑. 상단 = workspace identity 드롭다운 (Settings/
// Log out). 본문은 user-level 영역 + cell 별 그룹. 좌하단 footer = 보조 아이콘 (Guide/
// Capabilities/테마 토글).
export function Sidebar({ collapsed, onToggle, mobileOpen, onMobileClose, onOpenSearch }: SidebarProps) {
  const { user, logout } = useAuth()
  const theme = useTheme()

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/60 animate-in fade-in duration-150"
          onClick={onMobileClose}
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 flex flex-col border-r border-border-subtle bg-bg-elevated transition-[width] duration-200',
          'max-md:z-50',
          'md:z-30',
          collapsed ? 'md:w-14' : 'md:w-[244px]',
          mobileOpen
            ? 'max-md:w-64 max-md:translate-x-0'
            : 'max-md:w-64 max-md:-translate-x-full',
        )}
      >
        {/* Header — workspace dropdown + toggles */}
        <div
          className={cn(
            'relative flex items-center border-b border-border-subtle',
            collapsed
              ? 'md:flex-col md:h-auto md:gap-1 md:py-2 md:px-1 max-md:h-12 max-md:justify-between max-md:px-3'
              : 'h-12 justify-between px-2',
          )}
        >
          <WorkspaceMenu
            collapsed={collapsed}
            user={user}
            onLogout={logout}
            onMobileClose={onMobileClose}
          />

          {/* 우측 아이콘 그룹 — collapsed(md) 에선 부모 flex-col 따라 세로 정렬, 그 외 가로. */}
          <div
            className={cn(
              'flex items-center gap-0.5',
              collapsed && 'md:flex-col md:gap-1',
            )}
          >
            {/* Global search */}
            <button
              onClick={() => { onMobileClose(); onOpenSearch() }}
              className="rounded-md p-1.5 text-text-tertiary hover:bg-bg-hover hover:text-text transition-colors"
              aria-label="Search (⌘K)"
              title="Search (⌘K)"
            >
              <Search size={16} />
            </button>

            {/* Desktop toggle */}
            <button
              onClick={onToggle}
              className="hidden md:block rounded-md p-1.5 text-text-tertiary hover:bg-bg-hover hover:text-text transition-colors"
              aria-label="Toggle sidebar"
            >
              {collapsed ? <PanelLeft size={16} /> : <PanelLeftClose size={16} />}
            </button>

            {/* Mobile close */}
            <button
              onClick={onMobileClose}
              className="md:hidden rounded-md p-1.5 text-text-tertiary hover:bg-bg-hover hover:text-text transition-colors"
              aria-label="메뉴 닫기"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <SidebarNav collapsed={collapsed} onMobileClose={onMobileClose} />

        {/* Footer — icon-only 보조 항목 (Linear 의 좌하 "?" / 보조 아이콘 패턴). */}
        <div
          className={cn(
            'flex items-center gap-1 px-2 py-2',
            collapsed && 'md:flex-col md:justify-center md:gap-0.5 md:px-1',
          )}
        >
          <NavLink
            to="/help"
            onClick={onMobileClose}
            title="Guide"
            aria-label="Guide"
            className={({ isActive }) =>
              cn(
                'rounded-md p-1.5 transition-colors',
                isActive
                  ? 'bg-bg-hover text-text'
                  : 'text-text-tertiary hover:bg-bg-hover hover:text-text',
              )
            }
          >
            <HelpCircle size={16} />
          </NavLink>
          <NavLink
            to="/capabilities"
            onClick={onMobileClose}
            title="Capabilities"
            aria-label="Capabilities"
            className={({ isActive }) =>
              cn(
                'rounded-md p-1.5 transition-colors',
                isActive
                  ? 'bg-bg-hover text-text'
                  : 'text-text-tertiary hover:bg-bg-hover hover:text-text',
              )
            }
          >
            <Blocks size={16} />
          </NavLink>
          <button
            type="button"
            onClick={theme.toggle}
            title={theme.dark ? 'Light theme' : 'Dark theme'}
            aria-label={theme.dark ? 'Light theme' : 'Dark theme'}
            className="rounded-md p-1.5 text-text-tertiary hover:bg-bg-hover hover:text-text transition-colors"
          >
            {theme.dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </aside>
    </>
  )
}
