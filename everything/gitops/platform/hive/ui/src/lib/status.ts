import type { ContainerStatus, EntityStatus, SignalStatus } from './types'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info' | 'accent' | 'ghost'

export const STATUS_BADGE: Record<EntityStatus, BadgeVariant> = {
  backlog: 'default',
  todo: 'default',
  running: 'default',
  waiting: 'default',
  cleanup: 'default',
  done: 'default',
  cancelled: 'default',
  error: 'error',
}

export const STATUS_LABEL: Record<EntityStatus, string> = {
  backlog: 'Backlog',
  todo: 'Todo',
  running: 'Running',
  waiting: 'Waiting',
  cleanup: 'Cleanup',
  done: 'Done',
  cancelled: 'Cancelled',
  error: 'Error',
}

export const SIGNAL_STATUS_BADGE: Record<SignalStatus, BadgeVariant> = {
  emitted: 'default',
  consumed: 'default',
  dismissed: 'default',
}

/** Signal status dot 색상 — list row 우측 작은 indicator */
export const SIGNAL_STATUS_COLOR: Record<SignalStatus, string> = {
  emitted:    'bg-warning',
  consumed:   'bg-success',
  dismissed:  'bg-text-quaternary',
}

export const SIGNAL_STATUS_LABEL: Record<SignalStatus, string> = {
  emitted: 'Active',
  consumed: 'Consumed',
  dismissed: 'Dismissed',
}

// Human-allowed transitions from backend TRANSITIONS map.
// done·cancelled 는 모두 반드시 cleanup 경유 — 어떤 상태에서도 직접 종결 불가,
// cleanup 에서만 done/cancelled 직행 (project_issue_model.md §2).
export const HUMAN_TRANSITIONS: Partial<Record<EntityStatus, EntityStatus[]>> = {
  backlog: ['todo'],
  todo: ['waiting', 'backlog'],
  waiting: ['running', 'cleanup', 'backlog'],
  running: ['cleanup'],
  cleanup: ['done', 'cancelled', 'running', 'waiting'],
  done: [],
  cancelled: [],
  error: ['todo', 'backlog', 'cleanup'],
}

// hub terminal_transition_denied 의 UI 미러 (project_issue_model.md §2).
// done·cancelled 모두 cleanup 외 상태에서 직접 전이는 hub 가 거부 → cleanup 경유.
export function needsCleanupDetour(current: EntityStatus, next: EntityStatus): boolean {
  if (next === 'done' || next === 'cancelled') return current !== 'cleanup'
  return false
}

// 워크플로우상 다음으로 가야 할 상태. waiting에서는 이전 상태에서 추론.
export function getRecommendedNext(
  current: EntityStatus,
  previous?: EntityStatus | null,
): EntityStatus[] {
  if (current === 'waiting') {
    if (previous === 'running') return ['cleanup']
    if (previous === 'cleanup') return ['cleanup']
    return ['running', 'cleanup']
  }
  if (current === 'cleanup') return ['done', 'cancelled']
  if (current === 'backlog') return ['todo']
  if (current === 'error') return ['todo']
  return []
}

export const TRANSITION_LABEL: Record<string, string> = {
  'todo': 'Todo',
  'running': 'Running',
  'waiting': 'Waiting',
  'cleanup': 'Cleanup',
  'done': 'Done',
  'cancelled': 'Cancelled',
}

// --- Container status (Project · Initiative 공통 5상태) ---
// backlog=준비/launch 전, active=진행, waiting=대기(사람 답변 blocked, non-terminal),
// done=완료(terminal), archive=보관(terminal).

export const CONTAINER_STATUSES: ContainerStatus[] = ['backlog', 'active', 'waiting', 'done', 'archive']

export const CONTAINER_STATUS_LABEL: Record<ContainerStatus, string> = {
  backlog: 'Backlog',
  active: 'Active',
  waiting: 'Waiting',
  done: 'Done',
  archive: 'Archive',
}

export const CONTAINER_STATUS_BADGE: Record<ContainerStatus, BadgeVariant> = {
  backlog: 'default',
  active: 'info',
  waiting: 'warning',
  done: 'success',
  archive: 'ghost',
}

// 사람 허용 전이. launch(backlog→active), park(active→waiting, 사람 답변 대기),
// 재개(waiting→active), 종결(active/waiting→done/archive),
// 정정·재개(done/archive→active, backlog↔archive) 양방향 허용.
export const CONTAINER_HUMAN_TRANSITIONS: Record<ContainerStatus, ContainerStatus[]> = {
  backlog: ['active', 'archive'],
  active: ['waiting', 'done', 'archive', 'backlog'],
  waiting: ['active', 'done', 'archive'],
  done: ['active', 'archive'],
  archive: ['active', 'backlog'],
}

export function containerRecommendedNext(current: ContainerStatus): ContainerStatus[] {
  if (current === 'backlog') return ['active']
  if (current === 'active') return ['done']
  if (current === 'waiting') return ['active']
  return []
}

// 전이 화살표 우측 한 줄 라벨 — container 용.
export const CONTAINER_TRANSITION_LABEL: Record<ContainerStatus, string> = {
  backlog: 'Backlog',
  active: 'Launch',
  waiting: 'Waiting',
  done: 'Done',
  archive: 'Archive',
}

