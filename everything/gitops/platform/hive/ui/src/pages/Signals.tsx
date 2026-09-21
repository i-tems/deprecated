import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Radio, Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Empty } from '@/components/ui/empty'
import { Spinner } from '@/components/ui/spinner'
import { ErrorState } from '@/components/ErrorState'
import { PageHeader } from '@/components/PageHeader'
import { FilterTabs, type FilterTab } from '@/components/FilterTabs'
import { IconButton } from '@/components/IconButton'
import { SignalCard } from '@/components/SignalCard'
import { type SignalActionKey } from '@/components/SignalActions'
import { useUrlState } from '@/hooks/useUrlState'
import { useTitle } from '@/hooks/useTitle'
import { useToast } from '@/components/ui/toast'
import { signalList, signalGet, signalUpdateStatus, projectList, issueList } from '@/lib/api'
import type { Signal, SignalStatus, Project, Issue, EntityMap } from '@/lib/types'

type StatusTab = 'active' | 'done' | 'all'

const STATUS_TABS: FilterTab<StatusTab>[] = [
  { value: 'active', label: 'Active' },
  { value: 'done', label: 'Done' },
  { value: 'all', label: 'All' },
]

const ACTIVE_SIGNAL_STATUSES: SignalStatus[] = ['emitted']
const DONE_SIGNAL_STATUSES: SignalStatus[] = ['consumed', 'dismissed']
const ALL_SIGNAL_STATUSES: SignalStatus[] = [...ACTIVE_SIGNAL_STATUSES, ...DONE_SIGNAL_STATUSES]

const PAGE_SIZE = 30

function statusesForTab(tab: StatusTab): SignalStatus[] {
  if (tab === 'active') return ACTIVE_SIGNAL_STATUSES
  if (tab === 'done') return DONE_SIGNAL_STATUSES
  return ALL_SIGNAL_STATUSES
}

function isValidTab(v: string | null): v is StatusTab {
  return v === 'active' || v === 'done' || v === 'all'
}

function useReferencedEntities(signals: Signal[] | null) {
  const [entityMap, setEntityMap] = useState<EntityMap>({})

  useEffect(() => {
    if (!signals || signals.length === 0) return
    let cancelled = false

    const projectIds = new Set<string>()
    const issueIds = new Set<string>()
    for (const s of signals) {
      if (s.project_id && !entityMap[s.project_id]) projectIds.add(s.project_id)
      if (s.issue_id && !entityMap[s.issue_id]) issueIds.add(s.issue_id)
    }
    if (projectIds.size === 0 && issueIds.size === 0) return

    Promise.all([
      projectIds.size > 0 ? projectList({}).catch(() => [] as Project[]) : ([] as Project[]),
      issueIds.size > 0 ? issueList({}).then((r) => r.issues).catch(() => [] as Issue[]) : ([] as Issue[]),
    ]).then(([projects, issues]) => {
      if (cancelled) return
      const next: EntityMap = { ...entityMap }
      for (const g of projects) next[g.project_id] = { title: g.title, status: g.status }
      for (const t of issues) next[t.issue_id] = { title: t.title, status: t.status }
      setEntityMap(next)
    })

    return () => { cancelled = true }
    // entityMap 의존성을 빼지 않으면 매 fetch마다 무한 루프; signals만 추적
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signals])

  return entityMap
}

function matchesSearch(s: Signal, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    s.type.toLowerCase().includes(q) ||
    (s.title ?? '').toLowerCase().includes(q) ||
    (s.description ?? '').toLowerCase().includes(q)
  )
}

export default function Signals() {
  useTitle('Signals')
  const toast = useToast()
  const [rawTab, setTab] = useUrlState<StatusTab>('tab', 'active')
  // 이전 URL 의 ?tab=emitted 같은 값 fallback
  const tab: StatusTab = isValidTab(rawTab) ? rawTab : 'active'
  const [search, setSearch] = useState('')
  const [showSearch, setShowSearch] = useState(false)

  // ?focus=<signal_id> deeplink (Slack inbox 등에서 진입). 현재 탭 결과에 없으면
  // 단건 fetch 해 리스트 위에 prepend 강조. 있으면 highlight + scrollIntoView.
  const [searchParams, setSearchParams] = useSearchParams()
  const focusId = searchParams.get('focus')
  const [focusSignal, setFocusSignal] = useState<Signal | null>(null)
  const [focusError, setFocusError] = useState<string | null>(null)
  const focusRef = useRef<HTMLElement | null>(null)

  const [signals, setSignals] = useState<Signal[] | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  // tab/refresh 변경 시 reset + 첫 페이지 fetch
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setSignals(null)
    setNextCursor(null)
    setError(null)
    signalList({ statuses: statusesForTab(tab), limit: PAGE_SIZE })
      .then((res) => {
        if (cancelled) return
        setSignals(res.signals)
        setNextCursor(res.next_cursor)
        setLoading(false)
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e)
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [tab, refreshKey])

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const res = await signalList({ statuses: statusesForTab(tab), limit: PAGE_SIZE, cursor: nextCursor })
      setSignals((prev) => [...(prev ?? []), ...res.signals])
      setNextCursor(res.next_cursor)
    } catch (e) {
      toast.error(`Signal 추가 로드 실패: ${(e as Error).message}`)
    } finally {
      setLoadingMore(false)
    }
  }, [nextCursor, loadingMore, tab, toast])

  // IntersectionObserver — sentinel 이 보이면 다음 페이지 fetch
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const node = sentinelRef.current
    if (!node) return
    const observer = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) loadMore() },
      { rootMargin: '300px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [loadMore])

  // focus signal 단건 fetch — 리스트 결과와는 별도. signal_id 가 바뀌면 재요청.
  useEffect(() => {
    if (!focusId) {
      setFocusSignal(null)
      setFocusError(null)
      return
    }
    let cancelled = false
    setFocusError(null)
    signalGet(focusId)
      .then((sig) => { if (!cancelled) setFocusSignal(sig) })
      .catch((e: Error) => {
        if (cancelled) return
        setFocusSignal(null)
        setFocusError(e.message)
      })
    return () => { cancelled = true }
  }, [focusId])

  // focus 카드가 마운트되면 스크롤. signals/focusSignal 어느 쪽이든 ref 가 잡힌 후 실행.
  useEffect(() => {
    if (!focusId) return
    const node = focusRef.current
    if (!node) return
    node.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focusId, focusSignal, signals])

  // 리스트에서 focus signal 찾기 (있으면 그 자리에서 highlight, 별도 prepend 안 함)
  const focusInList = useMemo(() => {
    if (!focusId || !signals) return false
    return signals.some((s) => s.signal_id === focusId)
  }, [focusId, signals])

  const clearFocus = useCallback(() => {
    const next = new URLSearchParams(searchParams)
    next.delete('focus')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const entityMap = useReferencedEntities(signals)

  const handleAction = async (id: string, status: SignalActionKey) => {
    try {
      const updated = await signalUpdateStatus({ signal_id: id, status, note: `Manual ${status} from console` })
      // 현재 탭의 status 필터에서 벗어나면 목록에서 제거, 아니면 항목 교체.
      const allowed = new Set(statusesForTab(tab))
      setSignals((prev) => {
        if (!prev) return prev
        if (!allowed.has(updated.status)) return prev.filter((s) => s.signal_id !== id)
        return prev.map((s) => (s.signal_id === id ? updated : s))
      })
    } catch (e) {
      toast.error(`Signal 업데이트 실패: ${(e as Error).message}`)
    }
  }

  if (loading) return <Spinner />
  if (error) return <ErrorState error={error} onRetry={() => setRefreshKey((n) => n + 1)} />

  const visible = (signals ?? []).filter((s) => matchesSearch(s, search))

  return (
    <div className="space-y-3">
      <PageHeader
        title="Signals"
        icon={Radio}
        iconClass="text-signal"
      />

      <FilterTabs
        value={tab}
        onChange={setTab}
        tabs={STATUS_TABS}
        trailing={
          <IconButton active={showSearch} onClick={() => setShowSearch((v) => !v)} icon={Search} title="검색" />
        }
      />

      {showSearch && (
        <div className="px-1">
          <Input
            placeholder="Filter by type, title, reason..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            className="w-full"
          />
        </div>
      )}

      {focusId && (focusError || (focusSignal && !focusInList)) && (
        <div className="space-y-2">
          {focusError ? (
            <div className="rounded-lg border border-border-subtle bg-bg-subtle px-4 py-3 text-sm text-text-tertiary">
              <div className="flex items-center justify-between gap-2">
                <span>
                  <span className="font-mono text-text-secondary">{focusId}</span> 를 찾지 못했습니다 — {focusError}
                </span>
                <button onClick={clearFocus} className="text-xs underline hover:text-text">닫기</button>
              </div>
            </div>
          ) : focusSignal ? (
            <div className="space-y-1">
              <div className="flex items-center justify-between px-1 text-xs text-text-tertiary">
                <span>Focused signal · 현재 탭에 없음</span>
                <button onClick={clearFocus} className="underline hover:text-text">닫기</button>
              </div>
              <SignalCard
                ref={focusRef}
                signal={focusSignal}
                entityMap={entityMap}
                onAction={(key) => handleAction(focusSignal.signal_id, key)}
                highlighted
              />
            </div>
          ) : null}
        </div>
      )}

      {visible.length === 0 ? (
        <Empty icon={<Radio size={20} />} title="시그널 없음" />
      ) : (
        <div className="space-y-3">
          {visible.map((s) => (
            <SignalCard
              key={s.signal_id}
              ref={s.signal_id === focusId ? focusRef : undefined}
              signal={s}
              entityMap={entityMap}
              onAction={(key) => handleAction(s.signal_id, key)}
              highlighted={s.signal_id === focusId}
            />
          ))}
          <div ref={sentinelRef} className="h-1" />
          {loadingMore && (
            <div className="flex justify-center py-2">
              <Spinner />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
