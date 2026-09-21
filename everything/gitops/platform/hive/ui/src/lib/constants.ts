import type { FilterTab } from '@/components/FilterTabs'
import type { EntityStatus, ContainerStatus } from '@/lib/types'

export const STATUS_FILTERS: EntityStatus[] = ['backlog', 'todo', 'running', 'waiting', 'cleanup', 'done', 'cancelled', 'error']
/** Active = 사용자 액션이나 처리가 필요한 진행 상태 (backlog 와 종료 상태 제외) */
export const ACTIVE_STATUSES: Set<EntityStatus> = new Set(['todo', 'running', 'waiting', 'cleanup', 'error'])

/** Container(Project·Initiative) active = in-progress 상태. backlog·terminal(done/archive) 제외.
 *  waiting(사람 답변 대기, non-terminal)도 포함 — 사람 액션이 필요한 상태라 Active 탭에서 빠지면 안 됨. */
export const CONTAINER_ACTIVE_STATUSES: Set<ContainerStatus> = new Set(['active', 'waiting'])

/** Issues/Projects 공통 status 필터 탭. */
export type StatusFilterValue = 'all' | 'active'
export const STATUS_FILTER_TABS: FilterTab<StatusFilterValue>[] = [
  { value: 'active', label: 'Active' },
  { value: 'all', label: 'All' },
]

