import { useRef, useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { StatusIcon } from '@/components/StatusIcon'
import { Popover } from '@/components/Popover'
import {
  STATUS_LABEL, HUMAN_TRANSITIONS, TRANSITION_LABEL, getRecommendedNext,
  CONTAINER_STATUS_LABEL, CONTAINER_HUMAN_TRANSITIONS, CONTAINER_TRANSITION_LABEL, containerRecommendedNext,
} from '@/lib/status'
import type { AnyStatus, ContainerStatus, EntityStatus, StatusKind } from '@/lib/types'

interface StatusSelectProps {
  status: AnyStatus
  previousStatus?: AnyStatus | null
  disallowedStatuses?: AnyStatus[]
  onTransition: (next: AnyStatus) => void
  disabled?: boolean
  iconSize?: number
  /** 'issue'(8상태, 기본) | 'container'(Project·Initiative 4상태) */
  kind?: StatusKind
}

function allowedFor(status: AnyStatus, kind: StatusKind): AnyStatus[] {
  return kind === 'container'
    ? CONTAINER_HUMAN_TRANSITIONS[status as ContainerStatus] ?? []
    : HUMAN_TRANSITIONS[status as EntityStatus] ?? []
}

function recommendedFor(status: AnyStatus, previous: AnyStatus | null | undefined, kind: StatusKind): AnyStatus[] {
  return kind === 'container'
    ? containerRecommendedNext(status as ContainerStatus)
    : getRecommendedNext(status as EntityStatus, previous as EntityStatus | null | undefined)
}

function labelFor(status: AnyStatus, kind: StatusKind): string {
  return kind === 'container'
    ? CONTAINER_STATUS_LABEL[status as ContainerStatus]
    : STATUS_LABEL[status as EntityStatus]
}

function transitionLabelFor(status: AnyStatus, kind: StatusKind): string {
  return kind === 'container'
    ? CONTAINER_TRANSITION_LABEL[status as ContainerStatus]
    : TRANSITION_LABEL[status as EntityStatus]
}

/** 리스트 행 인라인 status 전환 트리거. allowed transition 만 메뉴에 노출. */
export function StatusSelect({
  status,
  previousStatus,
  disallowedStatuses,
  onTransition,
  disabled,
  iconSize = 14,
  kind = 'issue',
}: StatusSelectProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const allowed = allowedFor(status, kind)
  const disallowedSet = new Set(disallowedStatuses ?? [])
  const recommendedSet = new Set(recommendedFor(status, previousStatus, kind))
  const targets = [...allowed]
    .filter((t) => !disallowedSet.has(t))
    .sort((a, b) => (recommendedSet.has(a) ? 0 : 1) - (recommendedSet.has(b) ? 0 : 1))

  const hasTargets = targets.length > 0 && !disabled

  if (!hasTargets) {
    return <StatusIcon status={status} size={iconSize} kind={kind} />
  }

  const pick = (t: AnyStatus) => {
    setOpen(false)
    onTransition(t)
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open) }}
        className="inline-flex items-center justify-center rounded hover:bg-bg-hover transition-colors -m-0.5 p-0.5"
        title={labelFor(status, kind)}
      >
        <StatusIcon status={status} size={iconSize} kind={kind} />
      </button>
      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="min-w-[160px] rounded-lg border border-border bg-bg-elevated shadow-lg py-1 animate-in fade-in slide-in-from-top-1 duration-150"
      >
        {targets.map((t) => {
          const isRecommended = recommendedSet.has(t)
          return (
            <button
              key={t}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); pick(t) }}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-bg-hover transition-colors text-sm ${isRecommended ? 'bg-accent/5' : ''}`}
            >
              {isRecommended && <ArrowRight size={11} className="text-accent" />}
              <StatusIcon status={t} size={13} kind={kind} />
              <span className="text-xs">{labelFor(t, kind)}</span>
              <span className="ml-auto text-2xs text-text-tertiary">{transitionLabelFor(t, kind)}</span>
            </button>
          )
        })}
      </Popover>
    </>
  )
}
