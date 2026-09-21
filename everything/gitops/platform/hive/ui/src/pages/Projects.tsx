import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { Target, ChevronRight, User, Search, Plus } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { OwnerAvatar } from '@/components/OwnerAvatar'
import { Input } from '@/components/ui/input'
import { Empty } from '@/components/ui/empty'
import { LiveBanner } from '@/components/LiveBanner'
import { PageHeader } from '@/components/PageHeader'
import { FilterTabs } from '@/components/FilterTabs'
import { IconButton } from '@/components/IconButton'
import { StatusSelect } from '@/components/StatusSelect'
import { HoldBadge } from '@/components/HoldBadge'
import { PriorityIcon, valueToLevel, PRIORITY_COLOR } from '@/components/PriorityPicker'
import { CreateEntityModal } from '@/components/CreateEntityModal'
import { usePollingGate } from '@/hooks/usePollingGate'
import { usePersistedState } from '@/hooks/usePersistedState'
import { useUrlState } from '@/hooks/useUrlState'
import { useTitle } from '@/hooks/useTitle'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import { useToast } from '@/components/ui/toast'
import { projectList, issueList, projectUpdate, issueUpdate } from '@/lib/api'
import { relativeTime, entityShortName } from '@/lib/utils'
import {
  ACTIVE_STATUSES,
  CONTAINER_ACTIVE_STATUSES,
  STATUS_FILTER_TABS,
  type StatusFilterValue,
} from '@/lib/constants'
import type { Project, Issue, EntityStatus, ContainerStatus } from '@/lib/types'

export default function Projects() {
  const toast = useToast()
  useTitle('Projects')
  const toCell = useCellAwareTo()
  const { user } = useAuth()
  const [filter, setFilter] = useUrlState<StatusFilterValue>('filter', 'active')
  const [mineOnly, setMineOnly] = usePersistedState('projects:mine', false)
  const [search, setSearch] = useState('')
  const [showSearch, setShowSearch] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [showCreate, setShowCreate] = useState(false)

  const fetcher = useCallback(async () => {
    const issueParams: Record<string, unknown> =
      filter === 'active' ? { statuses: [...ACTIVE_STATUSES] } : {}
    const [projects, issueResult] = await Promise.all([projectList({}), issueList(issueParams)])
    return { projects, issues: issueResult.issues }
  }, [filter])

  const { data, lastUpdated, refetch, setData, liveStale, gate } = usePollingGate(fetcher, 5000, { scopes: ['cell'] })

  if (gate) return gate
  const { projects, issues } = data!

  const tasksByGoal = issues.reduce<Record<string, Issue[]>>((acc, t) => {
    ;(acc[t.project_id] ??= []).push(t)
    return acc
  }, {})

  const expandedSet = expanded

  const matchesFilter = (g: Project) =>
    filter === 'active' ? CONTAINER_ACTIVE_STATUSES.has(g.status) : true

  const filtered = projects
    .filter(matchesFilter)
    .filter((g) => !mineOnly || g.resolved_owner === user?.email)
    .filter((g) => !search || `${g.title} ${g.project_id}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleGoalTransition = async (projectId: string, status: ContainerStatus) => {
    setData((prev) => prev ? {
      ...prev,
      projects: prev.projects.map((g: Project) => g.project_id === projectId ? { ...g, status } : g),
    } : prev)
    try {
      await projectUpdate({ project_id: projectId, status })
      refetch()
    } catch (e) {
      toast.error(`Project 상태 변경 실패: ${(e as Error).message}`)
      refetch()
    }
  }

  const handleTaskTransition = async (issueId: string, status: EntityStatus) => {
    setData((prev) => prev ? {
      ...prev,
      issues: prev.issues.map((t: Issue) => t.issue_id === issueId ? { ...t, status } : t),
    } : prev)
    try {
      await issueUpdate({ issue_id: issueId, status })
      refetch()
    } catch (e) {
      toast.error(`Issue 상태 변경 실패: ${(e as Error).message}`)
      refetch()
    }
  }

  function ProjectRow({ project }: { project: Project }) {
    const projectTasks = tasksByGoal[project.project_id] ?? []
    const isExpanded = expandedSet.has(project.project_id)
    const hasChildren = projectTasks.length > 0
    const projectLevel = valueToLevel(project.priority?.value)

    return (
      <>
        <div
          className="group flex items-center gap-2 px-1 py-1 rounded-md hover:bg-bg-hover transition-colors"
          style={{ paddingLeft: '4px' }}
        >
          <button
            onClick={() => hasChildren && toggleExpand(project.project_id)}
            className="shrink-0 w-3.5 h-3.5 flex items-center justify-center text-text-quaternary transition-transform"
            style={{ transform: isExpanded ? 'rotate(90deg)' : 'none' }}
            disabled={!hasChildren}
          >
            {hasChildren && <ChevronRight size={11} />}
          </button>
          <span className={`shrink-0 ${PRIORITY_COLOR[projectLevel]}`}>
            <PriorityIcon level={projectLevel} size={13} />
          </span>
          <StatusSelect
            status={project.status}
            previousStatus={project.previous_status}
            onTransition={(s) => handleGoalTransition(project.project_id, s as ContainerStatus)}
            iconSize={14}
            kind="container"
          />
          {project.hold && <HoldBadge />}
          {entityShortName(project.project_id, project.cell_id, project.seq) && (
            <span className="text-xs text-text-tertiary tabular-nums shrink-0">
              {entityShortName(project.project_id, project.cell_id, project.seq)}
            </span>
          )}
          <Link to={toCell(`/projects/${project.project_id}`)} className="flex-1 min-w-0">
            <span className="text-sm truncate block">{project.title}</span>
          </Link>
          <div className="shrink-0 w-5 flex justify-center">
            {project.resolved_owner ? <OwnerAvatar email={project.resolved_owner} size="xs" /> : null}
          </div>
          <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-14 text-right whitespace-nowrap">
            {relativeTime(project.updated_at)}
          </span>
        </div>

        {isExpanded && hasChildren && (
          <div className="relative" style={{ marginLeft: '14px' }}>
            <div className="absolute left-0 top-0 bottom-0 w-px bg-border-subtle" />
            {projectTasks.map((t) => {
              const issueLevel = valueToLevel(t.priority?.value)
              return (
                <div
                  key={t.issue_id}
                  className="group flex items-center gap-2 px-1 py-1 rounded-md hover:bg-bg-hover transition-colors"
                  style={{ paddingLeft: '18px' }}
                >
                  <span className={`shrink-0 ${PRIORITY_COLOR[issueLevel]}`}>
                    <PriorityIcon level={issueLevel} size={13} />
                  </span>
                  <StatusSelect
                    status={t.status}
                    previousStatus={t.previous_status}
                    onTransition={(s) => handleTaskTransition(t.issue_id, s as EntityStatus)}
                    iconSize={14}
                  />
                  {t.hold && <HoldBadge />}
                  <Link to={toCell(`/issues/${t.issue_id}`)} className="flex-1 min-w-0">
                    <span className="text-sm truncate block text-text-secondary">{t.title}</span>
                  </Link>
                  <div className="shrink-0 w-5 flex justify-center">
                    {t.resolved_owner ? <OwnerAvatar email={t.resolved_owner} size="xs" /> : null}
                  </div>
                  <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-14 text-right whitespace-nowrap">
                    {relativeTime(t.updated_at)}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </>
    )
  }

  return (
    <div className="space-y-3">
      <LiveBanner stale={liveStale} />
      <PageHeader
        title="Projects"
        icon={Target}
        iconClass="text-project"
        lastUpdated={lastUpdated}
        actions={<IconButton icon={Plus} onClick={() => setShowCreate(true)} title="새 Project" size={15} />}
      />

      <FilterTabs
        value={filter}
        onChange={setFilter}
        tabs={STATUS_FILTER_TABS}
        trailing={
          <>
            <IconButton active={showSearch} onClick={() => setShowSearch((v) => !v)} icon={Search} title="검색" />
            <IconButton active={mineOnly} onClick={() => setMineOnly(!mineOnly)} icon={User} title="내 항목만" />
          </>
        }
      />

      {showSearch && (
        <div className="px-1">
          <Input
            placeholder="Search projects..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            className="w-full"
          />
        </div>
      )}

      <CreateEntityModal kind="project" open={showCreate} onClose={() => setShowCreate(false)} />

      {filtered.length === 0 ? (
        <Empty
          icon={<Target size={20} />}
          title="Project 없음"
          description={search ? '검색 결과가 없습니다' : '아직 생성된 Project이 없습니다'}
        />
      ) : (
        <div>
          {filtered.map((g) => (
            <ProjectRow key={g.project_id} project={g} />
          ))}
        </div>
      )}
    </div>
  )
}
