import { useEffect, useRef, useState } from 'react'
import { Compass } from 'lucide-react'
import { InitiativeStatusIcon } from '@/components/InitiativeStatusIcon'
import { Popover } from '@/components/Popover'
import type { Initiative } from '@/lib/types'

interface InitiativePickerPillProps {
  initiatives: Initiative[] | null   // null = 로딩 중
  value: string                       // initiative_id, 빈 문자열 = 미선택
  onChange: (id: string) => void
}

// Project 사이드바에서 같은 cell 의 Initiative 를 고르는 pill. cross-cell 거부는 hub
// validation 이 처리 — UI 는 활성 cell 의 initiative 만 노출한다.
export function InitiativePickerPill({ initiatives, value, onChange }: InitiativePickerPillProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const selected = initiatives?.find((i) => i.initiative_id === value) ?? null

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle px-2.5 py-1 text-xs hover:bg-bg-hover transition-colors max-w-[240px]"
      >
        {selected ? (
          <InitiativeStatusIcon status={selected.status} size={12} />
        ) : (
          <Compass size={12} className="text-initiative shrink-0" />
        )}
        {selected?.icon && <span className="shrink-0">{selected.icon}</span>}
        <span className="truncate">{selected ? selected.name : 'Initiative'}</span>
      </button>
      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-72 rounded-lg border border-border bg-bg-elevated shadow-lg overflow-hidden animate-in fade-in slide-in-from-top-1 duration-150"
      >
        <ul className="py-1 max-h-64 overflow-y-auto">
          <li>
            <button
              type="button"
              onClick={() => { onChange(''); setOpen(false) }}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm text-text-tertiary hover:bg-bg-hover transition-colors"
            >
              <span className="w-3" />
              <span className="flex-1 italic">No initiative</span>
            </button>
          </li>
          {initiatives === null && <li className="px-3 py-2 text-xs text-text-tertiary">Loading…</li>}
          {initiatives?.length === 0 && <li className="px-3 py-2 text-xs text-text-tertiary">No initiatives in this cell</li>}
          {initiatives?.map((i) => (
            <li key={i.initiative_id}>
              <button
                type="button"
                onClick={() => { onChange(i.initiative_id); setOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
              >
                <InitiativeStatusIcon status={i.status} size={12} />
                {i.icon && <span className="shrink-0">{i.icon}</span>}
                <span className="truncate flex-1">{i.name}</span>
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </>
  )
}
