import { useRef, useState } from 'react'
import { Popover } from '@/components/Popover'
import { KbdHint } from '@/components/KbdHint'
import { InitiativeStatusIcon } from '@/components/InitiativeStatusIcon'
import { INITIATIVE_STATUSES, INITIATIVE_STATUS_LABEL } from '@/lib/initiative'
import type { InitiativeStatus } from '@/lib/types'

interface InitiativeStatusPickerProps {
  value: InitiativeStatus
  onChange: (s: InitiativeStatus) => void
  /** pill 스타일(생성 모달용) vs sidebar 행 스타일(상세 페이지용). 기본 pill. */
  variant?: 'pill' | 'row'
}

// 3상태 모두 양방향 전이 허용 (Linear 정합 — 실수 정정·전략 재평가).
export function InitiativeStatusPicker({ value, onChange, variant = 'pill' }: InitiativeStatusPickerProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const triggerClass = variant === 'pill'
    ? 'inline-flex items-center gap-1.5 rounded-full border border-border-subtle px-2.5 py-1 text-xs hover:bg-bg-hover transition-colors'
    : 'w-full flex items-center gap-2 min-h-[28px] px-1 py-1 rounded hover:bg-bg-hover transition-colors text-left text-sm'

  return (
    <>
      <button
        ref={triggerRef}
        data-kb="status"
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={triggerClass}
        title="상태 변경 (s)"
      >
        <InitiativeStatusIcon status={value} size={variant === 'pill' ? 12 : 13} />
        <span className={variant === 'pill' ? '' : 'flex-1'}>{INITIATIVE_STATUS_LABEL[value]}</span>
        {variant === 'row' && <KbdHint k="s" />}
      </button>
      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-44 rounded-lg border border-border bg-bg-elevated shadow-lg overflow-hidden animate-in fade-in slide-in-from-top-1 duration-150"
      >
        <ul className="py-1">
          {INITIATIVE_STATUSES.map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={() => { onChange(s); setOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
              >
                <InitiativeStatusIcon status={s} size={13} />
                <span className="flex-1">{INITIATIVE_STATUS_LABEL[s]}</span>
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </>
  )
}
