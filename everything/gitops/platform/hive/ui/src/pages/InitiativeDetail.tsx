import { useState, useCallback, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ChevronRight, Target, Compass, Plus, ListTodo, Lock, LockOpen } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LiveBanner } from '@/components/LiveBanner'
import { LiveActivity } from '@/components/LiveActivity'
import { ActivityFeed } from '@/components/ActivityFeed'
import { HoldBadge } from '@/components/HoldBadge'
import { EditableDescription } from '@/components/EditableDescription'
import { SlotSection } from '@/components/SlotSection'
import { EntityActions } from '@/components/EntityActions'
import { StatusIcon } from '@/components/StatusIcon'
import { DetailHeader } from '@/components/DetailHeader'
import { ResourcesPanel } from '@/components/ResourcesPanel'
import { InitiativeStatusIcon } from '@/components/InitiativeStatusIcon'
import { InitiativeStatusPicker } from '@/components/InitiativeStatusPicker'
import { CreateInitiativeModal } from '@/components/CreateInitiativeModal'
import { CreateEntityModal } from '@/components/CreateEntityModal'
import { PriorityPicker } from '@/components/PriorityPicker'
import { AssigneePicker } from '@/components/AssigneePicker'
import { InitiativePropertyGroup } from '@/components/InitiativePropertyGroup'
import { PropertyGroup, PropertyItem, MetaRow } from '@/components/PropertyRow'
import { EntityMeta } from '@/components/EntityMeta'
import { usePollingGate } from '@/hooks/usePollingGate'
import { useResourceEditor } from '@/hooks/useResourceEditor'
import { useDetailShortcuts } from '@/hooks/useDetailShortcuts'
import { AssignMeTrigger } from '@/components/AssignMeTrigger'
import { useTitle } from '@/hooks/useTitle'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import { useAuth } from '@/contexts/AuthContext'
import { useToast } from '@/components/ui/toast'
import {
  initiativeGet, initiativeUpdate, initiativeList,
  projectList, issueList, eventList, viewMark,
} from '@/lib/api'
import { entityShortName, relativeTime } from '@/lib/utils'
import type { Initiative, Project, Issue } from '@/lib/types'

export default function InitiativeDetail() {
  const { initiativeId } = useParams<{ initiativeId: string }>()
  // 덱 read-state: 상세 열람 = "봤다" (best-effort, per-user last_viewed_at 갱신).
  useEffect(() => { if (initiativeId) viewMark('initiative', initiativeId).catch(() => {}) }, [initiativeId])
  const toast = useToast()
  const [showCreateSub, setShowCreateSub] = useState(false)
  const [showCreateGoal, setShowCreateGoal] = useState(false)
  const [showCreateIssue, setShowCreateIssue] = useState(false)
  const toCell = useCellAwareTo()
  const { user } = useAuth()

  const fetcher = useCallback(async () => {
    const initiative = await initiativeGet(initiativeId!)
    // hub project.list 는 initiative_id 필터를 지원하지 않으므로 client-side 필터링.
    // sub-initiative 도 list 의 parent_initiative_id 로 client 필터 — '__all__' 로 전부 받아 처리.
    const [allInitiatives, allGoals, issueResult, feed] = await Promise.all([
      initiativeList({ parent_initiative_id: '__all__' }),
      projectList({}),
      // 직접 anchor 된 standalone Issue 만 (project 경유 Issue 는 그 Project 노드 하위에 보임).
      issueList({ initiative_id: initiativeId!, standalone: true }).catch(() => ({ issues: [] })),
      // 워커·사람 comment / status_change 활동 (핸드오프·완료추천 코멘트 가시성).
      eventList({ entity_type: 'initiative', entity_id: initiativeId! }).catch(() => []),
    ])
    const parent = initiative.parent_initiative_id
      ? allInitiatives.find((i: Initiative) => i.initiative_id === initiative.parent_initiative_id) ?? null
      : null
    const subInitiatives = allInitiatives.filter(
      (i: Initiative) => i.parent_initiative_id === initiativeId,
    )
    const linkedGoals = allGoals.filter((g: Project) => g.initiative_id === initiativeId)
    const linkedIssues = (issueResult.issues ?? []).sort(
      (a: Issue, b: Issue) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )
    return { initiative, parent, subInitiatives, linkedGoals, linkedIssues, feed }
  }, [initiativeId])

  const { data, refetch, setData, liveStale, gate } = usePollingGate(fetcher, 5000, {
    scopes: ['cell'],
    entityId: initiativeId,
  })
  useTitle(data?.initiative.name ?? 'Initiative')

  const resEditor = useResourceEditor({
    getResources: () => data?.initiative.resources ?? [],
    updateResources: async (resources) => {
      await initiativeUpdate({ initiative_id: initiativeId, resources })
    },
    onSuccess: refetch,
    onError: (msg) => toast.error(msg),
  })

  // Linear 식 상세 단축키 (s 상태·p 우선순위·a 담당자 피커, c 코멘트, i 나에게 할당). Initiative 는 라벨 없음.
  const assignToMe = useCallback(() => {
    if (!user?.email) return
    initiativeUpdate({ initiative_id: initiativeId, owner: user.email })
      .then(refetch)
      .catch((e) => toast.error(`담당자 지정 실패: ${(e as Error).message}`))
  }, [user?.email, initiativeId, refetch, toast])
  useDetailShortcuts({ onAssignToMe: assignToMe })

  if (gate) return gate
  const { initiative, parent, subInitiatives, linkedGoals, linkedIssues, feed } = data!

  return (
    <div className="max-w-6xl mx-auto space-y-6 pt-14 md:pt-16">
      <AssignMeTrigger onAssignToMe={assignToMe} />
      <LiveBanner stale={liveStale} />
      <DetailHeader
        list={{ label: 'Initiatives', path: '/initiatives' }}
        title={initiative.name}
        icon={initiative.icon}
        onIconChange={async (next) => {
          await initiativeUpdate({ initiative_id: initiativeId, icon: next ?? '' })
          refetch()
        }}
        onTitleSave={async (next) => {
          await initiativeUpdate({ initiative_id: initiativeId, name: next })
          refetch()
        }}
        breadcrumbExtra={parent && (
          <>
            <ChevronRight size={11} />
            <Link
              to={toCell(`/initiatives/${(parent as Initiative).initiative_id}`)}
              className="inline-flex items-center gap-1 hover:text-text transition-colors min-w-0"
            >
              <InitiativeStatusIcon status={(parent as Initiative).status} size={11} />
              {(parent as Initiative).icon && <span className="shrink-0">{(parent as Initiative).icon}</span>}
              <span className="truncate max-w-[200px]">{(parent as Initiative).name}</span>
            </Link>
          </>
        )}
        createdAt={initiative.created_at}
        updatedAt={initiative.updated_at}
        shortName={entityShortName(initiative.initiative_id, initiative.cell_id, initiative.seq)}
        headerBadge={initiative.hold ? <HoldBadge /> : undefined}
      />

      <div className="entity-detail-grid grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-8">
        {/* Main column */}
        <div className="space-y-6 min-w-0">
          <SlotSection label="Description">
            <EditableDescription
              value={initiative.description}
              onSave={async (next) => {
                await initiativeUpdate({ initiative_id: initiativeId, description: next ?? '' })
                refetch()
              }}
            />
          </SlotSection>

          <ResourcesPanel resources={initiative.resources} prs={undefined} editor={resEditor} />

          {/* Sub-initiatives — Linear nested tree (≤5 depth) */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-tertiary">
              <Compass size={12} />
              Sub-initiatives
              <Badge variant="ghost">{subInitiatives.length}</Badge>
              <button
                type="button"
                onClick={() => setShowCreateSub(true)}
                className="ml-auto inline-flex items-center gap-1 text-text-tertiary hover:text-text rounded-md px-1.5 py-0.5 hover:bg-bg-hover transition-colors normal-case tracking-normal"
                title="Add sub-initiative"
              >
                <Plus size={12} />
                <span className="text-xs">Add</span>
              </button>
            </div>
            {subInitiatives.length === 0 ? (
              <button
                type="button"
                onClick={() => setShowCreateSub(true)}
                className="w-full flex items-center justify-center gap-2 rounded-md border border-dashed border-border-subtle px-3 py-2 text-xs text-text-tertiary hover:text-text hover:bg-bg-hover hover:border-border transition-colors"
              >
                <Plus size={13} />
                Add sub-initiative
              </button>
            ) : (
              <div className="rounded-md border border-border-subtle divide-y divide-border-subtle">
                {subInitiatives.map((s: Initiative) => (
                  <Link
                    key={s.initiative_id}
                    to={toCell(`/initiatives/${s.initiative_id}`)}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-bg-hover transition-colors"
                  >
                    <InitiativeStatusIcon status={s.status} size={13} />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm truncate block">{s.name}</span>
                      {s.description && (
                        <p className="text-xs text-text-tertiary truncate">{s.description}</p>
                      )}
                    </div>
                    <span className="text-xs text-text-tertiary shrink-0 tabular-nums">{relativeTime(s.updated_at)}</span>
                    <ChevronRight size={13} className="text-text-tertiary shrink-0" />
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Projects — manually curated (Linear 정합). 자동 attach 없음. */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-tertiary">
              <Target size={12} />
              Projects
              <Badge variant="ghost">{linkedGoals.length}</Badge>
              <button
                type="button"
                onClick={() => setShowCreateGoal(true)}
                className="ml-auto inline-flex items-center gap-1 text-text-tertiary hover:text-text rounded-md px-1.5 py-0.5 hover:bg-bg-hover transition-colors normal-case tracking-normal"
                title="Add project"
              >
                <Plus size={12} />
                <span className="text-xs">Add</span>
              </button>
            </div>
            {linkedGoals.length === 0 ? (
              <button
                type="button"
                onClick={() => setShowCreateGoal(true)}
                className="w-full flex items-center justify-center gap-2 rounded-md border border-dashed border-border-subtle px-3 py-2 text-xs text-text-tertiary hover:text-text hover:bg-bg-hover hover:border-border transition-colors"
              >
                <Plus size={13} />
                Add project
              </button>
            ) : (
              <div className="rounded-md border border-border-subtle divide-y divide-border-subtle">
                {linkedGoals.map((g: Project) => (
                  <Link
                    key={g.project_id}
                    to={toCell(`/projects/${g.project_id}`)}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-bg-hover transition-colors"
                  >
                    <StatusIcon status={g.status} size={13} kind="container" />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm truncate block">{g.title}</span>
                    </div>
                    <span className="text-xs text-text-tertiary shrink-0 tabular-nums">{relativeTime(g.updated_at)}</span>
                    <ChevronRight size={13} className="text-text-tertiary shrink-0" />
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* 직접 연결 Issues — standalone Issue 가 자체 initiative_id 로 직접 anchor.
              project 경유 Issue 는 그 Project 노드 하위에 보이므로 여기엔 standalone 만.
              비어 있어도 Add 진입을 노출 (Projects 섹션과 대칭). */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-tertiary">
              <ListTodo size={12} />
              Issues
              <Badge variant="ghost">{linkedIssues.length}</Badge>
              <button
                type="button"
                onClick={() => setShowCreateIssue(true)}
                className="ml-auto inline-flex items-center gap-1 text-text-tertiary hover:text-text rounded-md px-1.5 py-0.5 hover:bg-bg-hover transition-colors normal-case tracking-normal"
                title="Add issue"
              >
                <Plus size={12} />
                <span className="text-xs">Add</span>
              </button>
            </div>
            {linkedIssues.length === 0 ? (
              <button
                type="button"
                onClick={() => setShowCreateIssue(true)}
                className="w-full flex items-center justify-center gap-2 rounded-md border border-dashed border-border-subtle px-3 py-2 text-xs text-text-tertiary hover:text-text hover:bg-bg-hover hover:border-border transition-colors"
              >
                <Plus size={13} />
                Add issue
              </button>
            ) : (
              <div className="rounded-md border border-border-subtle divide-y divide-border-subtle">
                {linkedIssues.map((t: Issue) => (
                  <Link
                    key={t.issue_id}
                    to={toCell(`/issues/${t.issue_id}`)}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-bg-hover transition-colors"
                  >
                    <StatusIcon status={t.status} size={13} />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm truncate block">{t.title}</span>
                    </div>
                    <span className="text-xs text-text-tertiary shrink-0 tabular-nums">{relativeTime(t.updated_at)}</span>
                    <ChevronRight size={13} className="text-text-tertiary shrink-0" />
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Activity — 워커·사람 comment(핸드오프·완료추천)·status_change 타임라인. */}
          <ActivityFeed entityType="initiative" entityId={initiative.initiative_id} feed={feed} onRefetch={refetch} />
        </div>

        {/* Sidebar */}
        <aside className="entity-detail-aside space-y-3 lg:sticky lg:top-16 lg:self-start lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto">
          <EntityActions
            entityId={initiative.initiative_id}
            asPrompt={() => [
              `Initiative ${initiative.initiative_id}`,
              `Name: ${initiative.name}`,
              `Status: ${initiative.status}`,
              initiative.description ? `\n${initiative.description}` : '',
            ].join('\n')}
          />

          <PropertyGroup title="Properties">
            <div className="px-1 py-1 space-y-1">
              <InitiativeStatusPicker
                value={initiative.status}
                variant="row"
                onChange={async (next) => {
                  setData((prev) => prev ? { ...prev, initiative: { ...prev.initiative, status: next } } : prev)
                  try {
                    await initiativeUpdate({ initiative_id: initiative.initiative_id, status: next })
                    refetch()
                  } catch (e) {
                    toast.error(`상태 변경 실패: ${(e as Error).message}`)
                    refetch()
                  }
                }}
              />
              <PriorityPicker
                value={initiative.priority?.value}
                onChange={async (value) => {
                  try {
                    await initiativeUpdate({
                      initiative_id: initiative.initiative_id,
                      ...(value !== null ? { priority: { value } } : { clear_priority: true }),
                    })
                    refetch()
                  } catch (e) {
                    toast.error(`우선순위 변경 실패: ${(e as Error).message}`)
                  }
                }}
              />
              <AssigneePicker
                owner={initiative.owner}
                resolvedOwner={initiative.owner}
                onChange={async (email) => {
                  await initiativeUpdate({ initiative_id: initiative.initiative_id, owner: email ?? '' })
                  refetch()
                }}
              />
              <PropertyItem
                icon={initiative.hold
                  ? <Lock size={12} className="text-warning" />
                  : <LockOpen size={12} className="text-text-tertiary" />}
                title="agent-loop 자동 오케스트레이션 차단 토글. 수동 steering 중 켜고, 끝나면 해제. (leaf initiative 만 워커가 동작)"
                empty={!initiative.hold}
                onClick={async () => {
                  const next = !initiative.hold
                  setData((prev) => prev ? { ...prev, initiative: { ...prev.initiative, hold: next } } : prev)
                  try {
                    await initiativeUpdate({ initiative_id: initiative.initiative_id, hold: next })
                    refetch()
                  } catch (e) {
                    toast.error(`Hold 변경 실패: ${(e as Error).message}`)
                    refetch()
                  }
                }}
              >
                {initiative.hold ? <span className="text-warning font-medium">Hold</span> : 'Hold off'}
              </PropertyItem>
            </div>
          </PropertyGroup>

          <InitiativePropertyGroup
            title="Parent"
            excludeDescendantsOf={initiative.initiative_id}
            initiativeId={initiative.parent_initiative_id}
            onChange={async (next) => {
              // 빈 값(No initiative) → '' 로 보내 parent 제거(root). hub: '' → None.
              try {
                await initiativeUpdate({ initiative_id: initiative.initiative_id, parent_initiative_id: next ?? '' })
                refetch()
              } catch (e) {
                toast.error(`Parent 변경 실패: ${(e as Error).message}`)
                refetch()
              }
            }}
          />

          <EntityMeta
            createdAt={initiative.created_at}
            updatedAt={initiative.updated_at}
            idLabel="Initiative ID"
            idValue={initiative.initiative_id}
            extraRows={
              initiative.parent_initiative_id && (
                <MetaRow label="Parent ID">
                  <code className="font-mono text-2xs text-text-secondary">{initiative.parent_initiative_id}</code>
                </MetaRow>
              )
            }
          />

          <LiveActivity entityType="initiative" entityId={initiative.initiative_id} />
        </aside>
      </div>

      <CreateInitiativeModal
        open={showCreateSub}
        onClose={() => { setShowCreateSub(false); refetch() }}
        parentInitiativeId={initiative.initiative_id}
        parentName={initiative.name}
      />
      <CreateEntityModal
        kind="project"
        open={showCreateGoal}
        onClose={() => { setShowCreateGoal(false); refetch() }}
        defaultInitiativeId={initiative.initiative_id}
      />
      <CreateEntityModal
        kind="issue"
        open={showCreateIssue}
        onClose={() => { setShowCreateIssue(false); refetch() }}
        defaultInitiativeId={initiative.initiative_id}
      />
    </div>
  )
}
