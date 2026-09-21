import { useCallback, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useCell } from '@/contexts/CellContext'
import { appendCellTo } from '@/hooks/useCellAwareTo'
import {
  Target,
  ListTodo,
  Compass,
  Radio,
  LayoutDashboard,
  ChevronDown,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { CellBadge } from '@/components/CellBadge'

interface NavItem {
  to: string
  icon: LucideIcon
  label: string
  iconClass?: string
}

// 사용자 레벨 (cell 무관). aggregate 응답으로 모든 cell 의 항목을 한 뷰에 보여준다.
// Linear 사이드바 컨벤션: 일반 nav 항목 아이콘은 무채색 (행 텍스트 색 상속). 컬러는
// cell badge (team identifier) 만.
const USER_LEVEL: NavItem[] = [
  { to: '/workspace', icon: LayoutDashboard, label: 'Workspace' },
]

// cell 그룹 안에 노출되는 항목들. 각 링크는 ?cell=<cellId> 를 부착해 그 cell scope 로 진입.
const CELL_ITEMS: NavItem[] = [
  { to: '/initiatives', icon: Compass, label: 'Initiatives' },
  { to: '/projects', icon: Target, label: 'Projects' },
  { to: '/issues', icon: ListTodo, label: 'Issues' },
  { to: '/signals', icon: Radio, label: 'Signals' },
]

interface SidebarNavProps {
  collapsed: boolean
  onMobileClose: () => void
}

// user-level 항목은 ?cell URL 부착이 의미가 없어 plain path 로만 라우팅.
function UserLevelItemRow({
  item,
  collapsed,
  onMobileClose,
}: {
  item: NavItem
  collapsed: boolean
  onMobileClose: () => void
}) {
  const { to, icon: Icon, label, iconClass } = item
  return (
    <NavLink
      to={to}
      onClick={onMobileClose}
      className={({ isActive }) =>
        cn(
          'group flex items-center gap-2 rounded-md text-sm transition-colors',
          'py-2 md:py-1.5 px-2.5',
          isActive
            ? 'bg-bg-hover text-text font-medium'
            : 'text-text-secondary hover:bg-bg-hover hover:text-text',
          collapsed && 'md:justify-center md:px-0',
        )
      }
    >
      <Icon size={16} className={cn('shrink-0', iconClass)} />
      <span className={cn(collapsed && 'md:hidden')}>{label}</span>
    </NavLink>
  )
}

// cell 그룹 항목 — to 에 ?cell=<cellId> 를 명시 부착. 현재 URL ?cell 에 의존하지 않는다.
function CellScopedNavItemRow({
  item,
  cellId,
  collapsed,
  onMobileClose,
}: {
  item: NavItem
  cellId: string
  collapsed: boolean
  onMobileClose: () => void
}) {
  const { to, icon: Icon, label, iconClass } = item
  const target = appendCellTo(to, cellId) as string
  const location = useLocation()
  // NavLink 기본 매칭은 query 를 무시해 모든 cell 그룹의 동일 path 항목이 동시 active
  // 공명. cell-scoped 항목은 pathname 일치 + ?cell 값 일치를 모두 요구해야 한다.
  const currentCellInUrl = new URLSearchParams(location.search).get('cell')
  const isActive = location.pathname === to && currentCellInUrl === cellId
  return (
    <Link
      to={target}
      onClick={onMobileClose}
      className={cn(
        'group flex items-center gap-2 rounded-md text-sm transition-colors',
        'py-1.5 px-2.5 ml-6',
        isActive
          ? 'bg-bg-hover text-text font-medium'
          : 'text-text-secondary hover:bg-bg-hover hover:text-text',
        collapsed && 'md:justify-center md:px-0 md:ml-0',
      )}
    >
      <Icon size={14} className={cn('shrink-0', iconClass)} />
      <span className={cn(collapsed && 'md:hidden')}>{label}</span>
    </Link>
  )
}

// cell 그룹 펼침 상태 — cell 별 독립. localStorage 에 저장, 기본은 펼침.
const CELL_EXPAND_PREFIX = 'sidebar-cell:'
function useCellExpanded(cellId: string) {
  const key = `${CELL_EXPAND_PREFIX}${cellId}`
  const [expanded, setExpanded] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(key)
      return v === null ? true : v === '1'  // 기본 펼침
    } catch {
      return true
    }
  })
  const toggle = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev
      try { localStorage.setItem(key, next ? '1' : '0') } catch { /* SSR/QuotaExceeded — 무시 */ }
      return next
    })
  }, [key])
  return [expanded, toggle] as const
}

// cell 그룹 — cell 별 독립 펼침/접기 (localStorage 영구). 현재 cell 은 이름 강조.
// 헤더 전체 영역(chevron 포함) 클릭 = 토글. 자동 selectCell 없음 — 그 cell 로 진입은
// 펼친 그룹 내부 sub-item (Projects 등) 클릭으로 자연스럽게.
function CellGroup({
  cellId,
  cellName,
  isCurrent,
  collapsed,
  onMobileClose,
}: {
  cellId: string
  cellName: string
  isCurrent: boolean
  collapsed: boolean
  onMobileClose: () => void
}) {
  const [expanded, toggle] = useCellExpanded(cellId)
  if (collapsed) {
    // 축소 사이드바: cell 뱃지만 줄세움 — 헤더 영역이 좁아 펼침/접기 의미 없음. CellBadge 만.
    return (
      <div
        title={cellName}
        className={cn(
          'group w-full flex items-center justify-center rounded-md py-1.5',
          isCurrent && 'bg-bg-hover',
        )}
      >
        <CellBadge cellId={cellId} />
      </div>
    )
  }
  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        className={cn(
          'group w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors',
          'text-text-secondary hover:bg-bg-hover hover:text-text',
          isCurrent && 'text-text font-medium',
        )}
      >
        <ChevronDown
          size={11}
          className={cn(
            'shrink-0 text-text-tertiary transition-transform duration-150',
            !expanded && '-rotate-90',
          )}
        />
        <CellBadge cellId={cellId} />
        <span className="truncate flex-1 text-left">{cellName}</span>
      </button>
      {expanded && (
        <div className="space-y-0.5">
          {CELL_ITEMS.map((item) => (
            <CellScopedNavItemRow
              key={item.to}
              item={item}
              cellId={cellId}
              collapsed={collapsed}
              onMobileClose={onMobileClose}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// 섹션 펼침 상태 — `sidebar-section:<name>` localStorage, 기본 펼침.
// cell 그룹은 자체 키(`sidebar-cell:<cellId>`) 라 충돌 없음.
const SECTION_PREFIX = 'sidebar-section:'
function useSectionOpen(name: string) {
  const key = `${SECTION_PREFIX}${name}`
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(key)
      return v === null ? true : v === '1'
    } catch {
      return true
    }
  })
  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev
      try { localStorage.setItem(key, next ? '1' : '0') } catch { /* SSR/Quota — 무시 */ }
      return next
    })
  }, [key])
  return [open, toggle] as const
}

// Linear 컨벤션: 섹션 헤더는 항목보다 한 단계 작고(text-xs), 일반 케이스, muted 색.
// 항목은 text-sm 정규 — 두 단계 폰트 hierarchy 가 그룹과 본문 구분을 만든다.
function SectionHeader({ label, open, onToggle }: { label: string; open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="w-full flex items-center gap-1 px-2.5 pt-2 pb-1 text-xs font-medium text-text-tertiary hover:text-text-secondary transition-colors"
    >
      <span>{label}</span>
      <ChevronDown
        size={11}
        className={cn(
          'shrink-0 transition-transform duration-150',
          !open && '-rotate-90',
        )}
      />
    </button>
  )
}

export function SidebarNav({ collapsed, onMobileClose }: SidebarNavProps) {
  const { cells, currentCell } = useCell()
  const [cellsOpen, toggleCells] = useSectionOpen('cells')

  return (
    <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-3">
      {/* User-level — Workspace(Inbox·Deck·기대감 흐름). cell 무관 aggregate. */}
      <div className="space-y-0.5">
        {USER_LEVEL.map((item) => (
          <UserLevelItemRow
            key={item.to}
            item={item}
            collapsed={collapsed}
            onMobileClose={onMobileClose}
          />
        ))}
      </div>

      {/* Cells 섹션 — 헤더 클릭으로 전체 섹션 접기. cell 별 독립 펼침은 그 안에서 별도. */}
      {cells.length > 0 && (
        <div className="space-y-1">
          {!collapsed && <SectionHeader label="Cells" open={cellsOpen} onToggle={toggleCells} />}
          {(collapsed || cellsOpen) && (
            <div className="space-y-0.5">
              {cells.map((c) => (
                <CellGroup
                  key={c.cell_id}
                  cellId={c.cell_id}
                  cellName={c.name}
                  isCurrent={c.cell_id === currentCell?.cell_id}
                  collapsed={collapsed}
                  onMobileClose={onMobileClose}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </nav>
  )
}
