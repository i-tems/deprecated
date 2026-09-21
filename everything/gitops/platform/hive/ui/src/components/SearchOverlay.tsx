import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { relativeTime } from '@/lib/utils'
import {
  issueListAll,
  projectListAll,
  initiativeListAll,
  signalListAll,
} from '@/lib/api'
import type { Issue, Project, Initiative, Signal } from '@/lib/types'
import {
  ACTION_GROUPS,
  buildActionContext,
  filterActions,
  type Action,
  type ActionGroup,
} from '@/lib/actions'
import { StatusIcon } from '@/components/StatusIcon'
import { InitiativeStatusIcon } from '@/components/InitiativeStatusIcon'
import { CellBadge } from '@/components/CellBadge'

type Tab = 'all' | 'actions' | 'issues' | 'projects' | 'initiatives' | 'signals'

const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'actions', label: 'Actions' },
  { key: 'issues', label: 'Issues' },
  { key: 'projects', label: 'Projects' },
  { key: 'initiatives', label: 'Initiatives' },
  { key: 'signals', label: 'Signals' },
]

interface Results {
  issues: Issue[]
  projects: Project[]
  initiatives: Initiative[]
  signals: Signal[]
}

const EMPTY_RESULTS: Results = { issues: [], projects: [], initiatives: [], signals: [] }

interface Props {
  open: boolean
  onClose: () => void
}

// ⌘K Linear 식 커맨드 팔레트. 한 입력창에서 (1) 액션(상태 변경·페이지 이동·도움말 등)을
// substring 으로 찾아 Enter 로 실행하고 (2) issue/project/initiative/signal 검색도 같이
// 노출한다. 액션은 라우트로 가용성이 결정되고, 검색은 200ms 디바운스 후 4 타입 병렬
// fetch. ↑↓ 로 항목 이동, Enter 로 실행/이동, Esc 로 닫기.
export function SearchOverlay({ open, onClose }: Props) {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [tab, setTab] = useState<Tab>('all')
  const [results, setResults] = useState<Results>(EMPTY_RESULTS)
  const [loading, setLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const location = useLocation()

  const actionCtx = useMemo(
    () => buildActionContext(location.pathname, navigate),
    [location.pathname, navigate],
  )

  // open 시 입력 focus + 상태 초기화. 검색 후 재오픈에도 깨끗한 상태.
  useEffect(() => {
    if (open) {
      setQ('')
      setDebouncedQ('')
      setResults(EMPTY_RESULTS)
      setTab('all')
      setActiveIndex(0)
      const t = setTimeout(() => inputRef.current?.focus(), 0)
      return () => clearTimeout(t)
    }
  }, [open])

  // Esc 로 닫기.
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // 디바운스 — 마지막 입력 후 200ms.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 200)
    return () => clearTimeout(t)
  }, [q])

  // q 변경 시 4 타입 병렬 fetch. 빈 쿼리면 결과 비우고 호출 생략.
  useEffect(() => {
    if (!open) return
    if (!debouncedQ) {
      setResults(EMPTY_RESULTS)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    const params = { q: debouncedQ, limit: 20 }
    Promise.allSettled([
      issueListAll(params),
      projectListAll(params),
      initiativeListAll(params),
      signalListAll(params),
    ]).then((res) => {
      if (cancelled) return
      setResults({
        issues: res[0].status === 'fulfilled' ? res[0].value.issues : [],
        projects: res[1].status === 'fulfilled' ? res[1].value : [],
        initiatives: res[2].status === 'fulfilled' ? res[2].value : [],
        signals: res[3].status === 'fulfilled' ? res[3].value.signals : [],
      })
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [debouncedQ, open])

  // 현재 q (디바운스 X) 기준 액션 — 입력하자마자 반응한다.
  const actions = useMemo(() => filterActions(q, actionCtx), [q, actionCtx])

  // 키보드 nav 를 위한 평탄화 항목 목록. tab 별로 다르게 구성.
  type Item =
    | { kind: 'action'; action: Action }
    | { kind: 'issue'; entity: Issue }
    | { kind: 'project'; entity: Project }
    | { kind: 'initiative'; entity: Initiative }
    | { kind: 'signal'; entity: Signal }

  const items = useMemo<Item[]>(() => {
    const out: Item[] = []
    const showActions = tab === 'all' || tab === 'actions'
    const showIssues = tab === 'all' || tab === 'issues'
    const showProjects = tab === 'all' || tab === 'projects'
    const showInitiatives = tab === 'all' || tab === 'initiatives'
    const showSignals = tab === 'all' || tab === 'signals'
    if (showActions) for (const a of actions) out.push({ kind: 'action', action: a })
    if (showIssues) for (const e of results.issues) out.push({ kind: 'issue', entity: e })
    if (showProjects) for (const e of results.projects) out.push({ kind: 'project', entity: e })
    if (showInitiatives) for (const e of results.initiatives) out.push({ kind: 'initiative', entity: e })
    if (showSignals) for (const e of results.signals) out.push({ kind: 'signal', entity: e })
    return out
  }, [tab, actions, results])

  // 사용자가 입력·탭을 바꾸면 activeIndex 는 input/tab 핸들러에서 0 으로 리셋.
  // items 길이가 줄어도 render 단계에서 안전 clamp.
  const effectiveIndex = items.length === 0 ? 0 : Math.min(activeIndex, items.length - 1)

  // active 항목으로 스크롤.
  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-idx="${effectiveIndex}"]`)
    node?.scrollIntoView({ block: 'nearest' })
  }, [effectiveIndex])

  const totalCount = results.issues.length + results.projects.length + results.initiatives.length + results.signals.length

  const onPick = useCallback((path: string, cellId?: string) => {
    const target = cellId ? `${path}?cell=${cellId}` : path
    navigate(target)
    onClose()
  }, [navigate, onClose])

  const runItem = useCallback((item: Item) => {
    switch (item.kind) {
      case 'action':
        item.action.perform(actionCtx)
        onClose()
        return
      case 'issue':
        onPick(`/issues/${item.entity.issue_id}`, item.entity.cell_id)
        return
      case 'project':
        onPick(`/projects/${item.entity.project_id}`, item.entity.cell_id)
        return
      case 'initiative':
        onPick(`/initiatives/${item.entity.initiative_id}`, item.entity.cell_id)
        return
      case 'signal':
        onPick('/signals', item.entity.cell_id)
        return
    }
  }, [actionCtx, onClose, onPick])

  // input 위 ↑↓ Enter intercept — 다른 키는 input 이 처리.
  const onInputKey = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((i) => (items.length === 0 ? 0 : Math.min(i + 1, items.length - 1)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter') {
      const item = items[Math.min(activeIndex, items.length - 1)]
      if (item) { e.preventDefault(); runItem(item) }
    }
  }, [items, activeIndex, runItem])

  if (!open) return null

  return (
    <>
      {/* 클릭 시 닫힘 backdrop — 결과 영역과 분리해 검색 UI 외부 클릭 = 닫기. */}
      <div
        className="fixed inset-0 z-30 md:left-[var(--sidebar-w,244px)] bg-bg/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="fixed top-0 z-40 left-0 right-0 md:left-[var(--sidebar-w,244px)] bg-bg border-b border-border flex flex-col max-h-[calc(100vh-1rem)]"
        role="dialog"
        aria-label="커맨드 메뉴"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input row */}
        <div className="flex items-center gap-2 px-4 md:px-6 h-12 border-b border-border-subtle">
          <Search size={14} className="text-text-tertiary shrink-0" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => { setQ(e.target.value); setActiveIndex(0) }}
            onKeyDown={onInputKey}
            placeholder="액션 또는 issue/project/initiative/signal 검색..."
            aria-label="커맨드"
            spellCheck={false}
            autoComplete="off"
            className="flex-1 bg-transparent text-sm placeholder:text-text-tertiary outline-none"
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-text-tertiary hover:bg-bg-hover hover:text-text transition-colors"
            aria-label="닫기"
          >
            <X size={16} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 px-4 md:px-6 py-2 border-b border-border-subtle overflow-x-auto">
          {TABS.map((t) => {
            const count = countFor(t.key, results, actions.length)
            const active = tab === t.key
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => { setTab(t.key); setActiveIndex(0) }}
                className={cn(
                  'rounded-full px-3 py-1 text-sm transition-colors shrink-0',
                  active
                    ? 'bg-bg-hover text-text font-medium'
                    : 'text-text-secondary hover:bg-bg-hover hover:text-text',
                )}
              >
                {t.label}
                {count > 0 && (
                  <span className="ml-1.5 text-text-tertiary text-xs">{count}</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Results */}
        <div ref={listRef} className="flex-1 overflow-y-auto">
          {items.length === 0 ? (
            !debouncedQ && actions.length === 0 ? (
              <EmptyHint />
            ) : loading && totalCount === 0 ? (
              <LoadingHint />
            ) : (
              <NoResults q={debouncedQ} />
            )
          ) : (
            <ResultsList
              tab={tab}
              actions={actions}
              results={results}
              activeIndex={effectiveIndex}
              onActivate={setActiveIndex}
              onRun={runItem}
            />
          )}
        </div>
      </div>
    </>
  )
}

function countFor(tab: Tab, r: Results, actionCount: number): number {
  if (tab === 'all') return actionCount + r.issues.length + r.projects.length + r.initiatives.length + r.signals.length
  if (tab === 'actions') return actionCount
  if (tab === 'issues') return r.issues.length
  if (tab === 'projects') return r.projects.length
  if (tab === 'initiatives') return r.initiatives.length
  return r.signals.length
}

function EmptyHint() {
  return (
    <div className="px-6 py-10 text-sm text-text-tertiary">
      <p>액션 이름을 입력하거나(예: <code className="px-1 rounded bg-bg-subtle">상태</code>, <code className="px-1 rounded bg-bg-subtle">이동</code>) 제목·ID 의 일부를 입력하세요.</p>
    </div>
  )
}

function LoadingHint() {
  return (
    <div className="px-6 py-10 text-sm text-text-tertiary">검색 중...</div>
  )
}

function NoResults({ q }: { q: string }) {
  return (
    <div className="px-6 py-10 text-sm text-text-tertiary">
      "{q}" 에 해당하는 항목이 없습니다.
    </div>
  )
}

interface RowsProps {
  tab: Tab
  actions: Action[]
  results: Results
  activeIndex: number
  onActivate: (i: number) => void
  onRun: (item:
    | { kind: 'action'; action: Action }
    | { kind: 'issue'; entity: Issue }
    | { kind: 'project'; entity: Project }
    | { kind: 'initiative'; entity: Initiative }
    | { kind: 'signal'; entity: Signal }
  ) => void
}

function ResultsList({ tab, actions, results, activeIndex, onActivate, onRun }: RowsProps) {
  let idx = 0
  return (
    <div className="py-2">
      {(tab === 'all' || tab === 'actions') && actions.length > 0 && (
        ACTION_GROUPS.filter((g) => actions.some((a) => a.group === g)).map((group) => (
          <Section key={group} label={group}>
            {actions.filter((a) => a.group === group).map((a) => {
              const i = idx++
              return (
                <ActionRow
                  key={a.id}
                  action={a}
                  active={i === activeIndex}
                  index={i}
                  onMouseEnter={() => onActivate(i)}
                  onClick={() => onRun({ kind: 'action', action: a })}
                />
              )
            })}
          </Section>
        ))
      )}
      {(tab === 'all' || tab === 'issues') && results.issues.length > 0 && (
        <Section label="Issues">
          {results.issues.map((t) => {
            const i = idx++
            return (
              <IssueRow
                key={t.issue_id}
                issue={t}
                active={i === activeIndex}
                index={i}
                onMouseEnter={() => onActivate(i)}
                onClick={() => onRun({ kind: 'issue', entity: t })}
              />
            )
          })}
        </Section>
      )}
      {(tab === 'all' || tab === 'projects') && results.projects.length > 0 && (
        <Section label="Projects">
          {results.projects.map((g) => {
            const i = idx++
            return (
              <ProjectRow
                key={g.project_id}
                project={g}
                active={i === activeIndex}
                index={i}
                onMouseEnter={() => onActivate(i)}
                onClick={() => onRun({ kind: 'project', entity: g })}
              />
            )
          })}
        </Section>
      )}
      {(tab === 'all' || tab === 'initiatives') && results.initiatives.length > 0 && (
        <Section label="Initiatives">
          {results.initiatives.map((it) => {
            const i = idx++
            return (
              <InitiativeRow
                key={it.initiative_id}
                initiative={it}
                active={i === activeIndex}
                index={i}
                onMouseEnter={() => onActivate(i)}
                onClick={() => onRun({ kind: 'initiative', entity: it })}
              />
            )
          })}
        </Section>
      )}
      {(tab === 'all' || tab === 'signals') && results.signals.length > 0 && (
        <Section label="Signals">
          {results.signals.map((s) => {
            const i = idx++
            return (
              <SignalRow
                key={s.signal_id}
                signal={s}
                active={i === activeIndex}
                index={i}
                onMouseEnter={() => onActivate(i)}
                onClick={() => onRun({ kind: 'signal', entity: s })}
              />
            )
          })}
        </Section>
      )}
    </div>
  )
}

function Section({ label, children }: { label: string | ActionGroup; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="px-6 pt-2 pb-1 text-xs font-medium text-text-tertiary">{label}</div>
      <div>{children}</div>
    </div>
  )
}

interface RowProps {
  index: number
  active: boolean
  onMouseEnter: () => void
  onClick: () => void
}

function ActionRow({ action, active, index, onMouseEnter, onClick }: RowProps & { action: Action }) {
  const Icon = action.icon
  return (
    <button
      type="button"
      data-idx={index}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-3 px-6 py-1.5 text-sm transition-colors text-left',
        active ? 'bg-bg-hover' : 'hover:bg-bg-hover',
      )}
    >
      <span className="shrink-0 text-text-tertiary w-4 flex items-center justify-center">
        {Icon ? <Icon size={14} /> : null}
      </span>
      <span className="flex-1 truncate text-text">{action.label}</span>
      {action.hint && (
        <kbd className="px-1.5 py-0.5 rounded border border-border bg-bg-subtle text-xs font-mono text-text-tertiary shrink-0">
          {action.hint}
        </kbd>
      )}
    </button>
  )
}

function Row({
  id,
  cellId,
  title,
  icon,
  updatedAt,
  active,
  index,
  onMouseEnter,
  onClick,
}: RowProps & {
  id: string
  cellId?: string
  title: string
  icon: React.ReactNode
  updatedAt?: string
}) {
  return (
    <button
      type="button"
      data-idx={index}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-3 px-6 py-1.5 text-sm transition-colors text-left',
        active ? 'bg-bg-hover' : 'hover:bg-bg-hover',
      )}
    >
      <span className="text-xs text-text-tertiary w-32 truncate shrink-0">{id}</span>
      <span className="shrink-0">{icon}</span>
      <span className="flex-1 truncate text-text">{title}</span>
      {cellId && <CellBadge cellId={cellId} />}
      {updatedAt && (
        <span className="text-xs text-text-tertiary shrink-0">{relativeTime(updatedAt)}</span>
      )}
    </button>
  )
}

function IssueRow({ issue, ...rest }: RowProps & { issue: Issue }) {
  return (
    <Row
      {...rest}
      id={issue.issue_id}
      cellId={issue.cell_id}
      title={issue.title}
      icon={<StatusIcon status={issue.status} size={14} />}
      updatedAt={issue.updated_at}
    />
  )
}

function ProjectRow({ project, ...rest }: RowProps & { project: Project }) {
  return (
    <Row
      {...rest}
      id={project.project_id}
      cellId={project.cell_id}
      title={project.title}
      icon={<StatusIcon status={project.status} size={14} kind="container" />}
      updatedAt={project.updated_at}
    />
  )
}

function InitiativeRow({ initiative, ...rest }: RowProps & { initiative: Initiative }) {
  return (
    <Row
      {...rest}
      id={initiative.initiative_id}
      cellId={initiative.cell_id}
      title={initiative.name}
      icon={<InitiativeStatusIcon status={initiative.status} size={14} />}
      updatedAt={initiative.updated_at}
    />
  )
}

function SignalRow({ signal, ...rest }: RowProps & { signal: Signal }) {
  // signal 은 detail 페이지가 없어 cell signals 리스트로 이동, query 에 signal id 부착.
  return (
    <Row
      {...rest}
      id={signal.signal_id}
      cellId={signal.cell_id}
      title={signal.title || signal.description || signal.type}
      icon={<span className="inline-block w-2 h-2 rounded-full bg-accent" aria-hidden />}
      updatedAt={signal.ts_emitted}
    />
  )
}
