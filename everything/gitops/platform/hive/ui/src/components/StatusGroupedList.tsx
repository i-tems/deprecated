import { useState, useCallback } from 'react'
import { ChevronRight, Plus } from 'lucide-react'
import { StatusIcon } from '@/components/StatusIcon'
import { STATUS_LABEL, CONTAINER_STATUS_LABEL, CONTAINER_STATUSES } from '@/lib/status'
import { STATUS_FILTERS } from '@/lib/constants'
import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'
import type { AnyStatus, ContainerStatus, EntityStatus, StatusKind } from '@/lib/types'

interface StatusGroupedListProps<T> {
  items: T[]
  getStatus: (item: T) => AnyStatus
  renderItem: (item: T) => ReactNode
  itemKey: (item: T) => string
  /** localStorage key prefix for collapse state ("{prefix}:{status}") */
  storageKey: string
  /** 처음 접혀있을 status들. 기본 kind 별 terminal 상태. */
  initiallyCollapsed?: AnyStatus[]
  /** 그룹 헤더 우측 + 버튼 클릭 시 호출. status 미리 채워진 create flow를 열기 위함. */
  onCreate?: (status: AnyStatus) => void
  /** 'issue'(8상태, 기본) | 'container'(Project·Initiative 4상태) */
  kind?: StatusKind
}

function statusLabel(status: AnyStatus, kind: StatusKind): string {
  return kind === 'container'
    ? CONTAINER_STATUS_LABEL[status as ContainerStatus]
    : STATUS_LABEL[status as EntityStatus]
}

const DEFAULT_ENTITY_COLLAPSED: EntityStatus[] = ['done', 'cancelled']
const DEFAULT_CONTAINER_COLLAPSED: ContainerStatus[] = ['done', 'archive']

function useCollapsed(storageKey: string, status: AnyStatus, defaultCollapsed: boolean) {
  const key = `${storageKey}:${status}`
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(key)
      return v === null ? defaultCollapsed : v === '1'
    } catch {
      return defaultCollapsed
    }
  })
  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      try { localStorage.setItem(key, next ? '1' : '0') } catch {}
      return next
    })
  }, [key])
  return [collapsed, toggle] as const
}

interface SectionProps<T> {
  status: AnyStatus
  items: T[]
  renderItem: (item: T) => ReactNode
  itemKey: (item: T) => string
  storageKey: string
  defaultCollapsed: boolean
  onCreate?: (status: AnyStatus) => void
  kind: StatusKind
}

function StatusSection<T>({ status, items, renderItem, itemKey, storageKey, defaultCollapsed, onCreate, kind }: SectionProps<T>) {
  const [collapsed, toggle] = useCollapsed(storageKey, status, defaultCollapsed)
  return (
    <div className="group/section">
      <div className="flex items-center gap-1.5 pl-1 pr-1 py-1 hover:bg-bg-hover/50 transition-colors">
        <button
          type="button"
          onClick={toggle}
          className="flex items-center gap-1.5 flex-1 min-w-0 text-left"
        >
          <ChevronRight
            size={11}
            className={cn(
              'text-text-quaternary transition-transform duration-150 shrink-0',
              !collapsed && 'rotate-90',
            )}
          />
          <StatusIcon status={status} size={12} kind={kind} />
          <span className="text-mini font-medium text-text-secondary">{statusLabel(status, kind)}</span>
          <span className="text-xs text-text-tertiary tabular-nums">{items.length}</span>
        </button>
        {onCreate && (
          <button
            type="button"
            onClick={() => onCreate(status)}
            className="opacity-0 group-hover/section:opacity-100 focus:opacity-100 inline-flex items-center justify-center w-5 h-5 rounded text-text-tertiary hover:text-text hover:bg-bg-hover transition-all"
            title={`Add ${statusLabel(status, kind)}`}
          >
            <Plus size={12} />
          </button>
        )}
      </div>
      {!collapsed && (
        <div>
          {items.map((item) => (
            <div key={itemKey(item)}>{renderItem(item)}</div>
          ))}
        </div>
      )}
    </div>
  )
}

/** 상태별 그룹핑 + 접기/펴기 헤더. localStorage에 펼침 상태 저장. */
export function StatusGroupedList<T>({
  items,
  getStatus,
  renderItem,
  itemKey,
  storageKey,
  initiallyCollapsed,
  onCreate,
  kind = 'issue',
}: StatusGroupedListProps<T>) {
  const collapsedSet = new Set(
    initiallyCollapsed ?? (kind === 'container' ? DEFAULT_CONTAINER_COLLAPSED : DEFAULT_ENTITY_COLLAPSED),
  )
  const order: AnyStatus[] = kind === 'container' ? CONTAINER_STATUSES : STATUS_FILTERS
  const groups = new Map<AnyStatus, T[]>()
  for (const item of items) {
    const s = getStatus(item)
    if (!groups.has(s)) groups.set(s, [])
    groups.get(s)!.push(item)
  }
  const visibleStatuses = order.filter((s) => groups.has(s))

  return (
    <div>
      {visibleStatuses.map((status) => (
        <StatusSection
          key={status}
          status={status}
          items={groups.get(status)!}
          renderItem={renderItem}
          itemKey={itemKey}
          storageKey={storageKey}
          defaultCollapsed={collapsedSet.has(status)}
          onCreate={onCreate}
          kind={kind}
        />
      ))}
    </div>
  )
}
