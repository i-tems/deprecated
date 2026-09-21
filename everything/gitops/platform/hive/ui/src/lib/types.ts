// Issue 워커 status (8상태). Issue 전용 — Project/Initiative 는 ContainerStatus.
export type EntityStatus = 'backlog' | 'todo' | 'running' | 'waiting' | 'cleanup' | 'done' | 'cancelled' | 'error'

// Project·Initiative 공통 container status (5상태). backlog=parked/pre-launch,
// active=in-progress, waiting=parked/사람 답변 대기(non-terminal, active↔terminal 사이),
// done=completed(terminal), archive=abandoned/shelved(terminal).
// 정본: ~/hive/.claude/specs/model (container status 단일화 — 구 project cancelled/error,
// 구 initiative planned/completed + archived flag 를 흡수).
export type ContainerStatus = 'backlog' | 'active' | 'waiting' | 'done' | 'archive'

// status icon/select 같은 공용 컴포넌트가 양쪽을 받을 때의 합집합.
export type AnyStatus = EntityStatus | ContainerStatus

// status 도메인 식별자 — 공용 컴포넌트가 어느 라벨/전이/아이콘 표를 쓸지 분기.
export type StatusKind = 'issue' | 'container'

export interface Label {
  label_id: string
  cell_id: string
  name: string
  color: string  // hex "#RRGGBB"
  description?: string | null
  created_at: string
  updated_at: string
}

export interface Priority {
  value: number
}

export type GateValue = 'skip' | 'auto' | 'require'

export interface Gates {
  completion: GateValue
}

// Worker가 만든 PR 정보 (issue/project에 누적). 실제 merge 상태는 pr.status capability 로
// derive-on-read — 이 객체엔 stable identity 만 들고 있다 (예전 merge_state 필드는 폐기).
export interface PrInfo {
  url: string
  repo: string
  pr_number: number
  head_branch: string
  base: string
  role: string  // 'cell' | 'default/dev' | 'default/no-dev' | 'policy/<base>' | ...
  reported_at?: string
}


export interface Project {
  project_id: string
  cell_id?: string
  seq?: number
  title: string
  /** 사양(Outcome / Scope / Constraints) + 사람·워커 공용 사실·맥락·메모. */
  description?: string
  /** 워커가 작성하는 planning_frameworks 본문. 사람은 보통 비워둔다. */
  plan?: string | null
  status: ContainerStatus
  previous_status?: ContainerStatus | null
  /** true면 agent-loop 자동 픽업 차단 (개인 세션 수동작업 보호) */
  hold?: boolean
  dependencies: string[]
  source_signal_ids?: string[]
  labels?: string[]  // label_id 리스트
  resources?: Resource[]
  /** 이 Project 이 소유/관련된 meta App 이름. derived deployments 소스. */
  apps?: string[]
  /** Derived — hub 가 cell repo space 디렉토리를 스캔해 반환. read-only. */
  artifacts?: Artifact[]
  /** Derived — hub 가 meta 에서 도출한 live 배포 URL. read-only. */
  deployments?: Deployment[]
  gates?: Gates | null
  priority?: Priority | null
  priority_score?: number
  metadata?: Record<string, unknown>
  owner?: string | null
  resolved_owner?: string | null
  session_id?: string | null
  pr_urls?: PrInfo[]
  initiative_id?: string | null
  /** T3 derived field — Project entity context 에 얕은 깊이로 포함되는 Initiative 요약. */
  initiative?: InitiativeSummary | null
  /** 미응답 사용자 코멘트(chain head) event_id 들. 비어있지 않고 status=waiting 이면
   *  worker 가 곧 픽업한다 (hub `_recompute_pending_and_wake` 가 유지). read-only. */
  pending_user_comment_event_ids?: string[]
  /** Derived — 코멘트/상태전이 중 최신 시각. 덱 changed_since_view 계산 소스. read-only. */
  last_activity_ts?: string | null
  /** Derived (per-user) — 호출자가 마지막으로 본 시각. 안 봤으면 null. read-only. */
  last_viewed_at?: string | null
  /** Derived (per-user) — 마지막 본 이후 활동(새 코멘트/상태전이)이 있거나 한 번도 안 봤으면 true. read-only. */
  changed_since_view?: boolean
  created_at: string
  updated_at: string
}

export type ResourceType = 'repo' | 'doc' | 'api' | 'url'

export interface Resource {
  label: string
  uri: string
  type: ResourceType
  description?: string | null
  created_at?: string | null
}

/** Derived field — hub 가 cell repo `data/{type}s/{id}/` git tree 를 스캔해 매번
 *  반환하는 산출물 목록. resources(외부 리소스) 와 분리된 read-only 채널. */
export interface Artifact {
  path: string       // repo root 기준 (e.g. data/projects/INFRA-PROJECT-5/plan.md)
  blob_url: string   // main branch blob URL — PR 머지 후에도 link rot 없음
  size: number
  sha: string
}

/** Derived field — hub 가 meta 에서 매번 도출하는 live 배포 URL. project.apps[]
 *  또는 issue 브랜치 매칭. 사람이 닿는 host(tunnel/prd)만, read-only. */
export interface Deployment {
  app: string
  env: string        // prd | dev | preview
  url: string        // https://… (tunnel 또는 prd 공개 도메인)
  phase: string      // meta 배포 상태 (Ready 등)
}

export interface Issue {
  issue_id: string
  cell_id?: string
  seq?: number
  project_id: string
  title: string
  /** 사양(Outcome / Scope / Constraints) + 사람·워커 공용 사실·맥락·메모. */
  description?: string | null
  /** 워커가 작성하는 planning_frameworks 본문. 사람은 보통 비워둔다. */
  plan?: string | null
  status: EntityStatus
  previous_status?: EntityStatus | null
  /** true면 agent-loop 자동 픽업 차단 (개인 세션 수동작업 보호) */
  hold?: boolean
  source_signal_ids?: string[]
  labels?: string[]  // label_id 리스트
  capability: string[]
  dependencies: string[]
  model: string | null
  resources?: Resource[]
  /** Derived — hub 가 cell repo space 디렉토리를 스캔해 반환. read-only. */
  artifacts?: Artifact[]
  /** Derived — hub 가 meta 에서 도출한 live 배포 URL. read-only. */
  deployments?: Deployment[]
  gates?: Gates | null
  priority?: Priority | null
  priority_score?: number
  metadata?: Record<string, unknown>
  owner?: string | null
  resolved_owner?: string | null
  session_id?: string | null
  pr_urls?: PrInfo[]
  /** standalone Issue 가 직접 anchor 한 Initiative. project 있으면 dormant (effective 는 상위 Project 를 따라감). */
  initiative_id?: string | null
  /** Derived — effective initiative id. project 있으면 상위 Project 의 initiative, 없으면 initiative_id. read-only. */
  effective_initiative_id?: string | null
  /** Derived — effective Initiative 의 얕은 요약 (T3). 없으면 null. read-only. */
  initiative?: InitiativeSummary | null
  /** 미응답 사용자 코멘트(chain head) event_id 들. 비어있지 않고 status=waiting 이면
   *  worker 가 곧 픽업한다 (hub `_recompute_pending_and_wake` 가 유지). read-only. */
  pending_user_comment_event_ids?: string[]
  /** Derived — 코멘트/상태전이 중 최신 시각. 덱 changed_since_view 계산 소스. read-only. */
  last_activity_ts?: string | null
  /** Derived (per-user) — 호출자가 마지막으로 본 시각. 안 봤으면 null. read-only. */
  last_viewed_at?: string | null
  /** Derived (per-user) — 마지막 본 이후 활동(새 코멘트/상태전이)이 있거나 한 번도 안 봤으면 true. read-only. */
  changed_since_view?: boolean
  created_at: string
  updated_at: string
}

// Initiative — Project/Issue 와 동형으로 단일 status 축, sub-initiative ≤5 depth.
// Spec: ~/hive/.claude/specs/model/initiative_model.md
// status 는 이제 Project 과 동일한 container 모델(backlog|active|done|archive).
// archive 는 별도 boolean flag 가 아니라 terminal status 다.
export type InitiativeStatus = ContainerStatus

export interface Initiative {
  initiative_id: string
  cell_id: string
  seq?: number
  name: string
  description?: string | null
  status: InitiativeStatus
  owner?: string | null
  color?: string | null
  icon?: string | null
  parent_initiative_id?: string | null
  resources?: Resource[]
  priority?: Priority | null
  priority_score?: number
  hold?: boolean
  /** 미응답 사용자 코멘트(chain head) event_id 들. 비어있지 않고 status=waiting 이면
   *  worker 가 곧 픽업한다 (hub `_recompute_pending_and_wake` 가 유지). read-only. */
  pending_user_comment_event_ids?: string[]
  /** Derived — 코멘트/상태전이 중 최신 시각. 덱 changed_since_view 계산 소스. read-only. */
  last_activity_ts?: string | null
  /** Derived (per-user) — 호출자가 마지막으로 본 시각. 안 봤으면 null. read-only. */
  last_viewed_at?: string | null
  /** Derived (per-user) — 마지막 본 이후 활동(새 코멘트/상태전이)이 있거나 한 번도 안 봤으면 true. read-only. */
  changed_since_view?: boolean
  created_at: string
  updated_at: string
}

// Project entity context 에 얕은 깊이로 포함되는 Initiative 요약 (T3 derived field).
export interface InitiativeSummary {
  initiative_id: string
  name: string
  status: InitiativeStatus
}

// emitted = awaiting triage (inbox), consumed = absorbed into an Issue/Project
// (downstream progress lives on that entity), dismissed = no action.
export type SignalStatus = 'emitted' | 'consumed' | 'dismissed'

export interface Signal {
  signal_id: string
  cell_id?: string
  seq?: number
  type: string
  ts_emitted: string
  status: SignalStatus
  history: Array<{ status: string; ts: string; by?: string | null; note?: string | null }>
  title?: string | null
  description: string         // 사람용 본문. raw 의 구조화 evidence 는 별도 field.
  priority: number            // 1-5 (Issues/Projects 와 동일 scale)
  issue_id?: string | null
  project_id?: string | null
  session_id?: string | null
  raw?: SignalRaw | null      // signal-types.schema 의 detail.raw — 구조화 evidence/provenance.
}

export interface SignalRaw {
  target?: string             // 자연어 또는 식별자 (예: Iceberg FQN, capability id, rule path).
  evidence?: {
    sources?: Array<{ source?: string; ref?: string }>
  }
  metadata?: Record<string, unknown>
  [key: string]: unknown      // type 별 추가 sub-field 허용.
}

export type EntityMap = Record<string, { title: string; status: AnyStatus }>

// Inbox
export type InboxStatus = 'unread' | 'read'

export interface InboxItem {
  inbox_id: string
  type: string  // 'issue.done' | 'project.done' | 'signal.emitted' | 'insight.observed' (UI 라벨 매핑은 InboxPage 내부)
  status: InboxStatus
  ref: string
  summary: string
  body?: string  // 옵션 markdown 본문 (inbox.add 발행 시 함께 적재 — 상세 확장 시 표시).
  cell_id?: string  // record 소속 cell. user-level aggregate (inbox.list_all) 응답에서 UI 가 뱃지·라우팅에 사용. cell-scoped 호출에선 자명한 값이라 옵셔널.
  created_at: string
}

// Activity Feed
export type FeedItemKind = 'status_change' | 'field_change' | 'comment'

// comment 내부 의도 분류 (event.py CommentSubtype과 동기화)
export type CommentSubtype = 'discussion' | 'progress' | 'transition' | 'handoff' | 'halt'

export type PrincipalType = 'user' | 'worker' | 'system' | 'cli'

export interface FeedItem {
  kind: FeedItemKind
  ts: string
  data: Record<string, unknown>
  event_id: string
  session_id?: string
  principal_id?: string
  principal_type?: PrincipalType
  edited_at?: string
}

export interface CommentData {
  text?: string
  subtype?: CommentSubtype
  parent_event_id?: string
  payload?: Record<string, unknown>
}

// 워커 핸드오프(handoff/halt/done) comment_payload 의 선택지 — ActivityFeed 원본 코멘트의 인라인 버튼.
// transition = 상태전이 (issue.update), reply = 자유텍스트 답변 (event.add), create = 후속 entity
// 적재 (project.create/issue.create — 워커는 draft 만, 사람 클릭이 트리거). 본문(comment) 은 그대로
// 두고 추가 필드. options 비어 있으면 본문/payload 만 노출(하위호환).
export type HandoffOptionAction =
  | { type: 'transition'; status: AnyStatus; comment?: string }
  | { type: 'reply'; text: string; subtype?: CommentSubtype }
  | { type: 'create'; entity: 'project' | 'issue'; draft: Record<string, unknown> }

export interface HandoffOption {
  label: string
  key?: string  // 소문자 1자 (e.g. 'a', 'r'). 미지정 시 단축키 없음.
  tone?: 'primary' | 'danger' | 'default'
  action: HandoffOptionAction
}
