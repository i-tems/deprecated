import { useRef, useState } from 'react'
import { StatusIcon } from '@/components/StatusIcon'
import { Popover } from '@/components/Popover'
import { STATUS_LABEL, CONTAINER_STATUS_LABEL } from '@/lib/status'
import type { AnyStatus, ContainerStatus, EntityStatus, StatusKind } from '@/lib/types'

interface StatusPickerPillProps {
  value: AnyStatus
  onChange: (s: AnyStatus) => void
  /** 노출할 status 목록 (기본은 kind 별 create 시점 의미 있는 초기 상태) */
  options?: AnyStatus[]
  /** 'issue'(8상태, 기본) | 'container'(Project·Initiative 4상태) */
  kind?: StatusKind
}

const DEFAULT_ENTITY_OPTIONS: EntityStatus[] = ['backlog', 'todo']
const DEFAULT_CONTAINER_OPTIONS: ContainerStatus[] = ['backlog', 'active']

/** Create modal 용 status pill — transition rule 무시하고 options 만 노출. */
export function StatusPickerPill({
  value,
  onChange,
  options,
  kind = 'issue',
}: StatusPickerPillProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const opts: AnyStatus[] = options ?? (kind === 'container' ? DEFAULT_CONTAINER_OPTIONS : DEFAULT_ENTITY_OPTIONS)
  const label = (s: AnyStatus) =>
    kind === 'container' ? CONTAINER_STATUS_LABEL[s as ContainerStatus] : STATUS_LABEL[s as EntityStatus]

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle px-2.5 py-1 text-xs hover:bg-bg-hover transition-colors"
      >
        <StatusIcon status={value} size={12} kind={kind} />
        <span>{label(value)}</span>
      </button>
      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-44 rounded-lg border border-border bg-bg-elevated shadow-lg overflow-hidden animate-in fade-in slide-in-from-top-1 duration-150"
      >
        <ul className="py-1">
          {opts.map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={() => { onChange(s); setOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
              >
                <StatusIcon status={s} size={13} kind={kind} />
                <span className="flex-1">{label(s)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </>
  )
}
