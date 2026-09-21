import { useEffect, useRef, useState } from 'react'
import { Target } from 'lucide-react'
import { Popover } from '@/components/Popover'
import type { Project } from '@/lib/types'

interface ProjectPickerPillProps {
  projects: Project[] | null   // null = 로딩 중
  value: string           // project_id, 빈 문자열 = 미선택 (standalone issue)
  onChange: (id: string) => void
}

// Issue 생성 시 같은 cell 의 active Project 을 고르는 pill. cross-cell 거부는 hub
// validation 이 처리 — UI 는 활성 cell 의 active project 만 노출한다.
// InitiativePickerPill 와 동형 (Popover 기반).
export function ProjectPickerPill({ projects, value, onChange }: ProjectPickerPillProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const selected = projects?.find((g) => g.project_id === value)

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
        <Target size={12} className="text-project shrink-0" />
        <span className="truncate">{selected ? selected.title : 'Project'}</span>
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
              <span className="flex-1 italic">No project (standalone)</span>
            </button>
          </li>
          {projects === null && <li className="px-3 py-2 text-xs text-text-tertiary">Loading…</li>}
          {projects?.length === 0 && <li className="px-3 py-2 text-xs text-text-tertiary">No active projects</li>}
          {projects?.map((g) => (
            <li key={g.project_id}>
              <button
                type="button"
                onClick={() => { onChange(g.project_id); setOpen(false) }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
              >
                <Target size={12} className="text-project shrink-0" />
                <span className="truncate flex-1">{g.title}</span>
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </>
  )
}
