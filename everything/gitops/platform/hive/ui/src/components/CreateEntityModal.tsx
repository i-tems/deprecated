import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCell } from '@/contexts/CellContext'
import { Target, ListTodo } from 'lucide-react'
import { projectCreate, projectList, issueCreate } from '@/lib/api'
import { useToast } from '@/components/ui/toast'
import { StatusPickerPill } from '@/components/StatusPickerPill'
import { PriorityLevelPill } from '@/components/PriorityLevelPill'
import { ProjectPickerPill } from '@/components/ProjectPickerPill'
import { CreateModalShell } from '@/components/CreateModalShell'
import { levelToValue, type PriorityLevel } from '@/components/PriorityPicker'
import { CONTAINER_ACTIVE_STATUSES } from '@/lib/constants'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import type { Project, AnyStatus } from '@/lib/types'

export type CreateEntityKind = 'issue' | 'project'

interface CreateEntityModalProps {
  kind: CreateEntityKind
  open: boolean
  onClose: () => void
  /** issue: parent project_id (지정 시 project picker 숨김). project kind 에서는 사용 안 함. */
  parentId?: string
  /** 생성 시 자동으로 채워질 initiative_id (Initiative detail 의 + Add Project / + Add Issue 진입).
   *  issue 는 project 미선택 시 standalone anchor, project 선택 시 dormant 로 보존 (model §5.1). */
  defaultInitiativeId?: string
}

const KIND_META = {
  issue: { icon: ListTodo, iconClass: 'text-issue', label: 'issue', titlePh: 'Issue title' },
  project: { icon: Target,   iconClass: 'text-project', label: 'project', titlePh: 'Project title' },
} as const

export function CreateEntityModal({ kind, open, onClose, parentId, defaultInitiativeId }: CreateEntityModalProps) {
  const navigate = useNavigate()
  const toast = useToast()
  const toCell = useCellAwareTo()
  const { currentCell } = useCell()

  // issue=8상태(기본 todo), project=container 4상태(기본 active = 바로 진행).
  const statusKind = kind === 'project' ? 'container' : 'issue'
  const defaultStatus: AnyStatus = kind === 'project' ? 'active' : 'todo'

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<AnyStatus>(defaultStatus)
  const [priorityLevel, setPriorityLevel] = useState<PriorityLevel>('none')
  const [selectedProjectId, setSelectedProjectId] = useState(parentId ?? '')
  const [submitting, setSubmitting] = useState(false)

  // issue일 때만 active project 목록 로드 (parentId 미지정 케이스). Project 은 optional — 자동 선택 안 함.
  const [projects, setGoals] = useState<Project[] | null>(null)
  useEffect(() => {
    if (!open || kind !== 'issue' || parentId) return
    projectList({})
      .then((list) => {
        const active = list.filter((g: Project) => CONTAINER_ACTIVE_STATUSES.has(g.status))
        setGoals(active)
      })
      .catch((e) => toast.error(`Project 목록 로드 실패: ${(e as Error).message}`))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kind, parentId])

  useEffect(() => {
    if (parentId) setSelectedProjectId(parentId)
  }, [parentId])

  const reset = () => {
    setTitle('')
    setDescription('')
    setPriorityLevel('none')
    setStatus(defaultStatus)
    setSubmitting(false)
  }

  const handleClose = () => {
    if (submitting) return
    reset()
    onClose()
  }

  const titleRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (open) setTimeout(() => titleRef.current?.focus(), 50)
  }, [open])

  const meta = KIND_META[kind]
  const canSubmit = title.trim().length > 0

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || submitting) return
    setSubmitting(true)
    const trimmed = title.trim()
    const desc = description.trim()
    const priority = priorityLevel === 'none' ? null : { value: levelToValue(priorityLevel) }
    try {
      if (kind === 'issue') {
        const issue = await issueCreate({
          title: trimmed,
          status,
          ...(selectedProjectId && { project_id: selectedProjectId }),
          ...(defaultInitiativeId && { initiative_id: defaultInitiativeId }),
          ...(desc && { description: desc }),
          ...(priority && { priority }),
        })
        reset(); onClose(); navigate(toCell(`/issues/${issue.issue_id}`))
      } else {
        const project = await projectCreate({
          title: trimmed,
          status,
          ...(defaultInitiativeId && { initiative_id: defaultInitiativeId }),
          ...(desc && { description: desc }),
          ...(priority && { priority }),
        })
        reset(); onClose(); navigate(toCell(`/projects/${project.project_id}`))
      }
    } catch (e) {
      toast.error(`${kind === 'issue' ? 'Issue' : 'Project'} 생성 실패: ${(e as Error).message}`)
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
        kindIcon: meta.icon,
        kindIconClass: meta.iconClass,
        kindLabel: `New ${meta.label}`,
      }}
      footer={{
        submitLabel: `Create ${meta.label}`,
        canSubmit,
        submitting,
      }}
    >
      <div className="px-5 pt-2 pb-4 space-y-3">
        <textarea
          ref={titleRef}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              if (canSubmit) handleSubmit(e as unknown as React.FormEvent)
            }
          }}
          placeholder={meta.titlePh}
          rows={1}
          className="w-full bg-transparent text-xl font-semibold placeholder:text-text-quaternary focus:outline-none resize-none"
          disabled={submitting}
        />
        <div className="space-y-1">
          <label className="text-xs uppercase tracking-wide text-text-tertiary">Description</label>
          <p className="text-xs text-text-tertiary">Outcome · Scope · Constraints · Facts · Notes</p>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={6}
            className="w-full bg-transparent text-sm placeholder:text-text-quaternary focus:outline-none resize-none"
            disabled={submitting}
          />
        </div>
      </div>

      <div className="px-4 pb-4 flex items-center gap-1.5 flex-wrap">
        <StatusPickerPill value={status} onChange={setStatus} kind={statusKind} />
        <PriorityLevelPill level={priorityLevel} onChange={setPriorityLevel} />
        {kind === 'issue' && !parentId && (
          <ProjectPickerPill projects={projects} value={selectedProjectId} onChange={setSelectedProjectId} />
        )}
      </div>
    </CreateModalShell>
  )
}
