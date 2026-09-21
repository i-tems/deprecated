import { useRef, useState } from 'react'
import { Popover } from '@/components/Popover'
import { PriorityIcon, type PriorityLevel, PRIORITY_COLOR } from '@/components/PriorityPicker'

const LEVELS: PriorityLevel[] = ['none', 'urgent', 'high', 'medium', 'low']
const LABEL: Record<PriorityLevel, string> = {
  none: 'Priority',
  urgent: 'Urgent',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

interface PriorityLevelPillProps {
  level: PriorityLevel
  onChange: (l: PriorityLevel) => void
}

// 생성 모달용 priority pill — Popover 기반. 사이드바용 PriorityPicker 와 별개
// (label 톤 다름: 사이드바는 "Set priority"/"No priority", pill 은 "Priority").
export function PriorityLevelPill({ level, onChange }: PriorityLevelPillProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle px-2.5 py-1 text-xs hover:bg-bg-hover transition-colors"
      >
        <span className={PRIORITY_COLOR[level]}>
          <PriorityIcon level={level} size={13} />
        </span>
        <span>{LABEL[level]}</span>
      </button>
      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-44 rounded-lg border border-border bg-bg-elevated shadow-lg overflow-hidden"
      >
        <ul className="py-1">
          {LEVELS.map((l) => (
            <li key={l}>
              <button
                type="button"
                onClick={() => { onChange(l); setOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
              >
                <span className={PRIORITY_COLOR[l]}>
                  <PriorityIcon level={l} size={13} />
                </span>
                <span className="flex-1">{LABEL[l]}</span>
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </>
  )
}
