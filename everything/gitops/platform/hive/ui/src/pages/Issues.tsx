import { useCallback, useState } from 'react'
import { ListTodo, Search, ChevronRight, ChevronLeft, User, Plus } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Empty } from '@/components/ui/empty'
import { LiveBanner } from '@/components/LiveBanner'
import { PageHeader } from '@/components/PageHeader'
import { FilterTabs } from '@/components/FilterTabs'
import { IconButton } from '@/components/IconButton'
import { StatusGroupedList } from '@/components/StatusGroupedList'
import { IssueListRow } from '@/components/IssueListRow'
import { CreateEntityModal } from '@/components/CreateEntityModal'
import { usePollingGate } from '@/hooks/usePollingGate'
import { usePersistedState } from '@/hooks/usePersistedState'
import { useUrlState } from '@/hooks/useUrlState'
import { useTitle } from '@/hooks/useTitle'
import { useToast } from '@/components/ui/toast'
import { issueList, projectList, issueUpdate } from '@/lib/api'
import {
  ACTIVE_STATUSES,
  STATUS_FILTER_TABS,
  type StatusFilterValue,
} from '@/lib/constants'
import type { Issue, Project, EntityStatus } from '@/lib/types'

const PAGE_SIZE = 30

export default function Issues() {
  const toast = useToast()
  useTitle('Issues')
  const { user } = useAuth()
  const [filter, setFilter] = useUrlState<StatusFilterValue>('filter', 'active')
  const [mineOnly, setMineOnly] = usePersistedState('issues:mine', false)
  const [search, setSearch] = useState('')
  const [showSearch, setShowSearch] = useState(false)
  const [page, setPage] = useState(0)
  const [showCreate, setShowCreate] = useState(false)

  const fetcher = useCallback(async () => {
    const params: Record<string, unknown> =
      filter === 'active' ? { statuses: [...ACTIVE_STATUSES] } : {}
    params.limit = PAGE_SIZE
    params.offset = page * PAGE_SIZE
    const [result, projects] = await Promise.all([issueList(params), projectList()])
    return { issues: result.issues, total: result.total, projects }
  }, [filter, page])

  const { data, lastUpdated, refetch, setData, liveStale, gate } = usePollingGate(fetcher, 5000, { scopes: ['cell'] })

  if (gate) return gate
  const { issues, total, projects } = data!
  const projectMap = Object.fromEntries(projects.map((g: Project) => [g.project_id, g]))
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const filtered = issues
    .filter((t: Issue) => !mineOnly || t.resolved_owner === user?.email)
    .filter((t: Issue) => !search || `${t.title} ${t.issue_id}`.toLowerCase().includes(search.toLowerCase()))

  const handleFilterChange = (f: StatusFilterValue) => {
    setFilter(f)
    setPage(0)
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
      toast.error(`상태 변경 실패: ${(e as Error).message}`)
      refetch()
    }
  }

  const renderTaskRow = (t: Issue) => (
    <IssueListRow
      issue={t}
      project={projectMap[t.project_id]}
      onTransition={(s) => handleTaskTransition(t.issue_id, s)}
    />
  )

  return (
    <div className="space-y-3">
      <LiveBanner stale={liveStale} />
      <PageHeader
        title="Issues"
        icon={ListTodo}
        iconClass="text-issue"
        lastUpdated={lastUpdated}
        actions={<IconButton icon={Plus} onClick={() => setShowCreate(true)} title="새 Issue" size={15} />}
      />

      <FilterTabs
        value={filter}
        onChange={handleFilterChange}
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
            placeholder="Search issues..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            className="w-full"
          />
        </div>
      )}

      {filtered.length === 0 ? (
        <Empty icon={<ListTodo size={20} />} title="Issue 없음" />
      ) : (
        <StatusGroupedList
          items={filtered}
          getStatus={(t) => t.status}
          itemKey={(t) => t.issue_id}
          renderItem={renderTaskRow}
          storageKey="issues:status"
          onCreate={() => setShowCreate(true)}
        />
      )}

      <CreateEntityModal kind="issue" open={showCreate} onClose={() => setShowCreate(false)} />

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <Button variant="ghost" size="sm" onClick={() => setPage((p) => p - 1)} disabled={page === 0}>
            <ChevronLeft size={14} />
          </Button>
          <span className="text-xs text-text-tertiary tabular-nums">
            {page + 1} / {totalPages}
          </span>
          <Button variant="ghost" size="sm" onClick={() => setPage((p) => p + 1)} disabled={page >= totalPages - 1}>
            <ChevronRight size={14} />
          </Button>
        </div>
      )}
    </div>
  )
}
