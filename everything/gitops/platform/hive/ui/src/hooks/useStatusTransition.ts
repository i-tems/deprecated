import { useCallback } from 'react'
import type { AnyStatus, ContainerStatus, EntityStatus, StatusKind } from '@/lib/types'
import { HUMAN_TRANSITIONS, needsCleanupDetour, CONTAINER_HUMAN_TRANSITIONS } from '@/lib/status'

interface UseStatusTransitionOptions {
  getCurrentStatus: () => AnyStatus | undefined
  updateStatus: (status: AnyStatus, force: boolean, comment?: string) => Promise<void>
  applyOptimistic: (status: AnyStatus) => void
  refetch: () => void
  onError?: (message: string) => void
  /** 'issue'(8상태, 기본) | 'container'(Project·Initiative 4상태) */
  kind?: StatusKind
}

export function useStatusTransition({
  getCurrentStatus,
  updateStatus,
  applyOptimistic,
  refetch,
  onError,
  kind = 'issue',
}: UseStatusTransitionOptions): (status: AnyStatus) => Promise<void> {
  return useCallback(async (status: AnyStatus) => {
    const currentStatus = getCurrentStatus()
    if (!currentStatus) return

    const run = async (target: AnyStatus, force: boolean, comment?: string) => {
      applyOptimistic(target)
      try {
        await updateStatus(target, force, comment)
        refetch()
      } catch (e) {
        console.error('Transition failed:', e)
        onError?.(`상태 변경 실패: ${(e as Error).message}`)
        refetch()
      }
    }

    // Container(Project·Initiative)는 cleanup 단계가 없어 직접 전이. 비표준 전이는 force.
    if (kind === 'container') {
      const allowed = CONTAINER_HUMAN_TRANSITIONS[currentStatus as ContainerStatus] ?? []
      return run(status, !allowed.includes(status as ContainerStatus))
    }

    // Issue: cleanup 외 상태에서 done/cancelled 직접 선택 → cleanup 경유로 우회 (hub 가
    // 직접 전이를 거부, backlog/todo 의 취소 직행 포함). 워커가 transition comment 의
    // 진입 사유(완료/취소)를 읽고 teardown 후 done/cancelled 로 종결한다
    // (project_issue_model.md §2, issue_progress §C-1).
    const current = currentStatus as EntityStatus
    const target = status as EntityStatus
    if (needsCleanupDetour(current, target)) {
      const intent = target === 'cancelled' ? '취소' : '완료'
      return run('cleanup', false, `${intent} 진입 (UI)`)
    }

    const allowed = HUMAN_TRANSITIONS[current] ?? []
    return run(target, !allowed.includes(target))
  }, [getCurrentStatus, updateStatus, applyOptimistic, refetch, onError, kind])
}
