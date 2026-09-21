import { useEffect, useRef, useState } from 'react'
import { useToast } from '@/components/ui/toast'

interface EditableTitleProps {
  value: string
  onSave: (next: string) => Promise<void>
}

/** Linear-style 제목: 클릭 시 인라인 input 편집. Enter 저장, Esc 취소. 빈 값은 거절. */
export function EditableTitle({ value, onSave }: EditableTitleProps) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [submitting, setSubmitting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setDraft(value)
  }, [value])

  useEffect(() => {
    if (editing && inputRef.current) {
      const el = inputRef.current
      el.focus()
      const len = el.value.length
      el.setSelectionRange(len, len)
    }
  }, [editing])

  const startEdit = () => {
    setDraft(value)
    setEditing(true)
  }
  const cancel = () => {
    setEditing(false)
    setDraft(value)
  }
  const save = async () => {
    const next = draft.trim()
    if (next.length === 0) {
      toast.error('제목은 비울 수 없습니다')
      return
    }
    if (next === value.trim()) {
      setEditing(false)
      return
    }
    setSubmitting(true)
    try {
      await onSave(next)
      setEditing(false)
    } catch (e) {
      toast.error(`저장 실패: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        disabled={submitting}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            save()
          } else if (e.key === 'Escape') {
            e.preventDefault()
            cancel()
          }
        }}
        className="w-full bg-transparent text-2xl font-semibold leading-tight text-text focus:outline-none focus-visible:outline-none disabled:opacity-60"
      />
    )
  }

  return (
    <h1
      role="button"
      tabIndex={0}
      onClick={startEdit}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          startEdit()
        }
      }}
      title="Click to edit"
      className="text-2xl font-semibold leading-tight rounded hover:bg-bg-hover transition-colors -mx-1 px-1 cursor-text"
    >
      {value}
    </h1>
  )
}
