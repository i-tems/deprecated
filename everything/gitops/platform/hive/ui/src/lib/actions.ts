import type { NavigateFunction } from 'react-router-dom'
import type { ComponentType } from 'react'
import {
  Layers,
  CircleDot,
  Flag,
  Keyboard,
  LayoutGrid,
  ListChecks,
  MessageSquare,
  PanelLeft,
  Plug,
  Radar,
  Settings as SettingsIcon,
  Tag,
  Target,
  UserCircle2,
  UserPlus,
} from 'lucide-react'

// Linear 식 ⌘K 커맨드 팔레트의 액션 카탈로그. 액션은 정적으로 선언하고, 가용성은
// 현재 라우트에서 파생한 ActionContext 로 필터한다. 검색 결과와 같은 오버레이에
// 섞이므로 행렬 mutation 은 detail 페이지의 [data-kb="*"] 트리거를 click 으로 invoke
// 한다 — useDetailShortcuts 와 동일 경로. 페이지 이동·사이드바·도움말은 글로벌.

export type DetailEntity = 'issue' | 'project' | 'initiative'

export interface ActionContext {
  route: string
  entity: DetailEntity | null
  navigate: NavigateFunction
}

export type ActionGroup = '액션' | '이동' | '보기'

export interface Action {
  id: string
  label: string
  group: ActionGroup
  icon?: ComponentType<{ size?: number; className?: string }>
  hint?: string
  perform: (ctx: ActionContext) => void
  available?: (ctx: ActionContext) => boolean
}

// detail 페이지의 picker 트리거를 click 으로 연다. 미마운트면 조용히 fail.
function clickKb(name: string) {
  document.querySelector<HTMLElement>(`[data-kb="${name}"]`)?.click()
}

function focusComment() {
  const el = document.querySelector<HTMLTextAreaElement>('[data-kb="comment"]')
  if (!el) return
  el.scrollIntoView({ block: 'center' })
  el.focus()
}

function dispatchGlobal(name: string) {
  window.dispatchEvent(new CustomEvent(name))
}

const detailAvailable = (ctx: ActionContext) => ctx.entity !== null
const labelsAvailable = (ctx: ActionContext) => ctx.entity === 'issue' || ctx.entity === 'project'

const ACTIONS: Action[] = [
  // 상세 컨텍스트 액션 — useDetailShortcuts 와 동일 경로 (data-kb click).
  {
    id: 'detail.status',
    label: '상태 변경',
    group: '액션',
    icon: CircleDot,
    hint: 's',
    available: detailAvailable,
    perform: () => clickKb('status'),
  },
  {
    id: 'detail.priority',
    label: '우선순위 설정',
    group: '액션',
    icon: Flag,
    hint: 'p',
    available: detailAvailable,
    perform: () => clickKb('priority'),
  },
  {
    id: 'detail.assignee',
    label: '담당자 지정',
    group: '액션',
    icon: UserCircle2,
    hint: 'a',
    available: detailAvailable,
    perform: () => clickKb('assignee'),
  },
  {
    id: 'detail.labels',
    label: '라벨 편집',
    group: '액션',
    icon: Tag,
    hint: 'l',
    available: labelsAvailable,
    perform: () => clickKb('labels'),
  },
  {
    id: 'detail.assign-me',
    label: '나에게 할당',
    group: '액션',
    icon: UserPlus,
    hint: 'i',
    available: detailAvailable,
    perform: () => clickKb('assign-me'),
  },
  {
    id: 'detail.comment',
    label: '코멘트 작성',
    group: '액션',
    icon: MessageSquare,
    hint: 'c',
    available: detailAvailable,
    perform: focusComment,
  },

  // 페이지 이동.
  { id: 'go.projects', label: 'Projects 로 이동', group: '이동', icon: LayoutGrid, perform: (c) => c.navigate('/projects') },
  { id: 'go.issues', label: 'Issues 로 이동', group: '이동', icon: ListChecks, perform: (c) => c.navigate('/issues') },
  { id: 'go.initiatives', label: 'Initiatives 로 이동', group: '이동', icon: Target, perform: (c) => c.navigate('/initiatives') },
  { id: 'go.signals', label: 'Signals 로 이동', group: '이동', icon: Radar, perform: (c) => c.navigate('/signals') },
  { id: 'go.workspace', label: 'Workspace 로 이동', group: '이동', icon: Layers, perform: (c) => c.navigate('/workspace') },
  { id: 'go.capabilities', label: 'Capabilities 로 이동', group: '이동', icon: Plug, perform: (c) => c.navigate('/capabilities') },
  { id: 'go.settings', label: 'Settings 로 이동', group: '이동', icon: SettingsIcon, perform: (c) => c.navigate('/settings') },

  // 글로벌 토글 — Layout 이 window event 로 받는다.
  {
    id: 'view.sidebar',
    label: '사이드바 접기/펴기',
    group: '보기',
    icon: PanelLeft,
    hint: '⌘B',
    perform: () => dispatchGlobal('hive:toggle-sidebar'),
  },
  {
    id: 'view.shortcuts',
    label: '단축키 도움말',
    group: '보기',
    icon: Keyboard,
    hint: '?',
    perform: () => dispatchGlobal('hive:open-shortcuts'),
  },
]

function entityFromRoute(route: string): DetailEntity | null {
  if (/^\/issues\/[^/]+/.test(route)) return 'issue'
  if (/^\/projects\/[^/]+/.test(route)) return 'project'
  if (/^\/initiatives\/[^/]+/.test(route)) return 'initiative'
  return null
}

export function buildActionContext(route: string, navigate: NavigateFunction): ActionContext {
  return { route, entity: entityFromRoute(route), navigate }
}

// substring(대소문자 무시) match. 빈 쿼리면 가용성만 적용.
export function filterActions(query: string, ctx: ActionContext): Action[] {
  const q = query.trim().toLowerCase()
  return ACTIONS.filter((a) => (a.available ? a.available(ctx) : true))
    .filter((a) => (q ? a.label.toLowerCase().includes(q) || a.id.toLowerCase().includes(q) : true))
}

export const ACTION_GROUPS: ActionGroup[] = ['액션', '이동', '보기']
