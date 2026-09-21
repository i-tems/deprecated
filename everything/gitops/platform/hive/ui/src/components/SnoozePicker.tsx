import { useRef, useState } from 'react'
import { Clock } from 'lucide-react'
import { Popover } from '@/components/Popover'
import { dateAfter, formatRemaining, isFutureDate } from '@/lib/snooze'

interface SnoozePickerProps {
  /** 현재 metadata.snooze_until 을 Date 로 파싱한 값. 없으면 null. */
  until: Date | null
  /** null 전달 = 해제. */
  onChange: (until: Date | null) => void
}

const PRESETS: Array<{ label: string; addMs: number }> = [
  { label: '내일',   addMs: 1 * 24 * 60 * 60 * 1000 },
  { label: '3일 후', addMs: 3 * 24 * 60 * 60 * 1000 },
  { label: '1주 후', addMs: 7 * 24 * 60 * 60 * 1000 },
  { label: '2주 후', addMs: 14 * 24 * 60 * 60 * 1000 },
]

/**
 * 덱(Deck)에서 N일 뒤 다시 보기. hold(무기한 워커 픽업 차단) 와 직교.
 * 만료 판정은 read 시점 (덱이 5초 폴링하므로 만료 후 자동 복귀).
 */
export function SnoozePicker({ until, onChange }: SnoozePickerProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const active = isFutureDate(until)

  const setIn = (addMs: number) => {
    onChange(dateAfter(addMs))
    setOpen(false)
  }
  const clear = () => {
    onChange(null)
    setOpen(false)
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="덱에서 시한부로 숨김. 만료 시 자동 복귀. hold 와 독립."
        className="w-full flex items-center gap-2 min-h-[28px] px-1 py-1 rounded transition-colors text-left hover:bg-bg-hover cursor-pointer"
      >
        <span className="shrink-0 inline-flex items-center justify-center w-4 h-4">
          <Clock size={12} className={active ? 'text-accent' : 'text-text-tertiary'} />
        </span>
        <span className={`flex-1 min-w-0 text-sm ${active ? 'text-text' : 'text-text-tertiary'}`}>
          {active ? (
            <span className="text-accent font-medium">Snoozed · {formatRemaining(until!)}</span>
          ) : (
            'Snooze off'
          )}
        </span>
      </button>

      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-56 rounded-md border border-border bg-bg shadow-lg overflow-hidden"
      >
        <div className="px-2 py-1.5 text-xs text-text-tertiary border-b border-border-subtle">
          Snooze until…
        </div>
        <ul className="py-1">
          {PRESETS.map((p) => (
            <li key={p.label}>
              <button
                type="button"
                onClick={() => setIn(p.addMs)}
                className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
              >
                <Clock size={12} className="text-text-tertiary" />
                <span className="flex-1">{p.label}</span>
              </button>
            </li>
          ))}
          {active && (
            <li className="border-t border-border-subtle mt-1 pt-1">
              <button
                type="button"
                onClick={clear}
                className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors text-text-tertiary"
              >
                <span className="flex-1">해제</span>
              </button>
            </li>
          )}
        </ul>
      </Popover>
    </>
  )
}
