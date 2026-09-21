import { useEffect, type ReactNode } from 'react'
import { X, Box, ChevronRight } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

interface CreateModalShellProps {
  open: boolean
  /** 백드롭 클릭·ESC·Cancel·X 모두 같은 closer 호출. submitting 중 차단은 caller 책임. */
  onClose: () => void
  /** form submit. children 은 form body 만 — shell 이 form 으로 wrap. */
  onSubmit: (e: React.FormEvent) => void
  header: {
    /** 좌상단 breadcrumb 의 cell 이름 (e.g. currentCell?.name ?? 'workspace'). */
    cellName: string
    /** entity 종류 아이콘 (Issue=ListTodo, Project=Target, Initiative=Compass). */
    kindIcon: LucideIcon
    /** kindIcon 의 색 — text-issue / text-project / text-initiative. */
    kindIconClass: string
    /** "New issue" / "New initiative" / "New sub-initiative" 등. */
    kindLabel: string
    /** 추가 breadcrumb 노드 (e.g. sub-initiative 의 parent name). */
    parentLabel?: string
  }
  footer: {
    /** "Create issue" / "Create initiative" 등 (submitting 중엔 "Creating…" 노출). */
    submitLabel: string
    canSubmit: boolean
    submitting: boolean
  }
  /** 본문 — textarea·property pills row 등 caller-specific. shell 이 form 으로 wrap. */
  children: ReactNode
}

// Create*Modal 공용 shell: backdrop + container + ESC + header (cell breadcrumb +
// kind icon/label + optional parent) + form + footer (Cancel/Submit). 두 캐스트
// (CreateEntityModal · CreateInitiativeModal) 에서 같은 modal frame · header ·
// footer boilerplate 가 중복돼 추출 (~85 lines 절감).
export function CreateModalShell({ open, onClose, onSubmit, header, footer, children }: CreateModalShellProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const { cellName, kindIcon: KindIcon, kindIconClass, kindLabel, parentLabel } = header
  const { submitLabel, canSubmit, submitting } = footer

  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      className="fixed inset-0 z-50 flex items-end md:items-start justify-center bg-black/50 md:pt-[12vh] animate-in fade-in duration-150"
    >
      <div className="w-full max-w-2xl rounded-t-2xl md:rounded-2xl bg-bg-elevated shadow-2xl animate-in slide-in-from-bottom-4 md:slide-in-from-top-2 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-1.5 text-sm">
            <span className="inline-flex items-center justify-center w-6 h-6 rounded-md border border-border-subtle bg-bg">
              <Box size={13} className="text-accent" />
            </span>
            <span className="text-text-secondary">{cellName}</span>
            <ChevronRight size={12} className="text-text-tertiary" />
            <span className="text-text inline-flex items-center gap-1">
              <KindIcon size={13} className={kindIconClass} />
              {kindLabel}
            </span>
            {parentLabel && (
              <>
                <ChevronRight size={12} className="text-text-tertiary" />
                <span className="text-text-secondary truncate max-w-[200px]" title={parentLabel}>{parentLabel}</span>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 -mr-1 text-text-tertiary hover:text-text transition-colors rounded"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={onSubmit}>
          {children}

          {/* Footer */}
          <div className="px-4 py-3 flex items-center justify-end gap-2 border-t border-border-subtle bg-bg-subtle/30 rounded-b-2xl">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="rounded-md px-3 py-1.5 text-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !canSubmit}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover transition-colors disabled:opacity-50"
            >
              {submitting ? 'Creating…' : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
