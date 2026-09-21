import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { ChevronDown, Settings as SettingsIcon, LogOut } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WorkspaceMenuUser {
  name?: string
  email?: string
  picture?: string
}

interface WorkspaceMenuProps {
  collapsed: boolean
  user: WorkspaceMenuUser | null
  onLogout: () => void
  onMobileClose: () => void
}

// 사이드바 상단 workspace identity 드롭다운 — Linear 의 workspace picker 와 동형.
// 트리거: avatar + 사용자 이름 + ▼. 팝아웃: Settings/Log out. (테마 토글은 좌하단 푸터 아이콘.)
// collapsed 사이드바에선 트리거가 avatar 한 칸만 차지.
export function WorkspaceMenu({ collapsed, user, onLogout, onMobileClose }: WorkspaceMenuProps) {
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)

  const initial = (user?.name?.[0] || user?.email?.[0] || '?').toUpperCase()
  // 우선순위: name → email local-part → 'Hive' (미인증 fallback, 보통 도달 안 함)
  const label = user?.name || user?.email?.split('@')[0] || 'Hive'

  const Avatar = (
    user?.picture ? (
      <img
        src={user.picture}
        alt=""
        className="h-6 w-6 rounded-full shrink-0"
        referrerPolicy="no-referrer"
      />
    ) : (
      <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-accent-muted text-2xs font-medium text-accent-text shrink-0">
        {initial}
      </span>
    )
  )

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(
          'flex items-center rounded-md hover:bg-bg-hover transition-colors',
          collapsed ? 'p-1' : 'gap-1.5 px-1.5 py-1 min-w-0',
        )}
        title={user?.email || 'Workspace'}
      >
        {Avatar}
        {!collapsed && (
          <>
            <span className="truncate text-sm font-medium text-text">{label}</span>
            <ChevronDown size={12} className="shrink-0 text-text-tertiary" />
          </>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-50" onClick={close} />
          <div
            className={cn(
              'absolute z-50 w-60 rounded-lg border border-border bg-card shadow-popover overflow-hidden',
              collapsed ? 'left-full top-0 ml-1' : 'top-full left-0 mt-1.5',
            )}
          >
            {user && (
              <div className="px-3 py-2 border-b border-border-subtle">
                <div className="text-sm font-medium text-text truncate">{label}</div>
                {user.email && (
                  <div className="text-xs text-text-tertiary truncate">{user.email}</div>
                )}
              </div>
            )}

            <NavLink
              to="/settings"
              onClick={() => { close(); onMobileClose() }}
              className="flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
            >
              <SettingsIcon size={14} className="shrink-0 text-text-tertiary" />
              <span>Settings</span>
            </NavLink>

            <div className="border-t border-border-subtle">
              <button
                type="button"
                onClick={() => { close(); onLogout() }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:bg-bg-hover hover:text-danger transition-colors"
              >
                <LogOut size={14} className="shrink-0 text-text-tertiary" />
                <span>Log out</span>
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
