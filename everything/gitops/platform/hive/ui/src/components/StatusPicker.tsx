import { useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { StatusIcon } from '@/components/StatusIcon'
import { KbdHint } from '@/components/KbdHint'
import { Popover } from '@/components/Popover'
import {
  STATUS_LABEL, HUMAN_TRANSITIONS, getRecommendedNext,
  CONTAINER_STATUSES, CONTAINER_STATUS_LABEL, CONTAINER_HUMAN_TRANSITIONS, containerRecommendedNext,
} from '@/lib/status'
import type { AnyStatus, ContainerStatus, EntityStatus, StatusKind } from '@/lib/types'

const ALL_ENTITY_STATUSES: EntityStatus[] = [
  'backlog', 'todo', 'running', 'waiting', 'cleanup', 'done', 'cancelled', 'error',
]

interface StatusPickerProps {
  status: AnyStatus
  previousStatus?: AnyStatus | null
  /** 새 상태 선택 시 호출. force 적용 여부는 hook이 결정. */
  onChange: (status: AnyStatus) => void
  /** 'issue'(8상태, 기본) | 'container'(Project·Initiative 4상태) */
  kind?: StatusKind
}

export function StatusPicker({ status, previousStatus, onChange, kind = 'issue' }: StatusPickerProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const isContainer = kind === 'container'
  const allStatuses: AnyStatus[] = isContainer ? CONTAINER_STATUSES : ALL_ENTITY_STATUSES
  const label = (s: AnyStatus) =>
    isContainer ? CONTAINER_STATUS_LABEL[s as ContainerStatus] : STATUS_LABEL[s as EntityStatus]

  const allowed = new Set<AnyStatus>(
    isContainer
      ? CONTAINER_HUMAN_TRANSITIONS[status as ContainerStatus] ?? []
      : HUMAN_TRANSITIONS[status as EntityStatus] ?? [],
  )
  const recommended = new Set<AnyStatus>(
    isContainer
      ? containerRecommendedNext(status as ContainerStatus)
      : getRecommendedNext(status as EntityStatus, previousStatus as EntityStatus | null | undefined),
  )

  const select = (next: AnyStatus) => {
    if (next === status) {
      setOpen(false)
      return
    }
    onChange(next)
    setOpen(false)
  }

  return (
    <div>
      <button
        ref={triggerRef}
        data-kb="status"
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full hover:bg-bg-hover transition-colors text-sm"
        title="Change status (s)"
      >
        <StatusIcon status={status} size={14} kind={kind} />
        <span>{label(status)}</span>
        <ChevronDown size={10} className="text-text-tertiary" />
        <KbdHint k="s" />
      </button>

      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-64 rounded-md border border-border bg-bg shadow-lg overflow-hidden"
      >
        <div className="px-2 py-1.5 text-xs text-text-tertiary border-b border-border-subtle">
          Change status…
        </div>
        <ul className="max-h-[320px] overflow-y-auto py-1">
          {allStatuses.map((s) => {
            const isCurrent = s === status
            const isAllowed = allowed.has(s)
            const isRecommended = recommended.has(s)
            const dim = !isCurrent && !isAllowed && !isRecommended
            return (
              <li key={s}>
                <button
                  type="button"
                  onClick={() => select(s)}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors ${
                    dim ? 'opacity-40' : ''
                  }`}
                  title={dim ? '비표준 전이 — force로 적용됩니다' : undefined}
                >
                  <StatusIcon status={s} size={14} kind={kind} />
                  <span className="flex-1">{label(s)}</span>
                  {isCurrent && <span className="text-text-tertiary">✓</span>}
                  {!isCurrent && isRecommended && (
                    <span className="text-2xs text-accent">recommended</span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      </Popover>
    </div>
  )
}
