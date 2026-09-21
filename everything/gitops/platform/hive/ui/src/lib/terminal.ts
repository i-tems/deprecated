import type { SandboxEntityType, SandboxSessionKind, SandboxSession } from '@/lib/api'
import { getCellIdForRequest } from '@/lib/api'
import { isUserLevelPath } from '@/lib/userLevelPaths'

export const ENTITY_LABEL: Record<SandboxEntityType, string> = {
  issue: '이슈',
  project: '프로젝트',
  initiative: '이니셔티브',
}

// attending·directing 포함 전체 session kind 표시 라벨.
export const SESSION_KIND_LABEL: Record<SandboxSessionKind, string> = {
  ...ENTITY_LABEL,
  attending: 'attending-user',
  directing: 'CEO 대화',
}

export function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v))
}

// 현재 페이지에 맞는 hive-term 연결 명령(스니펫). FAB 버튼이 복사한다 — 세션 객체
// 없이 **페이지에서 직접 파생**한다: entity 상세→그 entity steering, cell-scoped→그
// cell CEO(directing), 그 외→attending. --name 으로 hive-term 이 그 이름의 세션을
// 만들거나(없으면) 이어붙인다(있으면 resume). 이름이 (cell,name)으로 dedup 되고 cwd
// 가 이름별 고유라 한 페이지=한 세션+재개. fresh console JWT 를 export 에 박는다.
// `cloudflared access curl` 은 URL 을 맨 앞에 둬야 한다(플래그 먼저면 parse 실패).
export function buildRunSnippet(token: string, pathname: string): string {
  const host = window.location.host
  const cell = getCellIdForRequest()
  const entity = detectEntityFromPath(pathname)
  let target: string
  if (entity) {
    target = `--name ${entity.type}-${entity.id} --entity-type ${entity.type} --entity-id ${entity.id}`
  } else if (isCellScopedPath(pathname)) {
    target = '--name ceo --entity-type directing'
  } else {
    target = '--name attending --entity-type attending'
  }
  if (cell) target += ` --cell ${cell}`
  return [
    `export HIVE_AUTH_TOKEN='${token}'`,
    `cloudflared access curl https://${host}/hive-term -fsSL -o /tmp/hive-term \\`,
    `  && python3 /tmp/hive-term attach ${target}`,
  ].join('\n')
}

export function formatTimeLeft(
  expiresAt: string,
  nowMs: number,
): { label: string; title: string; tone: string } {
  const expiresMs = new Date(expiresAt).getTime()
  if (!Number.isFinite(expiresMs)) {
    return {
      label: '--',
      title: '만료 시각 없음',
      tone: 'border-zinc-700 bg-zinc-900 text-zinc-300',
    }
  }

  const diffMs = expiresMs - nowMs
  const title = `만료 ${new Date(expiresMs).toLocaleString('ko-KR')}`
  if (diffMs <= 0) {
    return {
      label: 'expired',
      title,
      tone: 'border-red-500/40 bg-red-500/10 text-red-300',
    }
  }

  const minutesLeft = Math.floor(diffMs / 60000)
  const label = minutesLeft < 1 ? '<1m' : `${minutesLeft}m left`
  if (minutesLeft < 3) {
    return { label, title, tone: 'border-red-500/40 bg-red-500/10 text-red-300' }
  }
  if (minutesLeft < 10) {
    return { label, title, tone: 'border-amber-500/40 bg-amber-500/10 text-amber-200' }
  }
  return { label, title, tone: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' }
}

// pod phase 를 사람이 읽는 상태 라벨로. raw "Running"/"Pending"/"unknown" 대신 표시.
export function formatSandboxStatus(session: SandboxSession): { label: string; tone: string } {
  const RED = 'border-red-500/40 bg-red-500/10 text-red-300'
  const AMBER = 'border-amber-500/40 bg-amber-500/10 text-amber-200'
  const EMERALD = 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  const MUTED = 'border-zinc-700 bg-zinc-800 text-zinc-400'
  const ZINC = 'border-zinc-700 bg-zinc-800 text-zinc-300'
  switch ((session.status || '').toLowerCase()) {
    case 'running':
      return { label: '실행 중', tone: EMERALD }
    case 'pending':
    case 'containercreating':
    case '':
    case 'unknown':
      return { label: '준비 중', tone: AMBER }
    case 'failed':
      return { label: '실패', tone: RED }
    case 'succeeded':
      return { label: '종료됨', tone: MUTED }
    default:
      return { label: session.status, tone: ZINC }
  }
}

export function formatSessionLabel(sessionId: string): string {
  return sessionId.replace('sandbox-', '')
}

// skill-bound 세션은 skill 라벨로 표시 — 셀렉터·드롭다운에서 여러 세션을 한눈에
// 구분하게 한다. attending 은 id 없이 라벨만, entity 는 "이슈 abc-123" 식, plain
// 셸은 기존 sandbox-id 라벨로 폴백.
export function formatSessionTitle(session: SandboxSession): string {
  // attending·directing 은 id 없는 cell 단위 세션 — 라벨만.
  if (session.entity_type === 'attending' || session.entity_type === 'directing') {
    return SESSION_KIND_LABEL[session.entity_type]
  }
  if (session.entity_type && session.entity_id) {
    return `${SESSION_KIND_LABEL[session.entity_type]} ${session.entity_id}`
  }
  return formatSessionLabel(session.id)
}

const ENTITY_ID_RE = /^[A-Za-z0-9_-]{1,128}$/

// URL pathname 에서 entity 상세 페이지인지 판정. RemoteSshDrawer 의 CTA 와
// EntityActions 의 Steering 진입 버튼이 공유.
export function detectEntityFromPath(pathname: string): { type: SandboxEntityType; id: string } | null {
  const m = pathname.match(/^\/(issues|projects|initiatives)\/([^/?#]+)\/?$/)
  if (!m) return null
  const route = m[1]
  const id = m[2]
  if (!ENTITY_ID_RE.test(id)) return null
  const type: SandboxEntityType =
    route === 'issues' ? 'issue' : route === 'projects' ? 'project' : 'initiative'
  return { type, id }
}

// cell 단위 chrome·셀렉터·도움말 — cell 안의 데이터를 보는 페이지가 아니라
// cell 을 고르거나 cell 무관한 곳. (user-level aggregate 는 isUserLevelPath 가 따로 본다.)
const CELL_AGNOSTIC_PATHS = new Set(['/cells', '/help', '/login', '/'])

// "cell 안에 있는 페이지" 판정 — 터미널 기본 세션을 그 cell 의 CEO 대화
// (/directing-cells)로 띄울지, cross-cell attending 으로 띄울지 가른다. entity 상세는
// 호출부가 detectEntityFromPath 로 먼저 steering 으로 가르므로 여기 대상이 아니다.
// 리스트(/projects·/issues·/initiatives)·/signals·/capabilities·/settings 처럼
// cell 에 종속된 페이지는 true, inbox·triage(aggregate)·셀렉터·도움말은 false.
export function isCellScopedPath(pathname: string): boolean {
  if (isUserLevelPath(pathname)) return false
  if (CELL_AGNOSTIC_PATHS.has(pathname)) return false
  return true
}
