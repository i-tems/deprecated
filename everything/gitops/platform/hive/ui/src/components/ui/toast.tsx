import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'

type ToastKind = 'error' | 'success' | 'info'

interface Toast {
  id: string
  kind: ToastKind
  message: string
}

interface ToastContextValue {
  error: (message: string) => void
  success: (message: string) => void
  info: (message: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}

const ICON = {
  error: <AlertCircle size={14} className="text-error shrink-0" />,
  success: <CheckCircle2 size={14} className="text-success shrink-0" />,
  info: <Info size={14} className="text-info shrink-0" />,
}

const BORDER = {
  error: 'border-error/40',
  success: 'border-success/40',
  info: 'border-info/40',
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    setToasts((prev) => [...prev, { id, kind, message }])
    setTimeout(() => dismiss(id), 4000)
  }, [dismiss])

  const value: ToastContextValue = {
    error: (m) => push('error', m),
    success: (m) => push('success', m),
    info: (m) => push('info', m),
  }

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 lg:bottom-20 z-[100] flex flex-col gap-2 max-w-sm pointer-events-none">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const [entered, setEntered] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setEntered(true))
    return () => cancelAnimationFrame(id)
  }, [])
  return (
    <div
      className={`pointer-events-auto flex items-start gap-2 rounded-lg border ${BORDER[toast.kind]} bg-bg-elevated shadow-lg px-3 py-2.5 transition-all duration-150 ${
        entered ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      }`}
    >
      {ICON[toast.kind]}
      <p className="text-xs text-text flex-1 leading-relaxed">{toast.message}</p>
      <button onClick={onDismiss} className="text-text-tertiary hover:text-text shrink-0">
        <X size={12} />
      </button>
    </div>
  )
}
