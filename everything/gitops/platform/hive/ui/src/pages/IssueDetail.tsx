import { useCallback, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ChevronRight, Zap } from 'lucide-react'
import { LiveBanner } from '@/components/LiveBanner'
import { EditableDescription } from '@/components/EditableDescription'
import { SlotSection } from '@/components/SlotSection'
import { Markdown } from '@/components/Markdown'
import { extractOutcome } from '@/lib/decision'
import { EntityActions } from '@/components/EntityActions'
import { StatusIcon } from '@/components/StatusIcon'
import { ActivityFeed } from '@/components/ActivityFeed'
import { LiveActivity } from '@/components/LiveActivity'
import { DetailHeader } from '@/components/DetailHeader'
import { ResourcesPanel } from '@/components/ResourcesPanel'
import { EntityPropertiesGroup } from '@/components/EntityPropertiesGroup'
import { InitiativeStatusIcon } from '@/components/InitiativeStatusIcon'
import { HoldBadge } from '@/components/HoldBadge'
import { EntityMeta } from '@/components/EntityMeta'
import { PropertyItem, PropertyGroup, MetaRow } from '@/components/PropertyRow'
import { DependenciesGroup, SourceSignalsGroup } from '@/components/EntityRefs'
import { LabelsGroup } from '@/components/LabelsGroup'
import { usePollingGate } from '@/hooks/usePollingGate'
import { useResourceEditor } from '@/hooks/useResourceEditor'
import { useStatusTransition } from '@/hooks/useStatusTransition'
import { useDetailShortcuts } from '@/hooks/useDetailShortcuts'
import { AssignMeTrigger } from '@/components/AssignMeTrigger'
import { useAuth } from '@/contexts/AuthContext'
import { useTitle } from '@/hooks/useTitle'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import { useToast } from '@/components/ui/toast'
import { issueGet, projectGet, eventList, issueUpdate, labelList, resolveDependencyDetails, viewMark } from '@/lib/api'
import { entityShortName } from '@/lib/utils'
import { getSnoozeUntil, snoozeMetadataPatch } from '@/lib/snooze'
import type { Project, Issue } from '@/lib/types'

export default function IssueDetail() {
  const { issueId } = useParams<{ issueId: string }>()
  // 덱 read-state: 상세 열람 = "봤다" (best-effort, per-user last_viewed_at 갱신).
  useEffect(() => { if (issueId) viewMark('issue', issueId).catch(() => {}) }, [issueId])
  const toast = useToast()
  const toCell = useCellAwareTo()
  const { user } = useAuth()

  const resEditor = useResourceEditor({
    getResources: () => data?.issue.resources ?? [],
    updateResources: async (resources) => { await issueUpdate({ issue_id: issueId, resources }) },
    onSuccess: () => refetch(),
    onError: (msg) => toast.error(msg),
  })

  const fetcher = useCallback(async () => {
    const issue = await issueGet(issueId!)
    const [project, feed, depDetails, labels] = await Promise.all([
      issue.project_id ? projectGet(issue.project_id).catch(() => null) : Promise.resolve(null),
      eventList({ entity_type: 'issue', entity_id: issueId }),
      resolveDependencyDetails(issue.dependencies),
      labelList().catch(() => []),
    ])
    return { issue, project, feed, depDetails, labels }
  }, [issueId])

  const { data, refetch, setData, liveStale, gate } = usePollingGate(fetcher, 5000, { scopes: ['cell'], entityId: issueId })
  useTitle(data?.issue.title ?? 'Issue')

  const handleTransition = useStatusTransition({
    getCurrentStatus: () => data?.issue.status,
    updateStatus: async (status, force, comment) => {
      await issueUpdate({
        issue_id: issueId, status,
        ...(comment && { comment, comment_subtype: 'transition' }),
        ...(force && { force: true }),
      })
    },
    applyOptimistic: (status) => setData((prev) => prev ? { ...prev, issue: { ...prev.issue, status: status as Issue['status'] } } : prev),
    refetch,
    onError: (msg) => toast.error(msg),
  })

  // Linear 식 상세 단축키 (s/p/a/l 피커, c 코멘트, i 나에게 할당). i 는 owner 를 본인으로.
  const assignToMe = useCallback(() => {
    if (!user?.email) return
    issueUpdate({ issue_id: issueId, owner: user.email })
      .then(refetch)
      .catch((e) => toast.error(`담당자 지정 실패: ${(e as Error).message}`))
  }, [user?.email, issueId, refetch, toast])
  useDetailShortcuts({ onAssignToMe: assignToMe })

  if (gate) return gate
  const { issue, project, feed, depDetails, labels } = data!
  // T3 derived — effective Initiative 요약. standalone 이면 자체 anchor, project 있으면 상위 Project 상속.
  const initiative = issue.initiative ?? null

  return (
    <div className="max-w-6xl mx-auto space-y-6 pt-14 md:pt-16">
      <AssignMeTrigger onAssignToMe={assignToMe} />
      <LiveBanner stale={liveStale} />
      <DetailHeader
        list={{ label: 'Issues', path: '/issues' }}
        title={issue.title}
        onTitleSave={async (next) => {
          await issueUpdate({ issue_id: issueId, title: next })
          refetch()
        }}
        breadcrumbExtra={(initiative || project) && (
          <>
            {initiative && (
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
            {project && (
              <>
                <ChevronRight size={11} />
                <Link
                  to={toCell(`/projects/${(project as Project).project_id}`)}
                  className="inline-flex items-center gap-1 hover:text-text transition-colors min-w-0"
                >
                  <StatusIcon status={(project as Project).status} size={11} />
                  <span className="truncate max-w-[200px]">{(project as Project).title}</span>
                </Link>
              </>
            )}
          </>
        )}
        createdAt={issue.created_at}
        updatedAt={issue.updated_at}
        shortName={entityShortName(issue.issue_id, issue.cell_id, issue.seq)}
        headerBadge={issue.hold ? <HoldBadge /> : undefined}
      />

      <div className="entity-detail-grid grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-8">
        {/* Main column */}
        <div className="space-y-6 min-w-0">
          {(() => {
            const outcome = extractOutcome(issue.description)
            return (
              <>
                {outcome && (
                  <SlotSection label="Outcome">
                    <Markdown className="text-sm text-text leading-relaxed">{outcome}</Markdown>
                  </SlotSection>
                )}
                <SlotSection label="Description" collapsible={!!outcome} defaultCollapsed={!!outcome}>
                  <EditableDescription
                    value={issue.description}
                    onSave={async (next) => {
                      await issueUpdate({ issue_id: issueId, description: next ?? '' })
                      refetch()
                    }}
                  />
                </SlotSection>
              </>
            )
          })()}

          <SlotSection label="Plan" collapsible defaultCollapsed>
            <EditableDescription
              value={issue.plan}
              onSave={async (next) => {
                await issueUpdate({ issue_id: issueId, plan: next ?? '' })
                refetch()
              }}
            />
          </SlotSection>

          <ResourcesPanel resources={issue.resources} prs={issue.pr_urls} artifacts={issue.artifacts} deployments={issue.deployments} editor={resEditor} />

          <ActivityFeed entityType="issue" entityId={issueId!} feed={feed} onRefetch={refetch} />
        </div>

        {/* Sidebar */}
        <aside className="entity-detail-aside space-y-3 lg:sticky lg:top-16 lg:self-start lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto">
          <EntityActions
            entityId={issue.issue_id}
            asPrompt={() => [
              `Issue ${issue.issue_id}`,
              `Title: ${issue.title}`,
              `Status: ${issue.status}`,
              issue.description ? `\n${issue.description}` : '',
            ].join('\n')}
          />
          <EntityPropertiesGroup
            status={issue.status}
            previousStatus={issue.previous_status}
            onStatusChange={handleTransition}
            priorityValue={issue.priority?.value}
            onPriorityChange={async (value) => {
              await issueUpdate({
                issue_id: issueId,
                ...(value !== null ? { priority: { value } } : { clear_priority: true }),
              })
              refetch()
            }}
            owner={issue.owner}
            resolvedOwner={issue.resolved_owner}
            onOwnerChange={async (email) => {
              await issueUpdate({ issue_id: issueId, owner: email ?? '' })
              refetch()
            }}
            hold={issue.hold}
            onHoldChange={async (hold) => {
              setData((prev) => prev ? { ...prev, issue: { ...prev.issue, hold } } : prev)
              await issueUpdate({ issue_id: issueId, hold })
              refetch()
            }}
            snoozeUntil={getSnoozeUntil(issue.metadata)}
            onSnoozeChange={async (until) => {
              const patch = snoozeMetadataPatch(until)
              setData((prev) => prev ? {
                ...prev,
                issue: { ...prev.issue, metadata: { ...(prev.issue.metadata || {}), ...patch } },
              } : prev)
              await issueUpdate({ issue_id: issueId, metadata: patch })
              refetch()
            }}
            model={issue.model}
            onModelChange={async (model) => {
              await issueUpdate({ issue_id: issueId, model: model ?? null })
              refetch()
            }}
          />

          {issue.capability.length > 0 && (
            <PropertyGroup title="Capabilities">
              {issue.capability.map((c: string) => (
                <PropertyItem key={c} icon={<Zap size={12} className="text-accent" />}>
                  <span className="font-mono">{c}</span>
                </PropertyItem>
              ))}
            </PropertyGroup>
          )}

          <LabelsGroup
            labelIds={issue.labels}
            allLabels={labels}
            onChange={async (nextIds) => {
              setData((prev) => prev ? { ...prev, issue: { ...prev.issue, labels: nextIds } } : prev)
              await issueUpdate({ issue_id: issueId, labels: nextIds })
              refetch()
            }}
          />

          <DependenciesGroup dependencies={issue.dependencies} depDetails={depDetails} />
          <SourceSignalsGroup signalIds={issue.source_signal_ids} />

          <EntityMeta
            gates={issue.gates}
            createdAt={issue.created_at}
            updatedAt={issue.updated_at}
            idLabel="Issue ID"
            idValue={issue.issue_id}
            metadata={issue.metadata}
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

          <LiveActivity entityType="issue" entityId={issueId!} />
        </aside>
      </div>
    </div>
  )
}
