import { useState, useEffect, useCallback } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { FocusNav } from './FocusNav'
import { SearchOverlay } from './SearchOverlay'
import { ShortcutsHelp } from './ShortcutsHelp'
import { RemoteSshDrawer } from './RemoteSshDrawer'
import { PanelLeft } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useCell } from '@/contexts/CellContext'

export function Layout() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('sidebar-collapsed') === 'true' } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const location = useLocation()
  const { currentCell } = useCell()

  // 페이지 이동 시 모바일 사이드바·검색 모두 닫기
  useEffect(() => {
    setMobileOpen(false)
    setSearchOpen(false)
  }, [location.pathname, location.search])

  const toggle = useCallback(() => setCollapsed((c) => {
    const next = !c
    try { localStorage.setItem('sidebar-collapsed', String(next)) } catch {}
    return next
  }), [])

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        toggle()
      } else if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen((v) => !v)
      } else if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        // 텍스트 입력 중에는 양보 — '?' 를 그대로 입력해야 한다.
        const t = e.target as HTMLElement | null
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
        e.preventDefault()
        setHelpOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [toggle])

  // ⌘K 커맨드 팔레트의 글로벌 액션(사이드바 토글·단축키 도움말)이 dispatch 하는 이벤트.
  // 키보드 단축키(⌘B·?)와 같은 핸들러를 공유한다.
  useEffect(() => {
    function onToggleSidebar() { toggle() }
    function onOpenShortcuts() { setHelpOpen((v) => !v) }
    window.addEventListener('hive:toggle-sidebar', onToggleSidebar)
    window.addEventListener('hive:open-shortcuts', onOpenShortcuts)
    return () => {
      window.removeEventListener('hive:toggle-sidebar', onToggleSidebar)
      window.removeEventListener('hive:open-shortcuts', onOpenShortcuts)
    }
  }, [toggle])

  return (
    <div
      className="min-h-screen bg-bg"
      style={{
        '--sidebar-w': collapsed ? '56px' : '244px',
      } as React.CSSProperties}
    >
      {/* Mobile top bar */}
      <header className="md:hidden fixed top-0 inset-x-0 z-40 flex h-12 items-center gap-3 border-b border-border bg-bg px-4">
        <button
          onClick={() => setMobileOpen(true)}
          className="rounded-md p-2 -ml-2 text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
          aria-label="메뉴 열기"
        >
          <PanelLeft size={20} />
        </button>
        <span className="text-sm font-semibold tracking-tight">Hive</span>
      </header>

      <Sidebar
        collapsed={collapsed}
        onToggle={toggle}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
        onOpenSearch={() => setSearchOpen(true)}
      />

      {/* 리스트에서 한 건씩 처리(focus) 중일 때만 상단 우측에 pos/이전/다음/종료를 띄운다. */}
      <FocusNav />

      <main
        className={cn(
          'min-h-screen transition-[margin-left] duration-200',
          'pt-12 md:pt-0',
          collapsed ? 'md:ml-14' : 'md:ml-[244px]',
        )}
      >
        {/* cell 변경 시 페이지 트리를 remount — usePolling 의 stale data/pagination 등 local state 를 즉시 초기화 */}
        <div key={currentCell?.cell_id ?? '__no_cell__'} className="mx-auto max-w-6xl px-4 py-4 md:px-6 md:py-6 overflow-x-clip">
          <Outlet />
        </div>
      </main>
      <RemoteSshDrawer />
      <SearchOverlay open={searchOpen} onClose={() => setSearchOpen(false)} />
      <ShortcutsHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  )
}
