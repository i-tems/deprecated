import { Link } from 'react-router-dom'
import { Layers, Target, ListTodo, Compass, Play, AlertCircle, FolderOpen, User, PauseCircle } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useFocus } from '@/contexts/FocusContext'
import { OwnerAvatar } from '@/components/OwnerAvatar'
import { StatusSelect } from '@/components/StatusSelect'
import { HoldBadge } from '@/components/HoldBadge'
import { CellBadge } from '@/components/CellBadge'
import { PriorityIcon, valueToLevel, PRIORITY_COLOR } from '@/components/PriorityPicker'
import { Empty } from '@/components/ui/empty'
import { IconButton } from '@/components/IconButton'
import { usePollingGate } from '@/hooks/usePollingGate'
import { useUrlState } from '@/hooks/useUrlState'
import { usePersistedState } from '@/hooks/usePersistedState'
import { appendCellTo } from '@/hooks/useCellAwareTo'
import { useToast } from '@/components/ui/toast'
import {
  issueListAll, issueUpdate,
  projectListAll, projectUpdate,
  initiativeListAll, initiativeUpdate,
} from '@/lib/api'
import { relativeTime, entityShortName, cn } from '@/lib/utils'
import {
  ISSUE_ATTENTION, projItems, repBy,
  type TriageItem,
} from '@/lib/triageQueue'
import {
  buildDecks, itemChanged, itemTriggers, deckFocusQueue,
  mkDeckCompare, DECK_THEMES, type Deck, type DeckTheme,
} from '@/lib/deck'
import { useCallback } from 'react'
import type { ReactNode, MouseEvent as ReactMouseEvent } from 'react'
import type { Project, Initiative, EntityStatus, ContainerStatus } from '@/lib/types'

/** Deck = triage 를 대체(흡수)한 attention surface. 봐야 할 항목을 주제/계보(Initiative lineage)로
 *  묶어 한 번에 한 덱만 펼쳐 맥락 전환을 최소화한다. (구 /triage 는 /deck 으로 리다이렉트.)
 *
 *  풀(M1+M3): triage(waiting/error) + 완료확인 트리거가 걸린 done 컨테이너.
 *  M2: 본 이후 변화(새 코멘트/상태전이)·신규 강조. M4: 중요도×긴급도 점수로
 *  덱 내 끌어올림 + 점수 분해 hover. 트리거·점수는 deck.ts 에서 프론트 계산. */

// 덱 종류 라벨 (선택 덱 헤더 태그).
const KIND_LABEL: Record<Deck['kind'], string> = {
  initiative: 'Initiative', standalone: '독립', type: '할 일', cell: '도메인', priority: '우선순위',
}

// 묶는 축(테마) 전환 — 같은 풀을 다른 기준으로 재그룹.
function ThemeSwitcher({ theme, onChange }: { theme: DeckTheme; onChange: (t: DeckTheme) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border border-border-subtle p-0.5">
      {DECK_THEMES.map((t) => (
        <button
          key={t.value}
          type="button"
          onClick={() => onChange(t.value)}
          className={cn(
            'text-xs px-2 py-0.5 rounded transition-colors',
            theme === t.value ? 'bg-bg-hover text-text font-medium' : 'text-text-tertiary hover:text-text',
          )}
        >{t.label}</button>
      ))}
    </div>
  )
}

export function DeckPanel() {
  const toast = useToast()
  const { user } = useAuth()
  const focus = useFocus()
  const [selectedKey, setSelectedKey] = useUrlState<string>('deck', '')
  const [theme, setTheme] = usePersistedState<DeckTheme>('deck:theme', 'initiative')
  const [mineOnly, setMineOnly] = usePersistedState('deck:mine', false)

  // useCallback 필수 — 인라인 fetcher 는 매 렌더 새 identity 라 usePolling effect 가
  // 매 렌더 재실행되며 무한 refetch 루프(hub stampede)를 만든다. 반응형 의존성 없음(모듈 상수뿐).
  const fetcher = useCallback(async () => {
    const [waitErr, allProjects, allInitiatives] = await Promise.all([
      issueListAll({ statuses: ISSUE_ATTENTION }),
      projectListAll({ limit: 1000 }),
      initiativeListAll({ limit: 1000 }),
    ])
    return {
      issues: waitErr.issues,
      allProjects: allProjects as Project[],
      allInitiatives: allInitiatives as Initiative[],
      now: Date.now(), // 트리거·점수의 기준 시각 — fetch 시점(렌더 밖)이라 render 순수성 유지, 폴링마다 갱신.
    }
  }, [])

  // user-level aggregate — SSE 불가, 5s 폴링 (triage 와 동일).
  const { data, refetch, setData, gate } = usePollingGate(fetcher, 5000)

  if (gate) return gate
  const { issues, allProjects, allInitiatives, now } = data!

  const userEmail = user?.email ?? null
  const compare = mkDeckCompare()
  const decks = buildDecks(issues, allProjects, allInitiatives, { mineOnly, userEmail, now, theme })

  // 선택 덱 — URL 의 deck key 가 유효하면 그것, 아니면 첫 덱. (해결돼 사라지면 자동 첫 덱으로 폴백.)
  const selected = decks.find((d) => d.key === selectedKey) ?? decks[0]

  const totalItems = decks.reduce((s, d) => s + d.items.length, 0)
  const totalWaiting = decks.reduce((s, d) => s + d.waiting, 0)
  const totalError = decks.reduce((s, d) => s + d.error, 0)
  const totalChanged = decks.reduce((s, d) => s + d.changed, 0)
  const subtitle = decks.length > 0
    ? [`${decks.length}개 덱`, `${totalItems}건`,
       totalWaiting > 0 && `${totalWaiting} 결정 대기`,
       totalChanged > 0 && `${totalChanged} 새 변화`,
       totalError > 0 && `${totalError} error`].filter(Boolean).join(' · ')
    : undefined

  // ── 상태 전이 (triage 와 동일 패턴: 낙관적 갱신 → capability → refetch) ─────────────
  const handleProjectTransition = async (projectId: string, status: ContainerStatus, cellId: string | undefined) => {
    setData((prev) => prev ? {
      ...prev,
      allProjects: prev.allProjects.map((g) => g.project_id === projectId ? { ...g, status } : g),
    } : prev)
    try {
      await projectUpdate({ project_id: projectId, status }, cellId ? { cellOverride: cellId } : undefined)
      refetch()
    } catch (e) {
      toast.error(`Project 상태 변경 실패: ${(e as Error).message}`)
      refetch()
    }
  }

  const handleInitiativeTransition = async (initiativeId: string, status: ContainerStatus, cellId: string | undefined) => {
    setData((prev) => prev ? {
      ...prev,
      allInitiatives: prev.allInitiatives.map((i) => i.initiative_id === initiativeId ? { ...i, status } : i),
    } : prev)
    try {
      await initiativeUpdate({ initiative_id: initiativeId, status }, cellId ? { cellOverride: cellId } : undefined)
      refetch()
    } catch (e) {
      toast.error(`Initiative 상태 변경 실패: ${(e as Error).message}`)
      refetch()
    }
  }

  const handleIssueTransition = async (issueId: string, status: EntityStatus, cellId: string | undefined) => {
    setData((prev) => prev ? {
      ...prev,
      issues: prev.issues.map((t) => t.issue_id === issueId ? { ...t, status } : t),
    } : prev)
    try {
      await issueUpdate({ issue_id: issueId, status }, cellId ? { cellOverride: cellId } : undefined)
      refetch()
    } catch (e) {
      toast.error(`Issue 상태 변경 실패: ${(e as Error).message}`)
      refetch()
    }
  }

  // 선택 덱을 한 건씩 처리(focus) — 점수순(deck.ordered) 그대로. 덱 풀은 트리거 항목(active/done)을
  // 포함하므로 triage-only 라이브 재구성(buildTriageQueue)과 안 맞아 스냅샷으로 둔다(params 생략).
  const startDeckFocus = () => {
    if (!selected) return
    const queue = deckFocusQueue(selected)
    if (queue.length) focus.start(queue)
  }

  const enterFocusAt = (e: ReactMouseEvent, pathname: string) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0 || !selected) return
    const queue = deckFocusQueue(selected)
    const idx = queue.findIndex((f) => f.pathname === pathname)
    if (idx < 0) return
    e.preventDefault()
    focus.start(queue, undefined, idx)
  }

  // ── 카드 렌더러 (triage 행과 동형 — 덱별 affordance 는 후속 마일스톤에서 분기) ──────────
  const renderCard = (item: TriageItem): ReactNode => {
    if (item.kind === 'project') {
      const g = item.project
      const level = valueToLevel(g.priority?.value)
      const shortName = entityShortName(g.project_id, g.cell_id, g.seq)
      return (
        <Link
          to={appendCellTo(`/projects/${g.project_id}`, g.cell_id ?? null) as string}
          onClick={(e) => enterFocusAt(e, `/projects/${g.project_id}`)}
          className="group flex items-center gap-2 px-2 py-1 rounded-md hover:bg-bg-hover transition-colors"
        >
          <Target size={13} className="shrink-0 text-project" />
          {g.cell_id && <CellBadge cellId={g.cell_id} />}
          <span className={`shrink-0 ${PRIORITY_COLOR[level]}`}><PriorityIcon level={level} size={13} /></span>
          <StatusSelect
            status={g.status}
            previousStatus={g.previous_status}
            onTransition={(s) => handleProjectTransition(g.project_id, s as ContainerStatus, g.cell_id)}
            iconSize={14}
            kind="container"
          />
          {g.hold && <HoldBadge />}
          {shortName && <span className="text-xs text-text-tertiary tabular-nums shrink-0">{shortName}</span>}
          <span className="text-sm truncate flex-1 min-w-0">{g.title}</span>
          <div className="shrink-0 w-5 flex justify-center">
            {g.resolved_owner ? <OwnerAvatar email={g.resolved_owner} size="xs" /> : null}
          </div>
          <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-14 text-right whitespace-nowrap">{relativeTime(g.updated_at)}</span>
        </Link>
      )
    }
    if (item.kind === 'initiative') {
      const i = item.initiative
      const level = valueToLevel(i.priority?.value)
      const shortName = entityShortName(i.initiative_id, i.cell_id, i.seq)
      return (
        <Link
          to={appendCellTo(`/initiatives/${i.initiative_id}`, i.cell_id ?? null) as string}
          onClick={(e) => enterFocusAt(e, `/initiatives/${i.initiative_id}`)}
          className="group flex items-center gap-2 px-2 py-1 rounded-md hover:bg-bg-hover transition-colors"
        >
          <Compass size={13} className="shrink-0 text-initiative" />
          {i.cell_id && <CellBadge cellId={i.cell_id} />}
          <span className={`shrink-0 ${PRIORITY_COLOR[level]}`}><PriorityIcon level={level} size={13} /></span>
          <StatusSelect
            status={i.status}
            onTransition={(s) => handleInitiativeTransition(i.initiative_id, s as ContainerStatus, i.cell_id)}
            iconSize={14}
            kind="container"
          />
          {i.hold && <HoldBadge />}
          {shortName && <span className="text-xs text-text-tertiary tabular-nums shrink-0">{shortName}</span>}
          <span className="text-sm truncate flex-1 min-w-0">
            {i.icon && <span className="mr-1.5">{i.icon}</span>}{i.name}
          </span>
          <div className="shrink-0 w-5 flex justify-center">
            {i.owner ? <OwnerAvatar email={i.owner} size="xs" /> : null}
          </div>
          <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-14 text-right whitespace-nowrap">{relativeTime(i.updated_at)}</span>
        </Link>
      )
    }
    const t = item.issue
    const level = valueToLevel(t.priority?.value)
    const shortName = entityShortName(t.issue_id, t.cell_id, t.seq)
    return (
      <Link
        to={appendCellTo(`/issues/${t.issue_id}`, t.cell_id ?? null) as string}
        onClick={(e) => enterFocusAt(e, `/issues/${t.issue_id}`)}
        className="group flex items-center gap-2 px-2 py-1 rounded-md hover:bg-bg-hover transition-colors"
      >
        <ListTodo size={13} className="shrink-0 text-issue" />
        {t.cell_id && <CellBadge cellId={t.cell_id} />}
        <span className={`shrink-0 ${PRIORITY_COLOR[level]}`}><PriorityIcon level={level} size={13} /></span>
        <StatusSelect
          status={t.status}
          previousStatus={t.previous_status}
          onTransition={(s) => handleIssueTransition(t.issue_id, s as EntityStatus, t.cell_id)}
          iconSize={14}
        />
        {t.hold && <HoldBadge />}
        {shortName && <span className="text-xs text-text-tertiary tabular-nums shrink-0">{shortName}</span>}
        <span className="text-sm truncate flex-1 min-w-0">{t.title}</span>
        <div className="shrink-0 w-5 flex justify-center">
          {t.resolved_owner ? <OwnerAvatar email={t.resolved_owner} size="xs" /> : null}
        </div>
        <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-14 text-right whitespace-nowrap">{relativeTime(t.updated_at)}</span>
      </Link>
    )
  }

  // Project 그룹 헤더 — 그 아래 Issue 들을 묶는 라벨. 흐림(opacity)이 아니라 헤더 타이포로
  // 구분해 stale 항목과 혼동되지 않게 한다 (작은 medium 라벨 + 폴더형 아이콘). 클릭은 유지.
  const renderProjectContext = (project: Project | undefined, fallbackId: string): ReactNode => {
    const cellId = project?.cell_id ?? null
    return (
      <Link
        to={appendCellTo(`/projects/${fallbackId}`, cellId) as string}
        className="group flex items-center gap-1.5 px-1.5 pt-2 pb-0.5 text-2xs font-medium tracking-wide text-text-tertiary hover:text-text-secondary transition-colors"
      >
        <FolderOpen size={11} className="shrink-0 text-project" />
        <span className="truncate">{project?.title ?? fallbackId}</span>
      </Link>
    )
  }

  return (
    <div className="space-y-2">
      {/* 패널 헤더 — 페이지 제목은 Workspace 가 갖고, 여기선 라벨 + 컨트롤만. */}
      <div className="flex items-center gap-2 px-1">
        <Layers size={15} className="shrink-0 text-accent" />
        <h2 className="text-sm font-medium shrink-0">지금 할 일</h2>
        {subtitle && <span className="text-xs text-text-tertiary truncate">{subtitle}</span>}
        <div className="flex-1" />
        <IconButton active={mineOnly} onClick={() => setMineOnly(!mineOnly)} icon={User} title="내 항목만" />
        <ThemeSwitcher theme={theme} onChange={setTheme} />
      </div>

      {decks.length === 0 || !selected ? (
        <Empty
          icon={<Layers size={20} />}
          title="덱 없음"
          description="봐야 할 항목이 없습니다 — waiting·error 항목과 완료확인 트리거가 걸린 Project·Initiative 가 주제별 덱으로 묶여 여기에 모입니다."
        />
      ) : (
        <div className="flex gap-4 items-start">
          {/* 덱 레일 — 한 번에 한 덱만 펼쳐 맥락 전환을 줄인다. 높이 상한(내부 스크롤). */}
          <div className="shrink-0 max-h-[58vh] overflow-y-auto">
            <DeckRail decks={decks} selectedKey={selected.key} onSelect={setSelectedKey} theme={theme} />
          </div>

          {/* 선택 덱 본문 */}
          <div className="flex-1 min-w-0 space-y-2">
            <div className="flex items-center gap-2 px-1">
              {(selected.kind === 'initiative' || selected.kind === 'standalone') && (
                <Compass size={15} className={cn('shrink-0', selected.kind === 'standalone' ? 'text-text-quaternary' : 'text-initiative')} />
              )}
              {selected.icon && <span className="text-base">{selected.icon}</span>}
              <h2 className="text-sm font-medium truncate">{selected.title}</h2>
              <span className="shrink-0 text-2xs px-1 py-px rounded border border-border-subtle text-text-tertiary">
                {KIND_LABEL[selected.kind]}
              </span>
              <span className="text-xs text-text-tertiary tabular-nums">{selected.items.length}건</span>
              <div className="flex-1" />
              <IconButton onClick={startDeckFocus} icon={Play} title="이 덱 한 건씩 처리" />
            </div>
            {/* 카드 목록만 높이 상한(내부 스크롤) — 덱 제목·컨트롤은 위에 고정. 항목 적으면 그만큼만. */}
            <div className="max-h-[55vh] overflow-y-auto pr-1">
              <DeckBody
                deck={selected}
                renderCard={renderCard}
                renderProjectContext={renderProjectContext}
                compare={compare}
                now={now}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// 덱 레일 — 덱 목록. 각 덱은 이름·건수, error 가 있으면 경고 표시. 선택 덱 강조.
function DeckRail({
  decks, selectedKey, onSelect, theme,
}: {
  decks: Deck[]
  selectedKey: string
  onSelect: (key: string) => void
  theme: DeckTheme
}) {
  const themeLabel = DECK_THEMES.find((t) => t.value === theme)?.label ?? ''
  return (
    <div className="w-56 shrink-0 space-y-0.5">
      {/* 묶는 기준(테마)을 명시. */}
      <div className="px-2.5 pb-1 text-2xs font-medium tracking-wide text-text-quaternary">덱 · {themeLabel}별</div>
      {decks.map((d) => {
        const active = d.key === selectedKey
        return (
          <button
            key={d.key}
            type="button"
            onClick={() => onSelect(d.key)}
            className={cn(
              'group w-full flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors text-left',
              active ? 'bg-bg-hover text-text font-medium' : 'text-text-secondary hover:bg-bg-hover hover:text-text',
            )}
          >
            {/* 주제(Initiative) 테마에서만 종류 아이콘 — 평탄 테마는 이름이 곧 기준. */}
            {(d.kind === 'initiative' || d.kind === 'standalone') && (
              <Compass size={13} className={cn('shrink-0', d.kind === 'standalone' ? 'text-text-quaternary' : 'text-initiative')} />
            )}
            {d.icon && <span className="shrink-0 text-sm leading-none">{d.icon}</span>}
            <span className="truncate flex-1 min-w-0">{d.title}</span>
            {d.waiting > 0 && (
              <span className="shrink-0 inline-flex items-center gap-0.5 text-2xs tabular-nums px-1 rounded-full bg-warning/15 text-warning" title="결정 대기 — 사람 판단 필요">
                <PauseCircle size={10} />{d.waiting}
              </span>
            )}
            {d.changed > 0 && (
              <span className="shrink-0 text-2xs tabular-nums px-1 rounded-full bg-accent/15 text-accent" title="본 이후 변화/신규">{d.changed}</span>
            )}
            {d.triggered > 0 && (
              <span className="shrink-0 text-2xs tabular-nums px-1 rounded-full bg-warning/15 text-warning" title="완료확인 등 트리거">{d.triggered}</span>
            )}
            {d.error > 0 && <AlertCircle size={13} className="shrink-0 text-danger" />}
            <span className="text-xs text-text-tertiary tabular-nums shrink-0">{d.items.length}</span>
          </button>
        )
      })}
    </div>
  )
}

// 덱 본문 — 선택 덱의 TopNode 를 점수순으로 펼쳐 카드로 렌더. Project 묶음 + Initiative 직속 Issue.
function DeckBody({
  deck, renderCard, renderProjectContext, compare, now,
}: {
  deck: Deck
  renderCard: (item: TriageItem) => ReactNode
  renderProjectContext: (project: Project | undefined, fallbackId: string) => ReactNode
  compare: (a: TriageItem, b: TriageItem) => number
  now: number
}) {
  const node = deck.node

  // M2: 본 이후 변화/신규는 좌측 점으로 강조.
  // M3: 트리거(완료확인) 배지.
  const card = (it: TriageItem): ReactNode => {
    const changed = itemChanged(it)
    const trigs = itemTriggers(it, now)
    return (
      <div className="flex items-stretch gap-1">
        <span className="w-1.5 shrink-0 flex items-center justify-center">
          {changed && <span className="h-1.5 w-1.5 rounded-full bg-accent" title="본 이후 변화/신규" />}
        </span>
        <div className="flex-1 min-w-0">{renderCard(it)}</div>
        {trigs.length > 0 && (
          <div className="shrink-0 flex items-center gap-1 pr-1">
            {trigs.map((t) => (
              <span
                key={t.kind}
                className="text-2xs px-1 rounded whitespace-nowrap bg-accent/15 text-accent"
              >{t.label}</span>
            ))}
          </div>
        )}
      </div>
    )
  }

  // 평탄 테마(할 일·도메인·우선순위) — Project 트리 없이 중요도순 카드 리스트.
  if (!node) {
    return (
      <section className="rounded-md border border-border-subtle/60 p-1.5 space-y-0.5">
        {deck.ordered.map((it) => (<div key={it.id}>{card(it)}</div>))}
      </section>
    )
  }

  // 주제(Initiative) 테마 — Project 트리 구조.
  const projectNodes = [...node.projects.values()].sort((a, b) => {
    const ra = repBy(projItems(a), compare), rb = repBy(projItems(b), compare)
    if (!ra) return 1
    if (!rb) return -1
    return compare(ra, rb)
  })
  const looseIssues = [...node.looseIssues].sort(compare)
  // 맥락 헤더는 read-state 대상이 아님 — 정렬만 맞추는 빈 거터.
  const ctxRow = (children: ReactNode): ReactNode => (
    <div className="flex items-stretch gap-1">
      <span className="w-1.5 shrink-0" />
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )

  return (
    <section className="rounded-md border border-border-subtle/60 p-1.5 space-y-0.5">
      {/* 덱 자체(Initiative)가 waiting 이면 그 자체도 처리 대상 카드 */}
      {node.self && <div>{card(node.self)}</div>}

      {/* Project 묶음 */}
      {projectNodes.map((p) => (
        <div key={p.projectId}>
          {p.self ? card(p.self) : ctxRow(renderProjectContext(p.project, p.projectId))}
          {p.issues.length > 0 && (
            <div className="ml-3 border-l border-border pl-2">
              {[...p.issues].sort(compare).map((it) => (
                <div key={it.id}>{card(it)}</div>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* Initiative 직속 (project 없는) Issue */}
      {looseIssues.map((it) => (
        <div key={it.id}>{card(it)}</div>
      ))}
    </section>
  )
}
