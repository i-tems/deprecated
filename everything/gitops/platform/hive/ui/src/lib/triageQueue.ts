import { appendCellTo } from '@/hooks/useCellAwareTo'
import { isSnoozeActive } from '@/lib/snooze'
import type { Project, Issue, Initiative, EntityStatus, ContainerStatus } from '@/lib/types'
import type { FocusItem } from '@/contexts/FocusContext'

/**
 * Triage 큐의 순수 로직 — 필터(waiting/error·mine·tab) → Initiative ▸ Project 트리 → 정렬 → 평탄화.
 * Triage 페이지(트리 렌더)와 focus 큐의 라이브 재구성이 같은 순서를 쓰도록 한 곳에 둔다.
 *
 * 큐 멤버십 = worker 가 자동으로 가져가지 *않는* 항목. waiting 항목에 미응답 사용자 코멘트가
 * 있으면 work_finder 가 곧 픽업하므로(사람이 이미 답함) 큐에서 뺀다(`workerWillPickup`).
 * hold 항목은 worker 가 픽업하지 않으므로(차단) 그냥 status 대로 큐에 남는다 — 별도 구분 없음
 * (held 여부는 행의 HoldBadge 로 표시).
 */

export const ISSUE_ATTENTION: EntityStatus[] = ['waiting', 'error']
const CONTAINER_TERMINAL: ContainerStatus[] = ['done', 'archive']
export const STANDALONE = '__standalone__'

export type TabValue = 'all' | 'waiting' | 'error'
export type SortMode = 'priority' | 'updated' | 'waiting' | 'created'

export type TriageItem =
  | { kind: 'project'; id: string; status: ContainerStatus; project: Project }
  | { kind: 'initiative'; id: string; status: ContainerStatus; initiative: Initiative }
  | { kind: 'issue'; id: string; status: EntityStatus; issue: Issue }

export const itemHold = (i: TriageItem): boolean =>
  i.kind === 'issue' ? !!i.issue.hold : i.kind === 'project' ? !!i.project.hold : !!i.initiative.hold

// snooze: metadata.snooze_until 이 미래 시각이면 큐에서 시한부로 숨김. 만료 항목은
// 다음 폴링 사이클에서 자동 복귀 (read 시점 판정). hold 와 직교.
// Initiative 는 hub-side metadata 미보유 — 이 가설 단계에서는 Issue/Project 만 지원.
export const itemSnoozed = (i: TriageItem): boolean =>
  i.kind === 'initiative' ? false
    : isSnoozeActive(i.kind === 'issue' ? i.issue.metadata : i.project.metadata)

// 미응답 사용자 코멘트 존재 — work_finder 가 waiting 픽업 판정에 쓰는 바로 그 필드.
const itemPending = (i: TriageItem): boolean => {
  const ids = i.kind === 'issue' ? i.issue.pending_user_comment_event_ids
    : i.kind === 'project' ? i.project.pending_user_comment_event_ids
    : i.initiative.pending_user_comment_event_ids
  return (ids?.length ?? 0) > 0
}

// worker 가 곧 자동 픽업할 항목 = waiting + 미응답 사용자 코멘트 + hold 아님 (hold 면 픽업 차단).
// error 는 worker 가 픽업하지 않으므로 항상 false.
export const workerWillPickup = (i: TriageItem): boolean =>
  !itemHold(i) && i.status === 'waiting' && itemPending(i)

const itemUpdatedAt = (i: TriageItem): string =>
  i.kind === 'issue' ? i.issue.updated_at : i.kind === 'project' ? i.project.updated_at : i.initiative.updated_at

const itemCreatedAt = (i: TriageItem): string =>
  i.kind === 'issue' ? i.issue.created_at : i.kind === 'project' ? i.project.created_at : i.initiative.created_at

const itemPriority = (i: TriageItem): number =>
  (i.kind === 'issue' ? i.issue.priority?.value
    : i.kind === 'project' ? i.project.priority?.value
    : i.initiative.priority?.value) ?? 0

// focus 큐 항목용 — 상세 라우트(pathname)·cell·표시 제목.
const itemRoute = (i: TriageItem): { path: string; cellId: string | null; title: string } =>
  i.kind === 'issue' ? { path: `/issues/${i.issue.issue_id}`, cellId: i.issue.cell_id ?? null, title: i.issue.title }
  : i.kind === 'project' ? { path: `/projects/${i.project.project_id}`, cellId: i.project.cell_id ?? null, title: i.project.title }
  : { path: `/initiatives/${i.initiative.initiative_id}`, cellId: i.initiative.cell_id ?? null, title: i.initiative.name }

export const toFocusItem = (i: TriageItem): FocusItem => {
  const { path, cellId, title } = itemRoute(i)
  return { to: appendCellTo(path, cellId) as string, pathname: path, label: title }
}

// 두 triage 항목 비교 — 음수면 a 가 앞. priority: 높은 값 우선(동률은 최근 업데이트 tie-break),
// updated: 최신 우선, waiting: 가장 오래 업데이트 안 된 것 우선, created: 최근 생성 우선.
export const compareItems = (a: TriageItem, b: TriageItem, mode: SortMode): number => {
  switch (mode) {
    case 'priority': {
      const d = itemPriority(b) - itemPriority(a)
      return d !== 0 ? d : itemUpdatedAt(b).localeCompare(itemUpdatedAt(a))
    }
    case 'updated': return itemUpdatedAt(b).localeCompare(itemUpdatedAt(a))
    case 'waiting': return itemUpdatedAt(a).localeCompare(itemUpdatedAt(b))
    case 'created': return itemCreatedAt(b).localeCompare(itemCreatedAt(a))
  }
}

// 묶음의 "대표 항목" = 그 기준으로 가장 앞서는 항목. 그룹·Project 간 순서를 이 대표로 정한다.
export const repBy = (items: TriageItem[], compare: (a: TriageItem, b: TriageItem) => number): TriageItem | undefined =>
  items.length ? items.reduce((best, x) => (compare(x, best) < 0 ? x : best)) : undefined

// 트리 노드: ProjNode = (Project 헤더 + 그 아래 triage Issue 들), TopNode = (Initiative 헤더 + Project 들 + 직속 Issue 들)
export interface ProjNode { projectId: string; project?: Project; self?: TriageItem; issues: TriageItem[] }
export interface TopNode { key: string; initiative?: Initiative; self?: TriageItem; projects: Map<string, ProjNode>; looseIssues: TriageItem[] }

// 정렬 대표 계산용 — 묶음에 속한 실제 triage 항목들(맥락 헤더 제외)을 평면으로 모은다.
export const projItems = (p: ProjNode): TriageItem[] => (p.self ? [p.self, ...p.issues] : [...p.issues])
export const nodeItems = (n: TopNode): TriageItem[] => {
  const out: TriageItem[] = []
  if (n.self) out.push(n.self)
  for (const p of n.projects.values()) out.push(...projItems(p))
  out.push(...n.looseIssues)
  return out
}

const isProjTriage = (p: Project): boolean =>
  p.status === 'waiting' && !CONTAINER_TERMINAL.includes(p.status)
const isInitTriage = (i: Initiative): boolean =>
  i.status === 'waiting' && !CONTAINER_TERMINAL.includes(i.status)

export interface QueueParams {
  sort: SortMode
  mineOnly: boolean
  tab: TabValue
  userEmail: string | null
  /** 덱 단위 focus — 지정 시 라이브 재구성을 그 덱(Initiative lineage key)으로 한정한다.
   *  Triage 의 전역 focus 는 이 값을 비워 전체 큐를 재구성한다. (정본 묶음 키 = TopNode.key) */
  deckKey?: string
}

// triage 대상(waiting/error)만 모은다. issues 는 이미 waiting/error 로 받아온 것이라 가정.
export function buildTriageItems(
  issues: Issue[], allProjects: Project[], allInitiatives: Initiative[],
  opts: { mineOnly: boolean; userEmail: string | null },
): TriageItem[] {
  const mine = (owner?: string | null) => !opts.mineOnly || owner === opts.userEmail
  return [
    ...allProjects.filter(isProjTriage).filter((g) => mine(g.resolved_owner))
      .map((g): TriageItem => ({ kind: 'project', id: g.project_id, status: g.status, project: g })),
    ...allInitiatives.filter(isInitTriage).filter((i) => mine(i.owner))
      .map((i): TriageItem => ({ kind: 'initiative', id: i.initiative_id, status: i.status, initiative: i })),
    ...issues.filter((t) => mine(t.resolved_owner))
      .map((t): TriageItem => ({ kind: 'issue', id: t.issue_id, status: t.status, issue: t })),
  // worker 가 곧 픽업할 항목(코멘트 응답 달린 waiting)은 사람 큐가 아니므로 제외.
  // 미래 snooze 항목도 큐에서 숨김 (만료 시 다음 폴링에서 자동 복귀).
  ].filter((i) => !workerWillPickup(i) && !itemSnoozed(i))
}

export function filterTab(items: TriageItem[], tab: TabValue): TriageItem[] {
  return tab === 'all' ? items
    : items.filter((i) => i.status === tab)
}

// visible 항목들을 Initiative ▸ Project 트리로 묶고 정렬 기준으로 그룹을 재정렬한다 (standalone 은 항상 마지막).
export function buildTriageTree(
  visible: TriageItem[], allProjects: Project[], allInitiatives: Initiative[], sort: SortMode,
): TopNode[] {
  const projectMap = new Map(allProjects.map((p) => [p.project_id, p]))
  const initiativeMap = new Map(allInitiatives.map((i) => [i.initiative_id, i]))
  const issueInitId = (t: Issue): string | null => {
    const proj = t.project_id ? projectMap.get(t.project_id) : undefined
    return proj?.initiative_id ?? t.effective_initiative_id ?? t.initiative_id ?? null
  }
  const tops = new Map<string, TopNode>()
  const topFor = (initId: string | null): TopNode => {
    const key = initId ?? STANDALONE
    let n = tops.get(key)
    if (!n) {
      n = { key, initiative: initId ? initiativeMap.get(initId) : undefined, projects: new Map(), looseIssues: [] }
      tops.set(key, n)
    }
    return n
  }
  const projFor = (top: TopNode, projId: string): ProjNode => {
    let p = top.projects.get(projId)
    if (!p) { p = { projectId: projId, project: projectMap.get(projId), issues: [] }; top.projects.set(projId, p) }
    return p
  }
  for (const item of visible) {
    if (item.kind === 'initiative') {
      const top = topFor(item.initiative.initiative_id)
      top.self = item
      top.initiative = item.initiative
    } else if (item.kind === 'project') {
      const top = topFor(item.project.initiative_id ?? null)
      const p = projFor(top, item.project.project_id)
      p.self = item
      p.project = item.project
    } else {
      const t = item.issue
      const top = topFor(issueInitId(t))
      if (t.project_id) projFor(top, t.project_id).issues.push(item)
      else top.looseIssues.push(item)
    }
  }
  const compare = (a: TriageItem, b: TriageItem) => compareItems(a, b, sort)
  return [...tops.values()].sort((a, b) => {
    if (a.key === STANDALONE) return 1
    if (b.key === STANDALONE) return -1
    const ra = repBy(nodeItems(a), compare), rb = repBy(nodeItems(b), compare)
    if (!ra) return 1
    if (!rb) return -1
    return compare(ra, rb)
  })
}

// 트리를 화면 표시 순서 그대로 평탄화한다(맥락 헤더 제외 = 실제 처리 대상만) — TopGroupView 렌더 순서와 동일.
export function flattenQueue(topNodes: TopNode[], sort: SortMode): FocusItem[] {
  const compare = (a: TriageItem, b: TriageItem) => compareItems(a, b, sort)
  const out: FocusItem[] = []
  for (const node of topNodes) {
    if (node.self) out.push(toFocusItem(node.self))
    const projectNodes = [...node.projects.values()].sort((a, b) => {
      const ra = repBy(projItems(a), compare), rb = repBy(projItems(b), compare)
      if (!ra) return 1
      if (!rb) return -1
      return compare(ra, rb)
    })
    for (const p of projectNodes) {
      if (p.self) out.push(toFocusItem(p.self))
      for (const it of [...p.issues].sort(compare)) out.push(toFocusItem(it))
    }
    for (const it of [...node.looseIssues].sort(compare)) out.push(toFocusItem(it))
  }
  return out
}

// 라이브 재구성용 — 원시 목록에서 큐(FocusItem[])까지 한 번에. Triage 페이지가 ▶ 누른 시점의 필터·정렬과
// 동일한 params 로 호출하면 그때와 같은 순서가 나온다.
export function buildTriageQueue(
  issues: Issue[], allProjects: Project[], allInitiatives: Initiative[], params: QueueParams,
): FocusItem[] {
  const items = buildTriageItems(issues, allProjects, allInitiatives, params)
  const visible = filterTab(items, params.tab)
  const topNodes = buildTriageTree(visible, allProjects, allInitiatives, params.sort)
  const scoped = params.deckKey ? topNodes.filter((n) => n.key === params.deckKey) : topNodes
  return flattenQueue(scoped, params.sort)
}
