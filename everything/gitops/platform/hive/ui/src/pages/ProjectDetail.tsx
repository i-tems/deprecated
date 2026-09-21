import { useState, useCallback, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ChevronRight, ChevronLeft, ListTodo, Plus,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LiveBanner } from '@/components/LiveBanner'
import { EditableDescription } from '@/components/EditableDescription'
import { SlotSection } from '@/components/SlotSection'
import { Markdown } from '@/components/Markdown'
import { extractOutcome } from '@/lib/decision'
import { EntityActions } from '@/components/EntityActions'
import { CreateEntityModal } from '@/components/CreateEntityModal'
import { StatusIcon } from '@/components/StatusIcon'
import { ActivityFeed } from '@/components/ActivityFeed'
import { LiveActivity } from '@/components/LiveActivity'
import { DetailHeader } from '@/components/DetailHeader'
import { ResourcesPanel } from '@/components/ResourcesPanel'
import { EntityPropertiesGroup } from '@/components/EntityPropertiesGroup'
import { InitiativeStatusIcon } from '@/components/InitiativeStatusIcon'
import { InitiativePropertyGroup } from '@/components/InitiativePropertyGroup'
import { HoldBadge } from '@/components/HoldBadge'
import { EntityMeta } from '@/components/EntityMeta'
import { MetaRow } from "@/components/PropertyRow"
import { DependenciesGroup, SourceSignalsGroup } from "@/components/EntityRefs"
import { LabelsGroup } from "@/components/LabelsGroup"
import { usePollingGate } from '@/hooks/usePollingGate'
import { useResourceEditor } from '@/hooks/useResourceEditor'
import { useStatusTransition } from '@/hooks/useStatusTransition'
import { useDetailShortcuts } from '@/hooks/useDetailShortcuts'
import { AssignMeTrigger } from '@/components/AssignMeTrigger'
import { useTitle } from '@/hooks/useTitle'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import { useAuth } from '@/contexts/AuthContext'
import { useToast } from '@/components/ui/toast'
import { projectGet, issueList, eventList, projectUpdate, labelList, resolveDependencyDetails, viewMark } from '@/lib/api'
import { relativeTime, entityShortName } from '@/lib/utils'
import { getSnoozeUntil, snoozeMetadataPatch } from '@/lib/snooze'
import type { Issue, Project } from '@/lib/types'

const TASK_PAGE_SIZE = 20

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  // 덱 read-state: 상세 열람 = "봤다" (best-effort, per-user last_viewed_at 갱신).
  useEffect(() => { if (projectId) viewMark('project', projectId).catch(() => {}) }, [projectId])
  const [showCreateTask, setShowCreateTask] = useState(false)
  const toast = useToast()
  const toCell = useCellAwareTo()
  const { user } = useAuth()
  const [issuePage, setTaskPage] = useState(0)

  const fetcher = useCallback(async () => {
    const project = await projectGet(projectId!)
    const [issueResult, feed, depDetails, labels] = await Promise.all([
      issueList({ project_id: projectId, limit: TASK_PAGE_SIZE, offset: issuePage * TASK_PAGE_SIZE }),
      eventList({ entity_type: 'project', entity_id: projectId }),
      resolveDependencyDetails(project.dependencies),
      labelList().catch(() => []),
    ])
    const issues = issueResult.issues.sort(
      (a: Issue, b: Issue) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
    return { project, issues, issueTotal: issueResult.total, feed, depDetails, labels }
  }, [projectId, issuePage])

  const { data, refetch, setData, liveStale, gate } = usePollingGate(fetcher, 5000, { scopes: ['cell'], entityId: projectId })
  useTitle(data?.project.title ?? 'Project')

  const handleTransition = useStatusTransition({
    kind: 'container',
    getCurrentStatus: () => data?.project.status,
    updateStatus: async (status, force, comment) => {
      await projectUpdate({
        project_id: projectId, status,
        ...(comment && { comment, comment_subtype: 'transition' }),
        ...(force && { force: true }),
      })
    },
    applyOptimistic: (status) =>
      setData((prev) => prev ? { ...prev, project: { ...prev.project, status: status as Project['status'] } } : prev),
    refetch,
    onError: (msg) => toast.error(msg),
  })

  const resEditor = useResourceEditor({
    getResources: () => data?.project.resources ?? [],
    updateResources: async (resources) => { await projectUpdate({ project_id: projectId, resources }) },
    onSuccess: refetch,
    onError: (msg) => toast.error(msg),
  })

  // Linear 식 상세 단축키 (s/p/a/l 피커, c 코멘트, i 나에게 할당).
  const assignToMe = useCallback(() => {
    if (!user?.email) return
    projectUpdate({ project_id: projectId, owner: user.email })
      .then(refetch)
      .catch((e) => toast.error(`담당자 지정 실패: ${(e as Error).message}`))
  }, [user?.email, projectId, refetch, toast])
  useDetailShortcuts({ onAssignToMe: assignToMe })

  if (gate) return gate
  const { project, issues, issueTotal, feed, depDetails, labels } = data!
  const issueTotalPages = Math.ceil(issueTotal / TASK_PAGE_SIZE)
  // T3 derived field — Project entity context 에 포함된 Initiative 요약. standalone 이면 null.
  const initiative = project.initiative ?? null

  return (
    <div className="max-w-6xl mx-auto space-y-6 pt-14 md:pt-16">
      <AssignMeTrigger onAssignToMe={assignToMe} />
      <LiveBanner stale={liveStale} />
      <DetailHeader
        list={{ label: 'Projects', path: '/projects' }}
        title={project.title}
        onTitleSave={async (next) => {
          await projectUpdate({ project_id: projectId, title: next })
          refetch()
        }}
        breadcrumbExtra={initiative && (
          <>
            <ChevronRight size={11} />
            <Link
              to={toCell(`/initiatives/${initiative.initiative_id}`)}
              className="inline-flex items-center gap-1 hover:text-text transition-colors min-w-0"
              title={`Initiative · ${initiative.status}`}
            >
              <InitiativeStatusIcon status={initiative.status} size={11} />
              <span className="truncate max-w-[200px]">{initiative.name}</span>
            </Link>
          </>
        )}
        createdAt={project.created_at}
        updatedAt={project.updated_at}
        shortName={entityShortName(project.project_id, project.cell_id, project.seq)}
        headerBadge={project.hold ? <HoldBadge /> : undefined}
      />

      <div className="entity-detail-grid grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-8">
        {/* Main column */}
        <div className="space-y-6 min-w-0">
          {(() => {
            const outcome = extractOutcome(project.description)
            return (
              <>
                {outcome && (
                  <SlotSection label="Outcome">
                    <Markdown className="text-sm text-text leading-relaxed">{outcome}</Markdown>
                  </SlotSection>
                )}
                <SlotSection label="Description" collapsible={!!outcome} defaultCollapsed={!!outcome}>
                  <EditableDescription
                    value={project.description}
                    onSave={async (next) => {
                      await projectUpdate({ project_id: projectId, description: next ?? '' })
                      refetch()
                    }}
                  />
                </SlotSection>
              </>
            )
          })()}

          <SlotSection label="Plan" collapsible defaultCollapsed>
            <EditableDescription
              value={project.plan}
              onSave={async (next) => {
                await projectUpdate({ project_id: projectId, plan: next ?? '' })
                refetch()
              }}
            />
          </SlotSection>

          <ResourcesPanel resources={project.resources} prs={project.pr_urls} artifacts={project.artifacts} deployments={project.deployments} editor={resEditor} />

          {/* Issues */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-tertiary">
              <ListTodo size={12} />
              Issues
              <Badge variant="ghost">{issueTotal}</Badge>
              <button
                type="button"
                onClick={() => setShowCreateTask(true)}
                className="ml-auto inline-flex items-center gap-1 text-text-tertiary hover:text-text rounded-md px-1.5 py-0.5 hover:bg-bg-hover transition-colors normal-case tracking-normal"
                title="Add issue"
              >
                <Plus size={12} />
                <span className="text-xs">Add</span>
              </button>
            </div>
            {issues.length === 0 ? (
              <button
                type="button"
                onClick={() => setShowCreateTask(true)}
                className="w-full flex items-center justify-center gap-2 rounded-md border border-dashed border-border-subtle px-3 py-2 text-xs text-text-tertiary hover:text-text hover:bg-bg-hover hover:border-border transition-colors"
              >
                <Plus size={13} />
                Add issue
              </button>
            ) : (
              <div className="rounded-md border border-border-subtle divide-y divide-border-subtle">
                {issues.map((t: Issue) => (
                  <Link
                    key={t.issue_id}
                    to={toCell(`/issues/${t.issue_id}`)}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-bg-hover transition-colors"
                  >
                    <StatusIcon status={t.status} size={13} />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm truncate block">{t.title}</span>
                      {t.description && (
                        <p className="text-xs text-text-tertiary truncate">{t.description}</p>
                      )}
                    </div>
                    {t.capability.length > 0 && (
                      <Badge variant="ghost" className="shrink-0 text-2xs">
                        {t.capability.length} cap
                      </Badge>
                    )}
                    <span className="text-xs text-text-tertiary shrink-0 tabular-nums">{relativeTime(t.updated_at)}</span>
                    <ChevronRight size={13} className="text-text-tertiary shrink-0" />
                  </Link>
                ))}
              </div>
            )}
            {issueTotalPages > 1 && (
              <div className="flex items-center justify-center gap-2 mt-2">
                <Button variant="ghost" size="sm" onClick={() => setTaskPage(p => p - 1)} disabled={issuePage === 0}>
                  <ChevronLeft size={14} />
                </Button>
                <span className="text-xs text-text-tertiary tabular-nums">
                  {issuePage + 1} / {issueTotalPages}
                </span>
                <Button variant="ghost" size="sm" onClick={() => setTaskPage(p => p + 1)} disabled={issuePage >= issueTotalPages - 1}>
                  <ChevronRight size={14} />
                </Button>
              </div>
            )}
          </div>

          <ActivityFeed entityType="project" entityId={projectId!} feed={feed} onRefetch={refetch} />
        </div>

        {/* Sidebar */}
        <aside className="entity-detail-aside space-y-3 lg:sticky lg:top-16 lg:self-start lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto">
          <EntityActions
            entityId={project.project_id}
            asPrompt={() => [
              `Project ${project.project_id}`,
              `Title: ${project.title}`,
              `Status: ${project.status}`,
              project.description ? `\n${project.description}` : '',
            ].join('\n')}
          />
          <EntityPropertiesGroup
            statusKind="container"
            status={project.status}
            previousStatus={project.previous_status}
            onStatusChange={handleTransition}
            priorityValue={project.priority?.value}
            onPriorityChange={async (value) => {
              await projectUpdate({
                project_id: projectId,
                ...(value !== null ? { priority: { value } } : { clear_priority: true }),
              })
              refetch()
            }}
            owner={project.owner}
            resolvedOwner={project.resolved_owner}
            onOwnerChange={async (email) => {
              await projectUpdate({ project_id: projectId, owner: email ?? '' })
              refetch()
            }}
            hold={project.hold}
            onHoldChange={async (hold) => {
              setData((prev) => prev ? { ...prev, project: { ...prev.project, hold } } : prev)
              await projectUpdate({ project_id: projectId, hold })
              refetch()
            }}
            snoozeUntil={getSnoozeUntil(project.metadata)}
            onSnoozeChange={async (until) => {
              const patch = snoozeMetadataPatch(until)
              setData((prev) => prev ? {
                ...prev,
                project: { ...prev.project, metadata: { ...(prev.project.metadata || {}), ...patch } },
              } : prev)
              await projectUpdate({ project_id: projectId, metadata: patch })
              refetch()
            }}
          />

          <LabelsGroup
            labelIds={project.labels}
            allLabels={labels}
            onChange={async (nextIds) => {
              setData((prev) => prev ? { ...prev, project: { ...prev.project, labels: nextIds } } : prev)
              await projectUpdate({ project_id: projectId, labels: nextIds })
              refetch()
            }}
          />

          <InitiativePropertyGroup
            initiativeId={project.initiative_id}
            onChange={async (nextId) => {
              setData((prev) => prev ? { ...prev, project: { ...prev.project, initiative_id: nextId } } : prev)
              await projectUpdate({ project_id: projectId, initiative_id: nextId ?? '' })
              refetch()
            }}
          />

          <DependenciesGroup dependencies={project.dependencies} depDetails={depDetails} />
          <SourceSignalsGroup signalIds={project.source_signal_ids} />

          <EntityMeta
            gates={project.gates}
            createdAt={project.created_at}
            updatedAt={project.updated_at}
            idLabel="Project ID"
            idValue={project.project_id}
            metadata={project.metadata}
            extraRows={
              initiative && (
                <MetaRow label="Initiative">
                  <Link
                    to={toCell(`/initiatives/${initiative.initiative_id}`)}
                    className="inline-flex items-center gap-1.5 hover:text-text transition-colors min-w-0"
                  >
                    <InitiativeStatusIcon status={initiative.status} size={11} />
                    <span className="truncate">{initiative.name}</span>
                  </Link>
                </MetaRow>
              )
            }
          />

          <LiveActivity entityType="project" entityId={projectId!} />
        </aside>
      </div>
      <CreateEntityModal
        kind="issue"
        open={showCreateTask}
        onClose={() => { setShowCreateTask(false); refetch() }}
        parentId={project.project_id}
      />
    </div>
  )
}
