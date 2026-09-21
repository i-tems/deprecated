import { useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { KbdHint } from '@/components/KbdHint'
import { Popover } from '@/components/Popover'

/** Linear의 4단계 priority + No priority. 우리 모델은 {value: 1-5}. */
export type PriorityLevel = 'none' | 'urgent' | 'high' | 'medium' | 'low'

const LEVEL_ORDER: PriorityLevel[] = ['none', 'urgent', 'high', 'medium', 'low']

const LEVEL_LABEL: Record<PriorityLevel, string> = {
  none: 'No priority',
  urgent: 'Urgent',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

/** value(1-5) → Linear level. null/0 → none, 5 → urgent, 4 → high, 3 → medium, 2/1 → low. */
export function valueToLevel(value: number | null | undefined): PriorityLevel {
  if (!value) return 'none'
  if (value >= 5) return 'urgent'
  if (value === 4) return 'high'
  if (value === 3) return 'medium'
  return 'low'
}

/** level → value. none → null (priority 제거 의미). */
export function levelToValue(level: PriorityLevel): number | null {
  if (level === 'none') return null
  if (level === 'urgent') return 5
  if (level === 'high') return 4
  if (level === 'medium') return 3
  return 2 // low
}

/** Priority level → text color class. List/row leading indicator에 사용. */
export const PRIORITY_COLOR: Record<PriorityLevel, string> = {
  urgent: 'text-error',
  high: 'text-warning',
  medium: 'text-text-secondary',
  low: 'text-text-tertiary',
  none: 'text-text-quaternary',
}

/** Linear-style priority 아이콘. 3개의 막대 높이 표시. */
export function PriorityIcon({ level, size = 14 }: { level: PriorityLevel; size?: number }) {
  if (level === 'none') {
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
        <line x1="3" y1="8" x2="5" y2="8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="7" y1="8" x2="9" y2="8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="11" y1="8" x2="13" y2="8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }
  if (level === 'urgent') {
    return (
      <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
        <rect x="2" y="2" width="12" height="12" rx="2" fill="currentColor" />
        <rect x="7.25" y="4.5" width="1.5" height="5" rx="0.75" fill="white" />
        <rect x="7.25" y="10.5" width="1.5" height="1.5" rx="0.75" fill="white" />
      </svg>
    )
  }
  // high/medium/low — 3 bars at varying heights, lower bars filled
  const bars = level === 'high' ? 3 : level === 'medium' ? 2 : 1
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={2 + i * 4}
          y={12 - (i + 1) * 3}
          width={2.5}
          height={(i + 1) * 3}
          rx={0.5}
          fill={i < bars ? 'currentColor' : 'currentColor'}
          opacity={i < bars ? 1 : 0.3}
        />
      ))}
    </svg>
  )
}

interface PriorityPickerProps {
  /** 현재 issue.priority?.value */
  value: number | null | undefined
  onChange: (value: number | null) => void
}

export function PriorityPicker({ value, onChange }: PriorityPickerProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const current = valueToLevel(value)

  const select = (level: PriorityLevel) => {
    if (level !== current) onChange(levelToValue(level))
    setOpen(false)
  }

  const triggerColor = current === 'urgent' ? 'text-error'
    : current === 'high' ? 'text-warning'
    : current === 'medium' ? 'text-text'
    : current === 'low' ? 'text-text-tertiary'
    : 'text-text-tertiary'

  return (
    <div>
      <button
        ref={triggerRef}
        data-kb="priority"
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full hover:bg-bg-hover transition-colors text-sm"
        title="Set priority (p)"
      >
        <span className={triggerColor}>
          <PriorityIcon level={current} size={14} />
        </span>
        <span>{current === 'none' ? 'Set priority' : LEVEL_LABEL[current]}</span>
        <ChevronDown size={10} className="text-text-tertiary" />
        <KbdHint k="p" />
      </button>

      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-64 rounded-md border border-border bg-bg shadow-lg overflow-hidden"
      >
        <div className="px-2 py-1.5 text-xs text-text-tertiary border-b border-border-subtle">
          Set priority to…
        </div>
        <ul className="py-1">
          {LEVEL_ORDER.map((level) => {
            const isCurrent = level === current
            const color = level === 'urgent' ? 'text-error'
              : level === 'high' ? 'text-warning'
              : level === 'medium' ? 'text-text'
              : 'text-text-tertiary'
            return (
              <li key={level}>
                <button
                  type="button"
                  onClick={() => select(level)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
                >
                  <span className={color}>
                    <PriorityIcon level={level} size={14} />
                  </span>
                  <span className="flex-1">{LEVEL_LABEL[level]}</span>
                  {isCurrent && <span className="text-text-tertiary">✓</span>}
                </button>
              </li>
            )
          })}
        </ul>
      </Popover>
    </div>
  )
}
