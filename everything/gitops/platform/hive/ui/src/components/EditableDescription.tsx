import { useEffect, useRef, useState } from 'react'
import { Markdown } from '@/components/Markdown'
import { useToast } from '@/components/ui/toast'

interface EditableDescriptionProps {
  value: string | null | undefined
  onSave: (next: string | null) => Promise<void>
}

/** Linear-style description: 클릭 시 인라인 textarea 편집. Cmd+Enter 저장, Esc 취소. */
export function EditableDescription({ value, onSave }: EditableDescriptionProps) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const [submitting, setSubmitting] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pointerDown = useRef<{ x: number; y: number } | null>(null)

  useEffect(() => {
    setDraft(value ?? '')
  }, [value])

  // textarea 높이를 내용에 맞춘다. height='auto' 가 잠깐 textarea 를 rows 높이로
  // 줄였다 늘리는 reflow 가 윈도우 스크롤을 위로 튕기는 것을 막기 위해 스크롤 위치를 보존한다.
  const autosize = (ta: HTMLTextAreaElement) => {
    const { scrollX, scrollY } = window
    ta.style.height = 'auto'
    ta.style.height = ta.scrollHeight + 'px'
    if (window.scrollX !== scrollX || window.scrollY !== scrollY) {
      window.scrollTo(scrollX, scrollY)
    }
  }

  useEffect(() => {
    if (editing && textareaRef.current) {
      const ta = textareaRef.current
      ta.focus({ preventScroll: true })
      // 끝으로 캐럿 이동
      const len = ta.value.length
      ta.setSelectionRange(len, len)
      autosize(ta)
    }
  }, [editing])

  const startEdit = () => {
    setDraft(value ?? '')
    setEditing(true)
  }
  const onContainerClick = (e: React.MouseEvent) => {
    // 본문 안 링크 클릭은 편집 진입이 아니라 네비게이션으로 흘려보낸다.
    if ((e.target as HTMLElement).closest('a')) return
    // 드래그(텍스트 선택)로 끝난 클릭은 복사하려는 것이므로 편집 진입하지 않는다.
    const down = pointerDown.current
    if (down && (Math.abs(e.clientX - down.x) > 4 || Math.abs(e.clientY - down.y) > 4)) return
    const sel = window.getSelection()
    if (sel && !sel.isCollapsed && sel.toString().trim().length > 0) return
    startEdit()
  }
  const cancel = () => {
    setEditing(false)
    setDraft(value ?? '')
  }
  const save = async () => {
    const next = draft.trim()
    const current = (value ?? '').trim()
    if (next === current) {
      setEditing(false)
      return
    }
    setSubmitting(true)
    try {
      await onSave(next.length > 0 ? next : null)
      setEditing(false)
    } catch (e) {
      toast.error(`저장 실패: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  if (editing) {
    return (
      <div className="rounded-lg bg-bg px-5 pt-4 pb-3 space-y-2.5">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
            autosize(e.target)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              save()
            } else if (e.key === 'Escape') {
              cancel()
            }
          }}
          className="w-full bg-transparent text-sm text-text placeholder:text-text-tertiary focus:outline-none focus-visible:outline-none resize-none overflow-hidden leading-relaxed"
          rows={4}
        />
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">⌘↵ Save · Esc Cancel</span>
          <button
            type="button"
            onClick={cancel}
            disabled={submitting}
            className="ml-auto px-2.5 py-1 text-xs text-text-tertiary hover:text-text rounded-md hover:bg-bg-hover transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={submitting}
            className="px-3 py-1 text-xs font-medium bg-accent text-white rounded-md hover:bg-accent/90 disabled:opacity-40 transition-colors"
          >
            Save
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onMouseDown={(e) => {
        pointerDown.current = { x: e.clientX, y: e.clientY }
      }}
      onClick={onContainerClick}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          startEdit()
        }
      }}
      className="w-full text-left rounded-lg hover:bg-bg-hover transition-colors -mx-3 px-3 py-2.5 cursor-text block min-h-[2.25rem]"
      title="Click to edit"
    >
      {value && (
        <div className="prose-custom">
          <Markdown>{value}</Markdown>
        </div>
      )}
    </div>
  )
}
