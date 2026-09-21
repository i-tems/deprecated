import type { Issue, Project, Initiative } from '@/lib/types'
import {
  STANDALONE,
  buildTriageItems, buildTriageTree, nodeItems, projItems, repBy, itemSnoozed, toFocusItem,
  type TriageItem, type TopNode,
} from '@/lib/triageQueue'
import type { FocusItem } from '@/contexts/FocusContext'

/**
 * 덱(Deck) = 사람이 한 맥락(headspace)으로 처리하는 묶음. 봐야 할 항목을 주제/계보
 * (Initiative lineage)로 묶되, 한 번에 한 덱만 보여 맥락 전환을 최소화한다.
 *
 * 풀(M1+M3): triage(waiting/error) + 완료확인 트리거가 걸린 done 컨테이너 — "안 막혔지만
 * 봐야 할 것". read-state(M2)로 본 이후 변화를 강조. 점수(M4)로 덱 내 끌어올림.
 *
 * 트리거·점수는 프론트에서 계산한다 — 이미 받아오는 데이터(전 status 컨테이너 + M2
 * derived 필드)로 충분해 hub 왕복이 불필요.
 */

export const DONE_CONFIRM_WINDOW_DAYS = 14 // done 후 이 기간 내 미확인만 덱에 올림 (오래된 done 제외)
const DAY_MS = 86_400_000

// 덱을 묶는 축(테마) — 상단 전환기로 고른다. 같은 풀을 다른 기준으로 재그룹.
export type DeckTheme = 'initiative' | 'type' | 'cell' | 'priority'
export const DECK_THEMES: { value: DeckTheme; label: string }[] = [
  { value: 'initiative', label: '주제' },
  { value: 'type', label: '할 일' },
  { value: 'cell', label: '도메인' },
  { value: 'priority', label: '우선순위' },
]

export interface Deck {
  /** 덱 식별자. initiative 테마면 TopNode.key(Initiative id/STANDALONE), 그 외엔 버킷 키. */
  key: string
  title: string
  icon?: string | null
  kind: 'initiative' | 'standalone' | DeckTheme
  initiative?: Initiative
  /** initiative 테마에서만 — Project 트리 렌더용. 그 외 테마는 평탄 카드 리스트(node 없음). */
  node?: TopNode
  /** 이 덱의 실제 처리 대상(맥락 헤더 제외). */
  items: TriageItem[]
  /** 표시·focus 큐 동일 순서 (중요도순). */
  ordered: TriageItem[]
  waiting: number
  error: number
  /** 본 이후 변화(새 코멘트/상태전이)·신규 항목 수 (read-state, M2). */
  changed: number
  /** 트리거(완료확인 등)가 걸린 항목 수 (M3). */
  triggered: number
}

// ── 엔티티 접근자 ──────────────────────────────────────────────────────────
const entityOf = (i: TriageItem): Issue | Project | Initiative =>
  i.kind === 'issue' ? i.issue : i.kind === 'project' ? i.project : i.initiative

const lastMovementTs = (e: Issue | Project | Initiative): string | null =>
  e.last_activity_ts || e.updated_at || null

function daysSince(ts: string | null, now: number): number {
  if (!ts) return 0
  const t = Date.parse(ts)
  return Number.isNaN(t) ? 0 : Math.max(0, Math.floor((now - t) / DAY_MS))
}

// read-state(M2) 접근자.
export const itemChanged = (i: TriageItem): boolean =>
  !!(i.kind === 'issue' ? i.issue.changed_since_view
    : i.kind === 'project' ? i.project.changed_since_view
    : i.initiative.changed_since_view)

export const itemViewed = (i: TriageItem): boolean =>
  !!(i.kind === 'issue' ? i.issue.last_viewed_at
    : i.kind === 'project' ? i.project.last_viewed_at
    : i.initiative.last_viewed_at)

// ── 트리거 (M3) ───────────────────────────────────────────────────────────
// "안 막혔지만 봐야 할" 컨테이너를 풀에 올리는 사유. Issue 는 waiting/error 로 이미
// 노출되므로 트리거는 컨테이너(Project/Initiative) 한정 — 완료 후 미확인이 본질.
// (무활동/정체 기준은 제거: active 컨테이너를 무전이 기간만으로 띄우지 않는다.)
export type TriggerKind = 'done_unconfirmed'
export interface Trigger { kind: TriggerKind; label: string }

export function itemTriggers(i: TriageItem, now: number): Trigger[] {
  if (i.kind === 'issue') return []
  const e = i.kind === 'project' ? i.project : i.initiative
  const out: Trigger[] = []
  if (e.status === 'done') {
    // 완료됐는데 내가 본 이후 그대로(=아직 확인 안 함)인 최근 done — rollout 확인 의무.
    if (itemChanged(i) && daysSince(lastMovementTs(e), now) <= DONE_CONFIRM_WINDOW_DAYS) {
      out.push({ kind: 'done_unconfirmed', label: '완료 확인' })
    }
  }
  return out
}

// triage 풀에 없는(=waiting 아님) 컨테이너 중 트리거가 걸린 것을 TriageItem 으로.
function buildTriggerItems(
  allProjects: Project[], allInitiatives: Initiative[],
  opts: { mineOnly: boolean; userEmail: string | null }, now: number,
): TriageItem[] {
  const mine = (owner?: string | null) => !opts.mineOnly || owner === opts.userEmail
  const out: TriageItem[] = []
  for (const g of allProjects) {
    if (g.status === 'waiting') continue // triage 풀이 처리
    const item: TriageItem = { kind: 'project', id: g.project_id, status: g.status, project: g }
    if (itemSnoozed(item) || !mine(g.resolved_owner)) continue
    if (itemTriggers(item, now).length) out.push(item)
  }
  for (const i of allInitiatives) {
    if (i.status === 'waiting') continue
    const item: TriageItem = { kind: 'initiative', id: i.initiative_id, status: i.status, initiative: i }
    if (itemSnoozed(item) || !mine(i.owner)) continue
    if (itemTriggers(item, now).length) out.push(item)
  }
  return out
}

// ── 랭크 (M4) ─────────────────────────────────────────────────────────────
// 정렬 = 중요도(priority) desc, 동률은 최신 활동순. "긴급도" 같은 파생 개념은 두지 않는다
// (사용자 결정 — status·정체기간 등에서 점수를 합성하지 않는다). 변화(M2)·트리거(M3)는
// 정렬이 아니라 좌측 점·배지로만 주의를 끈다.
function itemPriorityScore(i: TriageItem): number {
  const e = entityOf(i)
  if (typeof e.priority_score === 'number') return e.priority_score
  const v = e.priority?.value
  return v ? Math.round(((v - 1) / 4) * 100) : 0
}

export const mkDeckCompare = () =>
  (a: TriageItem, b: TriageItem): number => {
    const d = itemPriorityScore(b) - itemPriorityScore(a)
    if (d !== 0) return d
    return (lastMovementTs(entityOf(b)) || '').localeCompare(lastMovementTs(entityOf(a)) || '')
  }

// 덱(TopNode)을 화면 표시 순서 그대로 평탄화 — DeckBody 렌더 순서·focus 큐 동일.
function orderedDeckItems(node: TopNode, compare: (a: TriageItem, b: TriageItem) => number): TriageItem[] {
  const out: TriageItem[] = []
  if (node.self) out.push(node.self)
  const projs = [...node.projects.values()].sort((a, b) => {
    const ra = repBy(projItems(a), compare), rb = repBy(projItems(b), compare)
    if (!ra) return 1
    if (!rb) return -1
    return compare(ra, rb)
  })
  for (const p of projs) {
    if (p.self) out.push(p.self)
    for (const it of [...p.issues].sort(compare)) out.push(it)
  }
  for (const it of [...node.looseIssues].sort(compare)) out.push(it)
  return out
}

export const deckFocusQueue = (deck: Deck): FocusItem[] => deck.ordered.map(toFocusItem)

function toDeck(node: TopNode, now: number, compare: (a: TriageItem, b: TriageItem) => number): Deck {
  const items = nodeItems(node)
  const isStandalone = node.key === STANDALONE
  return {
    key: node.key,
    title: isStandalone ? '독립 (Initiative 없음)' : (node.initiative?.name ?? node.key),
    icon: isStandalone ? null : node.initiative?.icon ?? null,
    kind: isStandalone ? 'standalone' : 'initiative',
    initiative: node.initiative,
    node,
    items,
    ordered: orderedDeckItems(node, compare),
    waiting: items.filter((i) => i.status === 'waiting').length,
    error: items.filter((i) => i.status === 'error').length,
    changed: items.filter(itemChanged).length,
    triggered: items.filter((i) => itemTriggers(i, now).length > 0).length,
  }
}

// ── 테마별 버킷 (initiative 외) ─────────────────────────────────────────────
// 한 항목이 어느 덱에 속하는지 + 덱 정렬 순서(ord, 작을수록 앞).
function themeBucket(i: TriageItem, theme: DeckTheme, now: number): { key: string; title: string; ord: number } {
  if (theme === 'type') {
    if (i.status === 'error') return { key: 'error', title: '복구', ord: 0 }
    if (i.status === 'waiting') return { key: 'waiting', title: '결정 대기', ord: 1 }
    const tr = itemTriggers(i, now)
    if (tr.some((t) => t.kind === 'done_unconfirmed')) return { key: 'done', title: '완료 확인', ord: 2 }
    return { key: 'other', title: '기타', ord: 3 }
  }
  if (theme === 'cell') {
    const c = entityOf(i).cell_id || '미지정'
    return { key: c, title: c, ord: 0 } // 동률 → 건수·이름순 (아래)
  }
  // priority: value 1-5 → 구간. 높을수록 앞.
  const v = entityOf(i).priority?.value ?? 0
  const label = v >= 5 ? 'Urgent' : v === 4 ? 'High' : v === 3 ? 'Medium' : v === 2 ? 'Low' : 'None'
  return { key: `p${v}`, title: label, ord: -v }
}

const countsOf = (items: TriageItem[], now: number) => ({
  waiting: items.filter((i) => i.status === 'waiting').length,
  error: items.filter((i) => i.status === 'error').length,
  changed: items.filter(itemChanged).length,
  triggered: items.filter((i) => itemTriggers(i, now).length > 0).length,
})

function buildFlatDecks(all: TriageItem[], theme: DeckTheme, now: number, compare: (a: TriageItem, b: TriageItem) => number): Deck[] {
  const groups = new Map<string, { title: string; ord: number; items: TriageItem[] }>()
  for (const it of all) {
    const b = themeBucket(it, theme, now)
    let g = groups.get(b.key)
    if (!g) { g = { title: b.title, ord: b.ord, items: [] }; groups.set(b.key, g) }
    g.items.push(it)
  }
  const tuples = [...groups.entries()].map(([key, g]) => {
    const items = g.items
    return {
      ord: g.ord,
      deck: {
        key, title: g.title, icon: null, kind: theme,
        items, ordered: [...items].sort(compare), ...countsOf(items, now),
      } as Deck,
    }
  })
  // ord asc → 건수 desc → 이름. (cell 처럼 ord 동률인 경우 건수·이름으로 안정 정렬.)
  tuples.sort((a, b) => a.ord - b.ord || b.deck.items.length - a.deck.items.length || a.deck.title.localeCompare(b.deck.title))
  return tuples.map((t) => t.deck)
}

// triage 풀 + 트리거 컨테이너를 선택 테마로 묶는다.
export function buildDecks(
  issues: Issue[], allProjects: Project[], allInitiatives: Initiative[],
  opts: { mineOnly: boolean; userEmail: string | null; now: number; theme: DeckTheme },
): Deck[] {
  const triagePool = buildTriageItems(issues, allProjects, allInitiatives, opts)
  const triggerPool = buildTriggerItems(allProjects, allInitiatives, opts, opts.now)
  const all = [...triagePool, ...triggerPool]
  const compare = mkDeckCompare()

  if (opts.theme !== 'initiative') return buildFlatDecks(all, opts.theme, opts.now, compare)

  // 주제(Initiative) 테마 — Project 트리 구조 유지. buildTriageTree 는 그룹핑용(순서는 중요도로 재정렬).
  const topNodes = buildTriageTree(all, allProjects, allInitiatives, 'priority')
  const decks = topNodes.map((n) => toDeck(n, opts.now, compare))
  decks.sort((a, b) => {
    const ra = a.ordered[0], rb = b.ordered[0]
    if (!ra) return 1
    if (!rb) return -1
    return compare(ra, rb)
  })
  return decks
}
