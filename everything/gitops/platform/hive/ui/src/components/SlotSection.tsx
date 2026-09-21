import { useState, type ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'

interface SlotSectionProps {
  label: string
  children: ReactNode
  /** true면 라벨 클릭으로 본문을 접고 펼 수 있다 (길고 워커-중심인 plan·spec 슬롯용). */
  collapsible?: boolean
  /** collapsible 일 때 초기 접힘 여부. */
  defaultCollapsed?: boolean
}

/** description / plan 슬롯의 라벨 표시. collapsible 이면 라벨이 토글 버튼이 된다. */
export function SlotSection({ label, children, collapsible = false, defaultCollapsed = false }: SlotSectionProps) {
  const [open, setOpen] = useState(!defaultCollapsed)
  if (!collapsible) {
    return (
      <section className="space-y-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-text-tertiary">{label}</h3>
        {children}
      </section>
    )
  }
  return (
    <section className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-text-tertiary hover:text-text-secondary transition-colors"
      >
        <ChevronRight size={12} className={`transition-transform ${open ? 'rotate-90' : ''}`} />
        {label}
      </button>
      {open && children}
    </section>
  )
}
