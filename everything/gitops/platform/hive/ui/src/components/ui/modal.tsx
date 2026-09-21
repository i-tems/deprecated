import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  /** 'md'(기본, 폼 다이얼로그) | 'wide'(정독·transcript 뷰 — 사이드바와 확실히 다른 폭) */
  size?: 'md' | 'wide'
}

export function Modal({ open, onClose, title, children, size = 'md' }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      ref={overlayRef}
      onClick={(e) => e.target === overlayRef.current && onClose()}
      className={`fixed inset-0 z-50 flex items-end md:items-start justify-center bg-black/60 animate-in fade-in duration-150 ${
        size === 'wide' ? 'md:pt-[7vh]' : 'md:pt-[15vh]'
      }`}
    >
      <div className={`w-full rounded-t-xl md:rounded-xl border border-border bg-bg-elevated shadow-2xl animate-in slide-in-from-bottom-4 md:slide-in-from-top-2 duration-200 ${
        size === 'wide' ? 'max-w-4xl' : 'max-w-md'
      }`}>
        <div className="flex items-center justify-between px-4 md:px-5 py-3.5 border-b border-border-subtle">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="p-1 -mr-1 text-text-tertiary hover:text-text transition-colors">
            <X size={18} />
          </button>
        </div>
        <div className={`px-4 md:px-5 py-4 overflow-y-auto ${size === 'wide' ? 'max-h-[82vh]' : 'max-h-[70vh]'}`}>{children}</div>
      </div>
    </div>
  )
}
