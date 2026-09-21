const BASE = '/api'
const CELL_KEY = 'last_cell_id'
const CELL_QUERY = 'cell'

// URL 의 ?cell= 가 단일 진실의 원천. localStorage 는 새 탭 부트스트랩용 보조 기억.
export function getCellIdInUrl(): string | null {
  if (typeof window === 'undefined') return null
  return new URLSearchParams(window.location.search).get(CELL_QUERY)
}

export function getRememberedCellId(): string | null {
  return localStorage.getItem(CELL_KEY)
}

export function rememberCellId(cellId: string) {
  localStorage.setItem(CELL_KEY, cellId)
}

export function forgetRememberedCellId() {
  localStorage.removeItem(CELL_KEY)
}

export function getCellIdForRequest(): string | null {
  return getCellIdInUrl() ?? getRememberedCellId()
}

// SSE 변경 스트림 URL. cell 미정이면 null (구독 불가 → 폴링 fallback).
// EventSource 는 same-origin 이라 콘솔 JWT 쿠키를 자동 전송 (hub sse.py 가
// in-handler 인증). scopes: cell|signals|inbox, entityId: 더 좁은 구독.
export function changeStreamUrl(opts?: { scopes?: string[]; entityId?: string }): string | null {
  const cellId = getCellIdForRequest()
  if (!cellId) return null
  const p = new URLSearchParams({ cell_id: cellId })
  if (opts?.scopes && opts.scopes.length) p.set('scopes', opts.scopes.join(','))
  if (opts?.entityId) p.set('entity_id', opts.entityId)
  return `${BASE}/sse.subscribe?${p.toString()}`
}

async function post<T>(
  path: string,
  body: Record<string, unknown> = {},
  opts?: { skipCell?: boolean; cellOverride?: string },
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Source': 'console',
  }
  // URL 의 cell 이 정본. query 보정 중인 짧은 순간에는 remembered cell 로 보강한다.
  // cellOverride: user-level aggregate 행에서 mutation 할 때 — URL ?cell 이 없거나
  // 항목의 cell 과 다르므로 호출자가 명시적으로 지정. skipCell 보다 우선순위는 낮다.
  if (!opts?.skipCell) {
    const cellId = opts?.cellOverride ?? getCellIdForRequest()
    if (cellId) {
      headers['X-Cell-Id'] = cellId
    }
  }

  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (res.status === 401) {
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }

  const json = await res.json()
  const isCellIdRequired = res.status === 400 && json?.error_code === 'cell_id_required'
  const isCellAccessDenied = res.status === 403 && (json?.error_code === 'cell_forbidden' || json?.error_code === 'forbidden')
  if (isCellIdRequired || isCellAccessDenied) {
    // cell_id_required 는 URL/localStorage 에 cell 이 살아 있으면 transient race
    // (다음 요청에서 헤더 정상화) 로 본다 — reset 트리거하지 않고 에러만 던진다.
    // cell_forbidden/forbidden 은 명시적 접근 거부라 cell 재선택 유도.
    if (isCellAccessDenied || !getCellIdForRequest()) {
      forgetRememberedCellId()
      // 하드 reload 대신 CellProvider 가 React Router 로 부드럽게 CellSelect 로
      // 전환 (`needsSelection` 게이트) — auth/sidebar 등 React state 보존.
      window.dispatchEvent(new CustomEvent('hive:cell-reset'))
    }
    throw new Error(json?.message || 'Cell selection required')
  }
  if (!res.ok) throw new Error(json?.message || `${res.status} ${res.statusText}`)
  if (json.status === 'error') throw new Error(json.message || 'API error')
  return json.data as T
}

// --- Auth ---

// hive-term CLI 가 쓸 console JWT 발급. httpOnly auth_token 쿠키는 JS 가 못
// 읽으므로 서버 경유 — auth.refresh 가 fresh 7일 토큰을 body 로 돌려준다(쿠키도
// 함께 회전되지만 갱신 daemon 과 동일 경로라 무해). cell 무관이라 X-Cell-Id 없이
// 직접 fetch. 이 엔드포인트는 인증된 페이지에서 이미 호출 가능하므로 보안 표면
// 확대는 없다(버튼은 기존 능력을 UI 로 노출만).
export async function fetchCliToken(): Promise<string> {
  const res = await fetch(`${BASE}/auth.refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Source': 'console' },
  })
  if (res.status === 401) {
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  const json = await res.json()
  if (json.status !== 'ok' || !json.data?.token) {
    throw new Error(json?.message || 'CLI 토큰 발급 실패')
  }
  return json.data.token as string
}

// --- Cells ---
export interface Cell {
  cell_id: string
  name: string
  description: string | null
  status: 'active' | 'archived'
  allowed_emails: string[]
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}
export const cellList = async (params: Record<string, unknown> = {}) => {
  const data = await post<{ cells: Cell[]; count: number }>('/cell.list', params, { skipCell: true })
  return data.cells
}
export const cellUpdate = (params: Record<string, unknown>) => post<Cell>('/cell.update', params, { skipCell: true })

// --- User settings (per-user, cell-independent) ---
// 로그인 사용자(콘솔 JWT)에 귀속. cell 헤더 불필요(hub cell_middleware 가 /user.settings 예외).
// 확장 시 이 인터페이스/페이지에 섹션을 추가한다 (예: editor, notifications).
export interface UserSettings {
  email: string
  git_name: string | null
  git_email: string | null
  default_git_name: string
  default_git_email: string
  effective_git_name: string
  effective_git_email: string
  display_name: string | null
  avatar: string | null
  default_display_name: string
  effective_display_name: string
}
export const userSettingsGet = () =>
  post<UserSettings>('/user.settings.get', {}, { skipCell: true })
// 필드별 부분 저장: 보낸 키만 갱신, 빈 문자열은 override 해제, 생략(undefined)은 미변경.
export const userSettingsUpdate = (params: {
  git_name?: string
  git_email?: string
  display_name?: string
  avatar?: string
}) => post<UserSettings>('/user.settings.update', params, { skipCell: true })

// 닉네임/아바타 override 를 설정한 사용자 목록 — 타 사용자 표시(OwnerAvatar)에 쓴다.
export interface DirectoryUser {
  email: string
  display_name: string | null
  avatar: string | null
}
export const userDirectoryList = async () => {
  const data = await post<{ users: DirectoryUser[] }>('/user.directory.list', {}, { skipCell: true })
  return data.users
}

// Projects — response: { projects: [...], count }
export const projectList = async (params: Record<string, unknown> = {}) => {
  const data = await post<{ projects: import('./types').Project[]; count: number }>('/project.list', params)
  return data.projects
}
// User-scoped aggregate. cell 헤더 미부착 — hub 가 accessible_cell_ids 로 직접 결정.
export const projectListAll = async (params: Record<string, unknown> = {}) => {
  const data = await post<{ projects: import('./types').Project[]; count: number; total: number; next_cursor: string | null }>(
    '/project.list_all', params, { skipCell: true },
  )
  return data.projects
}
export const projectGet = (project_id: string) => post<import('./types').Project>('/project.get', { project_id })
export const projectCreate = (params: Record<string, unknown>) => post<import('./types').Project>('/project.create', params)
export const projectUpdate = (params: Record<string, unknown>, opts?: { cellOverride?: string }) =>
  post<import('./types').Project>('/project.update', params, opts)
export const projectDelete = (project_id: string) => post<{ deleted: string }>('/project.delete', { project_id })

// Issues — response: { issues: [...], count, total }
export interface IssueListResult {
  issues: import('./types').Issue[]
  count: number
  total: number
}
export const issueList = async (params: Record<string, unknown> = {}): Promise<IssueListResult> => {
  return post<IssueListResult>('/issue.list', params)
}
// User-scoped aggregate. cell 헤더 미부착.
export const issueListAll = async (params: Record<string, unknown> = {}): Promise<IssueListResult> => {
  return post<IssueListResult>('/issue.list_all', params, { skipCell: true })
}
export const issueGet = (issue_id: string) => post<import('./types').Issue>('/issue.get', { issue_id })
export const issueCreate = (params: Record<string, unknown>) => post<import('./types').Issue>('/issue.create', params)

import type { AnyStatus } from './types'
export interface DepDetail {
  id: string
  kind: 'issue' | 'project' | 'unknown'
  title?: string
  status?: AnyStatus
  satisfied: boolean
}

/** dependency id 별로 issue/project 조회 — issue 가 우선, 없으면 project. 둘 다 실패면 unknown. */
export async function resolveDependencyDetails(ids: string[] | undefined): Promise<DepDetail[]> {
  if (!ids || ids.length === 0) return []
  return Promise.all(ids.map(async (id): Promise<DepDetail> => {
    try {
      const t = await issueGet(id)
      return { id, kind: 'issue', title: t.title, status: t.status, satisfied: t.status === 'done' || t.status === 'cancelled' }
    } catch {
      try {
        const g = await projectGet(id)
        return { id, kind: 'project', title: g.title, status: g.status, satisfied: g.status === 'done' || g.status === 'archive' }
      } catch {
        return { id, kind: 'unknown', satisfied: true }  // lookup 실패는 스케줄러에서도 통과 — 동일 의미
      }
    }
  }))
}
export const issueUpdate = (params: Record<string, unknown>, opts?: { cellOverride?: string }) =>
  post<import('./types').Issue>('/issue.update', params, opts)

// 덱(Deck) read-state — detail 페이지 열람 시 "지금 봤다"를 per-user 로 기록.
// 응답의 last_viewed_at 갱신 → 덱이 "본 이후 변화"를 다시 계산. detail 페이지엔 ?cell 이
// 있어 X-Cell-Id 가 자동 부착된다.
export const viewMark = (
  entity_type: 'issue' | 'project' | 'initiative',
  entity_id: string,
  opts?: { cellOverride?: string },
) => post<{ entity_type: string; entity_id: string; last_viewed_at: string }>(
  '/view.mark', { entity_type, entity_id }, opts,
)

// Initiatives — Linear 정본 (Cell→Initiative→Project→Issue 4-layer). response: { initiatives, count, total, next_cursor }
export const initiativeList = async (params: Record<string, unknown> = {}) => {
  const data = await post<{
    initiatives: import('./types').Initiative[]
    count: number
    total: number
    next_cursor: string | null
  }>('/initiative.list', params)
  return data.initiatives
}
// User-scoped aggregate. cell 헤더 미부착.
export const initiativeListAll = async (params: Record<string, unknown> = {}) => {
  const data = await post<{
    initiatives: import('./types').Initiative[]
    count: number
    total: number
    next_cursor: string | null
  }>('/initiative.list_all', params, { skipCell: true })
  return data.initiatives
}
export const initiativeGet = (initiative_id: string) =>
  post<import('./types').Initiative>('/initiative.get', { initiative_id })
export const initiativeCreate = (params: Record<string, unknown>) =>
  post<import('./types').Initiative>('/initiative.create', params)
export const initiativeUpdate = (params: Record<string, unknown>, opts?: { cellOverride?: string }) =>
  post<import('./types').Initiative>('/initiative.update', params, opts)

// Labels — cell-scoped Linear style. response: { labels: [...], count }
export const labelList = async (params: Record<string, unknown> = {}) => {
  const data = await post<{ labels: import('./types').Label[]; count: number }>('/label.list', params)
  return data.labels
}
export const labelGet = (label_id: string) => post<import('./types').Label>('/label.get', { label_id })
export const labelCreate = (params: { name: string; color?: string; description?: string }) =>
  post<import('./types').Label>('/label.create', params)
export const labelUpdate = (params: { label_id: string; name?: string; color?: string; description?: string }) =>
  post<import('./types').Label>('/label.update', params)
export const labelDelete = (label_id: string) =>
  post<import('./types').Label & { cascade: { projects: string[]; issues: string[] } }>('/label.delete', { label_id })

// Signals — response: { signals, count, total, next_cursor }
export const signalList = (params: Record<string, unknown> = {}) =>
  post<{ signals: import('./types').Signal[]; count: number; total: number; next_cursor: string | null }>('/signal.list', params)
// User-scoped aggregate. cell 헤더 미부착.
export const signalListAll = (params: Record<string, unknown> = {}) =>
  post<{ signals: import('./types').Signal[]; count: number; total: number; next_cursor: string | null }>(
    '/signal.list_all', params, { skipCell: true },
  )
export const signalGet = (signal_id: string) => post<import('./types').Signal>('/signal.get', { signal_id })
export const signalUpdateStatus = (params: Record<string, unknown>) => post<import('./types').Signal>('/signal.update_status', params)

// Inbox
export const inboxList = async (params: Record<string, unknown> = {}) => {
  const data = await post<{ items: import('./types').InboxItem[]; count: number }>('/inbox.list', params)
  return data.items
}
// User-scoped aggregate. cell 헤더 미부착.
export const inboxListAll = async (params: Record<string, unknown> = {}) => {
  const data = await post<{ items: import('./types').InboxItem[]; count: number }>('/inbox.list_all', params, { skipCell: true })
  return data.items
}
export const inboxAck = (inbox_id: string) => post<import('./types').InboxItem>('/inbox.ack', { inbox_id })
export const inboxAckAll = () => post<{ acked: number }>('/inbox.ack_all')

// Events (Activity Feed)
export const eventList = async (params: Record<string, unknown>) => {
  const data = await post<{ feed: import('./types').FeedItem[]; count: number }>('/event.list', params)
  return data.feed
}
export const eventAdd = (params: Record<string, unknown>) =>
  post<Record<string, unknown>>('/event.add', params)
export const eventUpdateComment = (params: {
  entity_type: string
  entity_id: string
  target_event_id: string
  text?: string
  subtype?: import('./types').CommentSubtype
  payload?: Record<string, unknown>
}) => post<Record<string, unknown>>('/event.update_comment', params)
export const eventDeleteComment = (params: { entity_type: string; entity_id: string; target_event_id: string }) =>
  post<Record<string, unknown>>('/event.delete_comment', params)

// Workers — live AI activity (text/tool_use/tool_result) relayed from runtime.
// PR #146 stdout `[ai-activity]` 채널 대체. hub 가 세션별 ring buffer 에 적재,
// push 시 wake_bus.notify → 기존 SSE 로 UI 가 거의 실시간 refetch.
export interface ActivityEvent {
  seq: number
  idx?: number   // history(과거 이력) item 의 전 세션 통합 정렬 순번
  ts: string
  kind: 'text' | 'tool_use' | 'tool_result' | 'turn'
  text?: string
  tool?: string
  tool_use_id?: string   // tool_use↔tool_result 정확 페어링 키
  input?: string
  output?: string
  is_error?: boolean
  prompt?: string        // kind==='turn': 그 turn 의 주입 작업지시/델타
}
export interface ActivityState {
  session_id: string | null
  started_at: string | null
  last_seen: string | null
  active: boolean
  last_seq: number
  items: ActivityEvent[]
}
export const workerActivityList = (params: { entity_type: 'issue' | 'project' | 'initiative'; entity_id: string; after_seq?: number }) =>
  post<ActivityState>('/worker.activity_list', params)

// Durable 과거 이력 — Agent SDK 세션 JSONL(공유 NFS) 기반. ring buffer 가
// 휘발(워커 비실행·hub 재시작·세션 교체 시 소실)된 뒤에도 보존. 역방향
// 페이지네이션(before_idx)으로 패널 상단 스크롤 시 더 과거를 이어 받는다.
export interface ActivityHistoryResponse {
  items: ActivityEvent[]   // 각 item 에 idx(전 세션 통합 정렬 순번) 포함
  total: number
  oldest_idx: number       // 이번 페이지가 시작한 idx (다음 before_idx)
  has_more: boolean        // oldest_idx > 0
}
export const workerActivityHistory = (params: {
  entity_type: 'issue' | 'project' | 'initiative'; entity_id: string; before_idx?: number; limit?: number
}) => post<ActivityHistoryResponse>('/worker.activity_history', params)

// 지금 살아있는(heartbeat TTL 30s 내) 워커 — status='running' 과 달리 *실제로 turn 을
// 도는 중*인지의 진짜 신호. hub in-memory _HEARTBEATS 기반. cell-scoped (list_all 과 달리
// 미들웨어가 X-Cell-Id 강제) 라 호출자가 cell 을 명시한다 — cross-cell 집계는 호출 쪽에서
// 활성 cell 마다 fan-out.
export interface ActiveWorker {
  worker_id: string
  cell_id?: string
  issue_id?: string | null   // Project 워커는 null — entity 매핑 불가
  session_type?: string
  started_at?: string
  last_seen?: string
  phase?: string | null      // bootstrap | claude_run | publish | post_dispatch
  note?: string | null
  session_id?: string | null
}
export const workerListActive = (cellId: string) =>
  post<{ workers: ActiveWorker[]; count: number }>(
    '/worker.list_active', { cell_id: cellId }, { cellOverride: cellId },
  )

// Capabilities
export const capabilityList = async () => {
  const data = await post<{ capabilities: { id: string; path: string; description: string | null }[]; count: number }>('/capability.list')
  return data.capabilities
}

// Remote sandbox sessions
// URL 로 감지되는 실제 entity 3종.
export type SandboxEntityType = 'issue' | 'project' | 'initiative'
// 세션이 묶일 수 있는 claude skill 종류 — entity 3종 + cross-cell 광역 attending
// + cell CEO 전략 대화 directing.
export type SandboxSessionKind = SandboxEntityType | 'attending' | 'directing'

export interface SandboxSession {
  id: string
  type: 'sandbox'
  status: string
  image: string
  created_at: string
  expires_at: string
  cell_id?: string
  session_id?: string
  // skill-bound 세션 — 설정되면 sandbox.ws 진입에서 claude 로 부팅. entity 3종은
  // /steering-*, 'attending' 은 /attending-user, 'directing' 은 /directing-cells
  // (둘 다 entity_id 없음). 미설정 = plain bash.
  entity_type?: SandboxSessionKind | null
  entity_id?: string | null
}

export interface SandboxCreateParams {
  image?: string
  session_id?: string
  ttl_hours?: number
  cpus?: number
  memory_mb?: number
  entity_type?: SandboxSessionKind
  entity_id?: string
}

export const sandboxList = () => post<SandboxSession[]>('/sandbox.list', {})
export const sandboxCreate = (params: SandboxCreateParams) =>
  post<SandboxSession>('/sandbox.create', params as Record<string, unknown>)
export const sandboxExtend = (id: string, hours: number) => post<SandboxSession>('/sandbox.extend', { id, hours })
export const sandboxDestroy = (id: string) => post<{ id: string; destroyed: boolean }>('/sandbox.destroy', { id })

// PR status — derive-on-read (hub 가 GitHub API 프록시, 30s 캐시).
// hub 저장소의 pr_urls[].merge_state 는 폐기됨 — UI 는 이 endpoint 로 현재 상태를 받는다.
export type PrLiveState = 'merged' | 'open' | 'draft' | 'closed'
export interface PrStatusResult {
  state: PrLiveState
  mergeable: boolean | null
  fetched_at: string
}
export const prStatus = (url: string) =>
  post<PrStatusResult>('/pr.status', { url }, { skipCell: true })

// Health
export async function healthCheck(): Promise<{ service: string; version: string; status: string }> {
  const res = await fetch(`${BASE}/health`)
  return res.json()
}
