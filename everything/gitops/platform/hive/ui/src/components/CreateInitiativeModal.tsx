import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { useCell } from '@/contexts/CellContext'
import { useToast } from '@/components/ui/toast'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import { initiativeCreate } from '@/lib/api'
import { InitiativeStatusPicker } from '@/components/InitiativeStatusPicker'
import { PriorityLevelPill } from '@/components/PriorityLevelPill'
import { IconPickerButton } from '@/components/IconPickerButton'
import { CreateModalShell } from '@/components/CreateModalShell'
import { levelToValue, type PriorityLevel } from '@/components/PriorityPicker'
import type { InitiativeStatus } from '@/lib/types'

interface CreateInitiativeModalProps {
  open: boolean
  onClose: () => void
  /** sub-initiative 생성 시 parent 의 initiative_id. 명시 시 생성 요청에 parent_initiative_id 첨부. */
  parentInitiativeId?: string
  /** 헤더 breadcrumb 에 부모 표시용 이름 (선택). */
  parentName?: string
}

export function CreateInitiativeModal({ open, onClose, parentInitiativeId, parentName }: CreateInitiativeModalProps) {
  const navigate = useNavigate()
  const toast = useToast()
  const toCell = useCellAwareTo()
  const { currentCell } = useCell()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [icon, setIcon] = useState<string | null>(null)
  const [status, setStatus] = useState<InitiativeStatus>('backlog')
  const [priorityLevel, setPriorityLevel] = useState<PriorityLevel>('none')
  const [submitting, setSubmitting] = useState(false)

  const reset = () => {
    setName('')
    setDescription('')
    setIcon(null)
    setStatus('backlog')
    setPriorityLevel('none')
    setSubmitting(false)
  }

  const handleClose = () => {
    if (submitting) return
    reset()
    onClose()
  }

  const nameRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (open) setTimeout(() => nameRef.current?.focus(), 50)
  }, [open])

  const canSubmit = name.trim().length > 0
  const isSub = !!parentInitiativeId

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || submitting) return
    setSubmitting(true)
    const trimmed = name.trim()
    const desc = description.trim()
    const priority = priorityLevel === 'none' ? null : { value: levelToValue(priorityLevel) }
    try {
      const initiative = await initiativeCreate({
        name: trimmed,
        status,
        ...(icon && { icon }),
        ...(desc && { description: desc }),
        ...(priority && { priority }),
        ...(parentInitiativeId && { parent_initiative_id: parentInitiativeId }),
      })
      reset()
      onClose()
      navigate(toCell(`/initiatives/${initiative.initiative_id}`))
    } catch (err) {
      toast.error(`Initiative 생성 실패: ${(err as Error).message}`)
      setSubmitting(false)
    }
  }

  return (
    <CreateModalShell
      open={open}
      onClose={handleClose}
      onSubmit={handleSubmit}
      header={{
        cellName: currentCell?.name ?? 'workspace',
        kindIcon: Compass,
        kindIconClass: 'text-initiative',
        kindLabel: isSub ? 'New sub-initiative' : 'New initiative',
        parentLabel: isSub ? parentName : undefined,
      }}
      footer={{
        submitLabel: isSub ? 'Create sub-initiative' : 'Create initiative',
        canSubmit,
        submitting,
      }}
    >
      <div className="px-5 pt-2 pb-4 space-y-3">
        <div className="flex items-start gap-2">
          <IconPickerButton icon={icon} onChange={setIcon} size="lg" />
          <textarea
            ref={nameRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (canSubmit) handleSubmit(e as unknown as React.FormEvent)
              }
            }}
            placeholder="Initiative name"
            rows={1}
            className="flex-1 bg-transparent text-xl font-semibold placeholder:text-text-quaternary focus:outline-none resize-none"
            disabled={submitting}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs uppercase tracking-wide text-text-tertiary">Description</label>
          <p className="text-xs text-text-tertiary">Strategic intent · 자유 형식 markdown.</p>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={5}
            className="w-full bg-transparent text-sm placeholder:text-text-quaternary focus:outline-none resize-none"
            disabled={submitting}
          />
        </div>
      </div>

      <div className="px-4 pb-4 flex items-center gap-1.5 flex-wrap">
        <InitiativeStatusPicker value={status} onChange={setStatus} />
        <PriorityLevelPill level={priorityLevel} onChange={setPriorityLevel} />
      </div>
    </CreateModalShell>
  )
}
