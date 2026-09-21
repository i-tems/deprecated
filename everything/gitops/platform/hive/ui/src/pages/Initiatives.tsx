import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { Compass, ChevronRight, CornerDownRight, Search, Plus } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Empty } from '@/components/ui/empty'
import { LiveBanner } from '@/components/LiveBanner'
import { PageHeader } from '@/components/PageHeader'
import { FilterTabs } from '@/components/FilterTabs'
import { IconButton } from '@/components/IconButton'
import { InitiativeStatusIcon } from '@/components/InitiativeStatusIcon'
import { PriorityIcon, valueToLevel, PRIORITY_COLOR } from '@/components/PriorityPicker'
import { CreateInitiativeModal } from '@/components/CreateInitiativeModal'
import { usePollingGate } from '@/hooks/usePollingGate'
import { useUrlState } from '@/hooks/useUrlState'
import { useTitle } from '@/hooks/useTitle'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import { initiativeList } from '@/lib/api'
import { INITIATIVE_STATUS_LABEL } from '@/lib/initiative'
import { relativeTime, entityShortName } from '@/lib/utils'
import type { Initiative } from '@/lib/types'
import type { FilterTab } from '@/components/FilterTabs'

// Initiative status 는 Project 과 동일한 container 모델(backlog|active|waiting|done|archive).
// archive 는 별도 retention flag 가 아니라 terminal status 다.
type InitiativeFilter = 'active' | 'backlog' | 'waiting' | 'done' | 'archive' | 'all'

// 'Active' = 진행 중(active). 'Archived' 탭만 archive 된 항목을 보이고, 나머지 탭은
// archive 를 제외한다 (status 별 탭에 archive 가 섞이지 않게).
const TABS: FilterTab<InitiativeFilter>[] = [
  { value: 'active', label: INITIATIVE_STATUS_LABEL.active },
  { value: 'backlog', label: INITIATIVE_STATUS_LABEL.backlog },
  { value: 'waiting', label: INITIATIVE_STATUS_LABEL.waiting },
  { value: 'done', label: INITIATIVE_STATUS_LABEL.done },
  { value: 'all', label: 'All' },
  { value: 'archive', label: INITIATIVE_STATUS_LABEL.archive },
]

function matchesFilter(i: Initiative, filter: InitiativeFilter): boolean {
  if (filter === 'archive') return i.status === 'archive'
  if (i.status === 'archive') return false
  if (filter === 'all') return true
  return i.status === filter
}

export default function Initiatives() {
  useTitle('Initiatives')
  const toCell = useCellAwareTo()
  const [filter, setFilter] = useUrlState<InitiativeFilter>('filter', 'active')
  const [search, setSearch] = useState('')
  const [showSearch, setShowSearch] = useState(false)
  const [showCreate, setShowCreate] = useState(false)

  // include_archived 로 archive 된 항목까지 받아 client 에서 탭별로 가른다 (cell 규모상 충분).
  const fetcher = useCallback(() => initiativeList({ parent_initiative_id: '__all__', include_archived: true }), [])
  const { data, lastUpdated, refetch, liveStale, gate } = usePollingGate(fetcher, 5000, { scopes: ['cell'] })

  if (gate) return gate
  const initiatives = data ?? []

  // priority_score desc → updated_at desc (Project/Issue 와 동일 패턴).
  const byPriority = (a: Initiative, b: Initiative) => {
    const ps = (b.priority_score ?? 0) - (a.priority_score ?? 0)
    if (ps !== 0) return ps
    return (b.updated_at || '').localeCompare(a.updated_at || '')
  }

  // 필터·검색을 통과한 항목 id 집합. 트리는 이 집합으로 "직접 매칭"을 판정한다.
  const matched = new Set(
    initiatives
      .filter((i) => matchesFilter(i, filter))
      .filter((i) => !search || `${i.name} ${i.initiative_id}`.toLowerCase().includes(search.toLowerCase()))
      .map((i) => i.initiative_id),
  )

  // parent_initiative_id 로 트리 구성. parent 가 응답에 없는(orphan) 항목은 root 로 승격.
  const byId = new Map(initiatives.map((i) => [i.initiative_id, i]))
  const childrenOf = new Map<string, Initiative[]>()
  const roots: Initiative[] = []
  for (const i of initiatives) {
    const pid = i.parent_initiative_id
    if (pid && byId.has(pid)) {
      const arr = childrenOf.get(pid)
      if (arr) arr.push(i)
      else childrenOf.set(pid, [i])
    } else {
      roots.push(i)
    }
  }

  // 자식만 매칭돼도 부모를 컨텍스트로 끌고 올라온다 (subtree 에 매칭이 하나라도 있으면 표시).
  const subtreeCache = new Map<string, boolean>()
  const subtreeMatched = (i: Initiative): boolean => {
    const cached = subtreeCache.get(i.initiative_id)
    if (cached !== undefined) return cached
    let r = matched.has(i.initiative_id)
    for (const c of childrenOf.get(i.initiative_id) ?? []) if (subtreeMatched(c)) r = true
    subtreeCache.set(i.initiative_id, r)
    return r
  }

  // depth 순 평탄화. context = 자기는 필터에 안 맞지만 자식 때문에 끌려온 흐린 부모 행.
  type Row = { init: Initiative; depth: number; context: boolean }
  const rows: Row[] = []
  const walk = (i: Initiative, depth: number) => {
    if (!subtreeMatched(i)) return
    rows.push({ init: i, depth, context: !matched.has(i.initiative_id) })
    for (const c of [...(childrenOf.get(i.initiative_id) ?? [])].sort(byPriority)) walk(c, depth + 1)
  }
  for (const r of [...roots].sort(byPriority)) walk(r, 0)

  return (
    <div className="space-y-3">
      <LiveBanner stale={liveStale} />
      <PageHeader
        title="Initiatives"
        icon={Compass}
        iconClass="text-initiative"
        lastUpdated={lastUpdated}
        actions={<IconButton icon={Plus} onClick={() => setShowCreate(true)} title="새 Initiative" size={15} />}
      />

      <FilterTabs
        value={filter}
        onChange={setFilter}
        tabs={TABS}
        trailing={
          <IconButton active={showSearch} onClick={() => setShowSearch((v) => !v)} icon={Search} title="검색" />
        }
      />

      {showSearch && (
        <div className="px-1">
          <Input
            placeholder="Search initiatives..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            className="w-full"
          />
        </div>
      )}

      <CreateInitiativeModal open={showCreate} onClose={() => { setShowCreate(false); refetch() }} />

      {rows.length === 0 ? (
        <Empty
          icon={<Compass size={20} />}
          title="Initiative 없음"
          description={search ? '검색 결과가 없습니다' : '아직 생성된 Initiative 가 없습니다'}
        />
      ) : (
        <div className="rounded-md border border-border-subtle divide-y divide-border-subtle">
          {rows.map(({ init: i, depth, context }) => (
            <Link
              key={i.initiative_id}
              to={toCell(`/initiatives/${i.initiative_id}`)}
              className={`flex items-center gap-3 px-3 py-2 hover:bg-bg-hover transition-colors ${context ? 'opacity-55' : ''}`}
              style={depth > 0 ? { paddingLeft: 12 + depth * 18 } : undefined}
            >
              {depth > 0 && (
                <CornerDownRight size={13} className="shrink-0 -ml-0.5 text-text-tertiary" />
              )}
              <span className={`shrink-0 ${PRIORITY_COLOR[valueToLevel(i.priority?.value)]}`}>
                <PriorityIcon level={valueToLevel(i.priority?.value)} size={13} />
              </span>
              <InitiativeStatusIcon status={i.status} size={13} />
              {entityShortName(i.initiative_id, i.cell_id, i.seq) && (
                <span className="text-xs text-text-tertiary tabular-nums shrink-0">
                  {entityShortName(i.initiative_id, i.cell_id, i.seq)}
                </span>
              )}
              <div className="flex-1 min-w-0">
                <span className="text-sm truncate block">
                  {i.icon && <span className="mr-1.5">{i.icon}</span>}
                  {i.name}
                </span>
                {i.description && (
                  <p className="text-xs text-text-tertiary truncate">{i.description}</p>
                )}
              </div>
              <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-14 text-right whitespace-nowrap">
                {relativeTime(i.updated_at)}
              </span>
              <ChevronRight size={13} className="text-text-tertiary shrink-0" />
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
