import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, AlertTriangle, ChevronRight, Wrench, Check, X, Loader2, Sparkles,
  FileText, SquarePen, Pencil, Terminal, Search, FolderOpen, Globe,
  Bot, BookOpen, ListTodo, Zap, Maximize2, ClipboardList, MoreHorizontal,
  type LucideIcon,
} from 'lucide-react'
import { PropertyGroup } from '@/components/PropertyRow'
import { Badge } from '@/components/ui/badge'
import { Modal } from '@/components/ui/modal'
import { Markdown } from '@/components/Markdown'
import { JsonView } from '@/components/JsonView'
import { usePolling } from '@/hooks/usePolling'
import {
  workerActivityList, workerActivityHistory,
  type ActivityState, type ActivityEvent,
} from '@/lib/api'
import { relativeTime } from '@/lib/utils'

interface Props {
  entityType: 'issue' | 'project' | 'initiative'
  entityId: string
}

// 과거 이력 한 페이지 크기. 위로 스크롤 시 이 단위로 이어 받는다.
const HIST_PAGE = 100

function elapsedLabel(fromIso: string, now: number): string {
  const sec = Math.max(0, Math.floor((now - new Date(fromIso).getTime()) / 1000))
  return sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`
}

// ── 표시 모델: flat 이벤트 → 대화 노드 ────────────────────────────────────────
// AI 텍스트는 prose 메시지로, tool_use+tool_result 는 한 액션으로 페어링해
// 접이식 칩으로. 페어링은 tool_use_id 로 **정확히** 매칭한다(이름+추정 LIFO
// 폐기 — 병렬·동일이름 호출이 뒤섞이거나 상단 군집되던 버그 수정). 노드는
// ts 를 들고 있어 진행 시각을 표시한다.
type ToolStatus = 'running' | 'ok' | 'error'
interface MsgNode { type: 'msg'; key: string; ts: string; text: string }
interface ToolNode {
  type: 'tool'; key: string; ts: string; tool: string
  input?: string; output?: string; status: ToolStatus
}
// 자율 워커의 turn 트리거(주입 작업지시/델타) — 압축 구분선으로 표시.
interface TurnNode { type: 'turn'; key: string; ts: string; prompt: string }
type ActNode = MsgNode | ToolNode | TurnNode

function groupNodes(items: { key: string; ev: ActivityEvent }[]): ActNode[] {
  const nodes: ActNode[] = []
  const byId: Record<string, ToolNode> = {}
  for (const { key, ev } of items) {
    if (ev.kind === 'turn') {
      const prompt = (ev.prompt ?? '').trim()
      if (prompt) nodes.push({ type: 'turn', key, ts: ev.ts, prompt })
    } else if (ev.kind === 'text') {
      const text = (ev.text ?? '').trim()
      if (text) nodes.push({ type: 'msg', key, ts: ev.ts, text })
    } else if (ev.kind === 'tool_use') {
      const n: ToolNode = {
        type: 'tool', key, ts: ev.ts, tool: ev.tool || '?',
        input: ev.input, status: 'running',
      }
      nodes.push(n)
      if (ev.tool_use_id) byId[ev.tool_use_id] = n
    } else {
      // tool_result — tool_use_id 로 정확 매칭. 매칭 tool_use 가 로드된
      // 페이지에 없으면(과거 윈도우 경계) 그 자리에 단독 결과 칩으로
      // 시간순 표시 (상단 군집 X).
      const target = ev.tool_use_id ? byId[ev.tool_use_id] : undefined
      if (target) {
        target.status = ev.is_error ? 'error' : 'ok'
        target.output = ev.output
      } else {
        nodes.push({
          type: 'tool', key, ts: ev.ts, tool: ev.tool || '?',
          output: ev.output, status: ev.is_error ? 'error' : 'ok',
        })
      }
    }
  }
  return nodes
}

function argHint(input?: string): string {
  if (!input) return ''
  // hub 가 절단한 JSON-ish 문자열 — 칩 한 줄용 짧은 힌트.
  const s = input.replace(/^\{|\}$/g, '').replace(/["\\]/g, '').replace(/\s+/g, ' ').trim()
  return s.length > 52 ? s.slice(0, 52) + '…' : s
}

// 도구 이름 → 아이콘. claude/hive 워커가 쓰는 툴 종류별로 한눈에 구분되게.
// mcp__*·capability 는 Zap, 알 수 없는 건 Wrench 폴백.
function toolIcon(name: string): LucideIcon {
  const n = name.toLowerCase()
  if (n.startsWith('mcp__') || n.includes('capability')) return Zap
  if (n.includes('multiedit') || n === 'edit' || n.includes('notebook')) return Pencil
  if (n === 'write') return SquarePen
  if (n === 'read') return FileText
  if (n === 'bash') return Terminal
  if (n === 'grep' || n.includes('websearch') || n === 'search') return Search
  if (n === 'glob' || n === 'ls') return FolderOpen
  if (n.includes('webfetch') || n.includes('fetch') || n.includes('url')) return Globe
  if (n === 'issue' || n === 'agent') return Bot
  if (n === 'skill') return BookOpen
  if (n.includes('todo')) return ListTodo
  return Wrench
}

// ISO ts → 로컬 HH:MM:SS. 진행 시각 표시(서사가 적은 transcript 의 순서 가독).
function clock(ts: string): string {
  const t = Date.parse(ts)
  if (!t) return ''
  const d = new Date(t)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// turn 프롬프트 → 한 줄 요약 (작업 title 우선 → 델타 → 첫 줄).
function turnSummary(prompt: string): string {
  const title = prompt.match(/"title"\s*:\s*"([^"]+)"/)
  if (title) return `작업: ${title[1]}`
  const delta = prompt.match(/이전 사이클 이후 변경[^\n]*\n?\s*([^\n]{0,80})/)
  if (delta) return `변경: ${(delta[1] || '').trim() || '없음'}`
  const line = prompt.split('\n').map((s) => s.trim()).find(Boolean) || ''
  return line.length > 72 ? line.slice(0, 72) + '…' : line
}

function firstLine(text: string): string {
  const s = (text.split('\n').map((x) => x.trim()).find(Boolean) || '')
    .replace(/[#*`>_~-]/g, '')
  return s.length > 64 ? s.slice(0, 64) + '…' : s
}

// 통일 Entry — 요청/답/액션 모두 동일 구조: 한 줄 헤더(▸ 아이콘 라벨
// 미리보기 [상태] 시각) + 접이식 본문.
// detailed=false(사이드바): 전부 접힘, 본문 plain text(compact·일관).
// detailed=true(확대 모달, 정독 뷰):
//  - 산문(요청·답)은 기본 펼침 + 마크다운 렌더로 통일. 액션(툴 I/O)만
//    접힘 — 덤프까지 다 펼치면 지저분해 서사 흐름이 묻힌다. 필요 시 클릭.
//    툴 I/O 는 코드·JSON 이라 항상 monospace pre — 종류가 명확해 비일관 아님.
function Entry({ node, detailed = false }: { node: ActNode; detailed?: boolean }) {
  const [open, setOpen] = useState(detailed && node.type !== 'tool')

  // turn(Request)은 Group 이 전담 렌더 — NodeList 는 Entry 에 turn 을
  // 넘기지 않는다. 런타임 불변식이지만 타입은 모르므로 여기서 명시 배제해
  // node 를 MsgNode|ToolNode 로 좁힌다(아래 tool 분기의 .tool/.input 등 보장).
  if (node.type === 'turn') return null

  // 사이드바: Reply(산문)는 서사 척추다 — 접지 않고 인라인 prose 로 바로
  // 읽히게 두고, 도구만 접힌 칩으로 남겨 부차 정보로 후퇴시킨다. 정독
  // 모달(detailed)은 기존 통일 Entry 그대로.
  if (!detailed && node.type === 'msg') {
    return (
      <div className="flex gap-1.5 border-b border-border-subtle/50 py-1.5 last:border-0">
        <Sparkles size={12} className="mt-0.5 shrink-0 text-accent/80" />
        <div className="min-w-0 flex-1 whitespace-pre-wrap break-words rounded bg-bg-hover/50 px-2 py-1 text-xs leading-relaxed text-text-secondary">
          {node.text}
        </div>
      </div>
    )
  }

  let Icon: LucideIcon
  let label: string
  let preview: string
  let body: React.ReactNode = null
  let status: React.ReactNode = null
  let accent = 'text-accent/80'

  const pre = detailed ? 'text-xs' : 'text-2xs'
  if (node.type === 'msg') {
    Icon = Sparkles
    label = 'Reply'
    preview = firstLine(node.text)
    // 마크다운은 정독 뷰(확대)에서만. 사이드바는 plain — 어떤 항목은
    // 마크다운, 어떤 항목은 아닌 비일관 해소.
    body = detailed
      ? (
        <div className="rounded bg-bg-hover/50 px-2 py-1">
          <Markdown className="text-sm leading-relaxed">{node.text}</Markdown>
        </div>
      )
      : <div className="whitespace-pre-wrap break-words text-xs leading-relaxed text-text-secondary">{node.text}</div>
  } else {
    Icon = toolIcon(node.tool)
    label = node.tool
    preview = argHint(node.input)
    if (node.status === 'running') {
      accent = 'text-accent'
      status = <Loader2 size={11} className="shrink-0 animate-spin text-accent" />
    } else if (node.status === 'ok') {
      status = <Check size={12} className="shrink-0 text-success" />
    } else {
      status = <X size={12} className="shrink-0 text-error" />
    }
    if (node.input || node.output) {
      // tool I/O 는 거의 JSON dump 또는 plain text — JsonView 가 자동 분기
      // (JSON 이면 indent=2 + 신택스 컬러, 아니면 원문 plain wrap).
      body = (
        <div className="space-y-1">
          {node.input && (
            <div>
              <div className="text-2xs uppercase tracking-wider text-text-tertiary">input</div>
              <JsonView
                raw={node.input}
                className={`mt-0.5 rounded bg-bg-hover/50 px-2 py-1 font-mono ${pre} text-text-secondary`}
              />
            </div>
          )}
          {node.output && (
            <div>
              <div className="text-2xs uppercase tracking-wider text-text-tertiary">
                {node.status === 'error' ? 'error' : 'output'}
              </div>
              <JsonView
                raw={node.output}
                className={`mt-0.5 rounded px-2 py-1 font-mono ${pre} ${
                  node.status === 'error' ? 'bg-error/10 text-error' : 'bg-bg-hover/50 text-text-secondary'
                }`}
              />
            </div>
          )}
        </div>
      )
    }
  }

  const hasBody = body != null
  const isTool = node.type === 'tool'
  return (
    <div className="border-b border-border-subtle/50 last:border-0">
      <button
        type="button"
        onClick={() => hasBody && setOpen((v) => !v)}
        className={`w-full flex items-center gap-1.5 py-1.5 text-left text-xs rounded ${
          hasBody ? 'hover:bg-bg-hover/50 cursor-pointer' : 'cursor-default'
        }`}
        title={hasBody ? (open ? 'Collapse' : 'Expand') : undefined}
      >
        <ChevronRight
          size={11}
          className={`shrink-0 text-text-tertiary transition-transform ${
            open ? 'rotate-90' : ''
          } ${hasBody ? '' : 'opacity-0'}`}
        />
        <Icon size={12} className={`shrink-0 ${accent}`} />
        <span className={`shrink-0 font-medium ${isTool ? 'font-mono text-text-secondary' : 'text-text'}`}>
          {label}
        </span>
        <span className="min-w-0 flex-1 truncate text-text-tertiary">{preview}</span>
        {status}
        {detailed && (
          <span className="shrink-0 text-2xs tabular-nums text-text-tertiary">{clock(node.ts)}</span>
        )}
      </button>
      {open && hasBody && <div className="pb-2 pl-6 pr-1">{body}</div>}
    </div>
  )
}

// turn(요청) 1개 + 그에 뒤따르는 답/액션 = 한 작업 단위. 평면 나열은
// 이 소속 관계를 못 보여줬다(요청·답·액션이 다 같은 깊이). turn 을 그룹
// 머리로 두고 자식 답/액션을 좌측 보더로 들여써 "이 요청이 낳은 것들"을
// 시각적으로 표현한다. 첫 turn 이전의 노드(로드 윈도우 경계)는 부모 없는
// 고아 그룹으로 평면 렌더.
interface TurnGroup { key: string; turn: TurnNode | null; children: (MsgNode | ToolNode)[] }

function groupByTurn(nodes: ActNode[]): TurnGroup[] {
  const groups: TurnGroup[] = []
  let cur: TurnGroup | null = null
  for (const n of nodes) {
    if (n.type === 'turn') {
      cur = { key: n.key, turn: n, children: [] }
      groups.push(cur)
    } else {
      if (!cur) { cur = { key: `orphan-${n.key}`, turn: null, children: [] }; groups.push(cur) }
      cur.children.push(n)
    }
  }
  return groups
}

// 한 turn 그룹. Request 머리 클릭 = 이 요청의 prompt·자식(Reply·도구) 전체
// 접기/펼치기 — "머리는 그룹 토글"이라는 트리 멘탈모델과 일치(접으면 그룹
// 전체가 한 줄). prompt 는 펼친 상태에서 기본 펼침(Reply 와 대칭), 헤더 ⋯
// 버튼으로 숨김 토글(긴 prompt 정리용) — 사이드바·모달 동일.
function Group({ g, detailed }: { g: TurnGroup; detailed: boolean }) {
  const t = g.turn!  // NodeList 가 g.turn 있을 때만 Group 렌더
  const [groupOpen, setGroupOpen] = useState(true)
  // prompt 기본 펼침 — Reply(기본 펼침)와 대칭. ⋯ 는 긴 prompt 숨김 토글로
  // 남는다. (사이드바에서도 prompt 가 ⋯ 뒤에 숨어 안 보이던 비대칭 해소)
  const [promptOpen, setPromptOpen] = useState(true)
  return (
    <div className="mt-1.5 first:mt-0">
      <div className="border-b border-border-subtle/50">
        <div className="flex items-center gap-1.5 py-1.5 text-xs">
          <button
            type="button"
            onClick={() => setGroupOpen((v) => !v)}
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded text-left hover:bg-bg-hover/50 cursor-pointer"
            title={groupOpen ? 'Collapse' : 'Expand'}
          >
            <ChevronRight
              size={11}
              className={`shrink-0 text-text-tertiary transition-transform ${groupOpen ? 'rotate-90' : ''}`}
            />
            <ClipboardList size={12} className="shrink-0 text-accent/80" />
            <span className="shrink-0 font-medium text-text">Request</span>
            <span className="min-w-0 flex-1 truncate text-text-tertiary">{turnSummary(t.prompt)}</span>
          </button>
          {groupOpen && (
            <button
              type="button"
              onClick={() => setPromptOpen((v) => !v)}
              className={`shrink-0 rounded p-0.5 hover:bg-bg-hover/50 ${promptOpen ? 'text-text' : 'text-text-tertiary'}`}
              title={promptOpen ? 'Hide prompt' : 'Show full prompt'}
            >
              <MoreHorizontal size={13} />
            </button>
          )}
          <span className="shrink-0 text-2xs tabular-nums text-text-tertiary">{clock(t.ts)}</span>
        </div>
        {groupOpen && promptOpen && (
          <div className="pb-2 pl-6 pr-1">
            {detailed
              ? (
                <div className="rounded bg-bg-hover/50 px-2 py-1">
                  <Markdown className="text-sm leading-relaxed">{t.prompt}</Markdown>
                </div>
              )
              : (
                <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap break-words rounded bg-bg-hover/50 px-2 py-1 font-mono text-2xs text-text-secondary">
                  {t.prompt}
                </pre>
              )}
          </div>
        )}
      </div>
      {groupOpen && (
        <div className="ml-2 border-l border-border-subtle/60 pl-2">
          {g.children.map((c) => <Entry key={c.key} node={c} detailed={detailed} />)}
        </div>
      )}
    </div>
  )
}

// 노드 → 렌더. 사이드바와 확대 모달이 동일 표현을 공유(중복 제거).
// turn 있는 그룹은 Group(접기·prompt 분리), turn 없는 고아 그룹은 평면 Entry.
function NodeList({ nodes, detailed = false }: { nodes: ActNode[]; detailed?: boolean }) {
  return (
    <>
      {groupByTurn(nodes).map((g) =>
        g.turn
          ? <Group key={g.key} g={g} detailed={detailed} />
          : (
            <div key={g.key}>
              {g.children.map((c) => <Entry key={c.key} node={c} detailed={detailed} />)}
            </div>
          ),
      )}
    </>
  )
}

/**
 * AI activity 패널 — 실시간(ring buffer, SSE) + durable 과거(세션 JSONL).
 * 대화형: AI 텍스트는 마크다운 prose 메시지, tool_use+tool_result 는 한
 * 액션으로 페어링해 접이식 칩(기본 접힘, 클릭 시 input/output). 워커 비실행·
 * hub 재시작·세션 교체 후에도 과거가 보이고(파일 기반), 위로 연속 스크롤하면
 * worker.activity_history 로 더 과거를 잇는다(역방향). 헤더 확대 버튼으로
 * 동일 transcript 를 큰 모달로 상세히 본다.
 */
export function LiveActivity({ entityType, entityId }: Props) {
  const fetcher = useCallback(
    () => workerActivityList({ entity_type: entityType, entity_id: entityId }),
    [entityType, entityId],
  )
  // SSE 전용. push 시 hub 가 wake_bus.notify(entityId) → 이 키에서 깨어 refetch.
  const { data } = usePolling<ActivityState>(fetcher, 5000, { scopes: ['cell'], entityId })

  const [now, setNow] = useState(() => Date.now())
  const [expanded, setExpanded] = useState(false)  // 확대 모달
  useEffect(() => {
    if (!data?.active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [data?.active])

  // ── durable 과거 이력 (역방향 페이지네이션) ────────────────────────────────
  const [hist, setHist] = useState<ActivityEvent[]>([])
  const [histOldestIdx, setHistOldestIdx] = useState<number | null>(null)
  const [histHasMore, setHistHasMore] = useState(false)
  // history 로드 실패는 무음으로 삼키면 "AI Activity 패널이 통째로 사라지는"
  // 사각지대가 된다 (관측: JSONL 안 lone surrogate → Starlette UTF-8 인코딩
  // 500 → catch 무음 → live 도 비어 있으면 hide gate 통과). 에러 메시지를
  // 상태로 유지해 패널 안에 가시화하고, hide gate 도 회피한다.
  const [histError, setHistError] = useState<string | null>(null)
  const loadingRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)            // 바닥 근처면 새 실시간에 자동 스크롤
  const prependRef = useRef(false)         // 직전 렌더가 과거 prepend 였는지
  const prevHeightRef = useRef(0)
  // 확대 모달은 인라인과 독립된 stick 상태 — 사이드바와 모달이 동시에 떠 있어도
  // 각자 스크롤 위치를 보존한다. 모달은 loadOlder 를 직접 트리거하지 않으므로
  // prepend anchor 는 필요 없다 (안내 배너만 표시).
  const modalScrollRef = useRef<HTMLDivElement>(null)
  const modalStickRef = useRef(true)

  const loadOlder = useCallback(async () => {
    if (loadingRef.current || !histHasMore) return
    loadingRef.current = true
    try {
      const r = await workerActivityHistory({
        entity_type: entityType, entity_id: entityId,
        before_idx: histOldestIdx ?? undefined, limit: HIST_PAGE,
      })
      if (r.items.length) {
        prependRef.current = true
        setHist((prev) => [...r.items, ...prev])
      }
      setHistOldestIdx(r.oldest_idx)
      setHistHasMore(r.has_more)
      setHistError(null)
    } catch (e) {
      setHistError(e instanceof Error ? e.message : String(e))
    } finally {
      loadingRef.current = false
    }
  }, [entityType, entityId, histOldestIdx, histHasMore])

  // entity 바뀌면 과거 초기 1페이지 로드 (실시간 ring 이 비어도 패널이 뜨도록).
  useEffect(() => {
    setHist([])
    setHistOldestIdx(null)
    setHistHasMore(false)
    setHistError(null)
    let alive = true
    loadingRef.current = true
    workerActivityHistory({ entity_type: entityType, entity_id: entityId, limit: HIST_PAGE })
      .then((r) => {
        if (!alive) return
        setHist(r.items)
        setHistOldestIdx(r.oldest_idx)
        setHistHasMore(r.has_more)
      })
      .catch((e) => {
        if (!alive) return
        setHistError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => { loadingRef.current = false })
    return () => { alive = false }
  }, [entityType, entityId])

  const liveItems = data?.items ?? []
  // 진행 순서 = 실제 timestamp 순. history(파일 ts: `…Z`)와 live(ring ts:
  // `…+00:00`)는 포맷이 달라 문자열 비교가 깨진다 → Date.parse 로 epoch(ms)
  // 비교. history 는 그 entity 의 완전한 상위집합이므로, live 는 history 의
  // 最新 ts 보다 엄격히 새로운 것만 덧붙인다(중복 차단, 경계 정합).
  const tms = (e: ActivityEvent) => Date.parse(e.ts) || 0
  const sortedHist = [...hist].sort((a, b) => tms(a) - tms(b))
  const maxHistMs = sortedHist.length ? tms(sortedHist[sortedHist.length - 1]) : 0
  const tailLive = [...liveItems]
    .sort((a, b) => tms(a) - tms(b))
    .filter((l) => tms(l) > maxHistMs)
  const ordered: { key: string; ev: ActivityEvent }[] = [
    ...sortedHist.map((ev) => ({ key: `h${ev.idx ?? ev.ts}`, ev })),
    ...tailLive.map((ev) => ({ key: `l${ev.seq}`, ev })),
  ]
  const nodes = groupNodes(ordered)
  // 현재 무엇을 하는지: active 일 때 마지막 노드 요약 (running tool 우선).
  const lastNode: ActNode | undefined = nodes[nodes.length - 1]
  let currentLabel: string | null = null
  if (data?.active && lastNode) {
    if (lastNode.type === 'tool') {
      currentLabel = lastNode.status === 'running'
        ? `${lastNode.tool} 실행 중…`
        : `${lastNode.tool} 완료 — 다음 단계 준비`
    } else if (lastNode.type === 'msg') {
      currentLabel = lastNode.text.replace(/\s+/g, ' ').slice(0, 60)
    } else {
      currentLabel = '새 turn 시작 — 작업 지시 수신'
    }
  }

  const lastSeq = data?.last_seq ?? 0
  // 실시간 새 이벤트 → 바닥 고정 시 자동 스크롤. 과거 prepend 시엔 스크롤 위치
  // 보존 (anchor: prepend 전후 scrollHeight 차만큼 보정).
  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      if (prependRef.current) {
        el.scrollTop += el.scrollHeight - prevHeightRef.current
        prependRef.current = false
      } else if (stickRef.current) {
        el.scrollTop = el.scrollHeight
      }
      prevHeightRef.current = el.scrollHeight
    }
    // 확대 모달도 동일 stick 규칙. 닫혀 있으면 ref 가 null 이라 무동작.
    const mel = modalScrollRef.current
    if (mel && modalStickRef.current) {
      mel.scrollTop = mel.scrollHeight
    }
  }, [nodes.length, lastSeq])

  // 모달이 열린 직후엔 바닥 정렬로 시작 (현재 진행 라인이 바로 보이게).
  useEffect(() => {
    if (!expanded) return
    const el = modalScrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    modalStickRef.current = true
  }, [expanded])

  const onScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    if (el.scrollTop < 48 && histHasMore && !loadingRef.current) {
      prevHeightRef.current = el.scrollHeight
      void loadOlder()
    }
  }, [histHasMore, loadOlder])

  const onModalScroll = useCallback(() => {
    const el = modalScrollRef.current
    if (!el) return
    modalStickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }, [])

  // 실시간도 과거도 전혀 없으면 렌더 안 함 (idle·이력 없음 — 사이드바 노이즈
  // 방지). 단, history 로드가 실패해서 빈 것이라면 idle/결함 분간이 불가하니
  // 패널을 띄워 에러 배너로 가시화한다 (무음 무시 시 패널 자체가 사라져
  // 사각지대가 됐던 문제 해소).
  if (nodes.length === 0 && !data?.session_id && !histError) return null

  // 헤더는 PropertyGroup(Properties/Labels/Meta 와 동일 블록)에 위임 — title
  // 은 그대로 "AI Activity". 우측 action 슬롯엔 live/idle·확대만
  // 둬 한 줄 유지. elapsed/last·진행 펄스는 본문 상단 얇은 줄로 내린다
  // (헤더에 다 쑤셔넣어 두 줄로 깨지던 문제 해소).
  const headerAction = (
    <span className="flex items-center gap-1.5">
      {data?.active
        ? <Badge variant="success" className="text-2xs">live</Badge>
        : <Badge variant="ghost" className="text-2xs">idle</Badge>}
      {nodes.length > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="p-0.5 text-text-tertiary hover:text-text transition-colors"
          title="Enlarge"
        >
          <Maximize2 size={12} />
        </button>
      )}
    </span>
  )

  return (
    <PropertyGroup title="AI Activity" action={headerAction}>
      {histError && (
        <div className="flex items-start gap-1.5 rounded border border-error/40 bg-error/10 px-2 py-1 text-xs text-error">
          <AlertTriangle size={11} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1 break-words">
            <span className="font-medium">과거 이력 로드 실패</span>
            <span className="ml-1 text-text-secondary">— {histError}</span>
          </span>
        </div>
      )}
      {(data?.active || data?.last_seen) && (
        <div className="flex items-center gap-2 px-1 text-2xs text-text-tertiary">
          <Activity
            size={11}
            className={data?.active ? 'text-success animate-pulse' : 'text-text-tertiary'}
          />
          {data?.started_at && data.active && (
            <span className="tabular-nums text-text-secondary">{elapsedLabel(data.started_at, now)}</span>
          )}
          {data?.last_seen && (
            <span className="tabular-nums">last {relativeTime(data.last_seen)}</span>
          )}
        </div>
      )}
      {currentLabel && (
        <div className="flex items-center gap-1.5 rounded bg-accent/10 px-2 py-1 text-xs text-accent-text">
          <Loader2 size={11} className="shrink-0 animate-spin" />
          <span className="font-medium shrink-0">Now</span>
          <span className="truncate min-w-0 text-text-secondary">{currentLabel}</span>
        </div>
      )}
      {nodes.length > 0 && (
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="max-h-96 overflow-y-auto rounded border border-border-subtle bg-bg-hover/20 px-2 py-1"
        >
          {histHasMore && (
            <div className="py-1 text-center text-2xs text-text-tertiary">
              위로 스크롤해 이전 기록 더 보기…
            </div>
          )}
          <NodeList nodes={nodes} />
        </div>
      )}
      <Modal open={expanded} onClose={() => setExpanded(false)} title="AI Activity" size="wide">
        {histError && (
          <div className="mb-2 flex items-start gap-1.5 rounded border border-error/40 bg-error/10 px-2 py-1 text-xs text-error">
            <AlertTriangle size={11} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1 break-words">
              <span className="font-medium">과거 이력 로드 실패</span>
              <span className="ml-1 text-text-secondary">— {histError}</span>
            </span>
          </div>
        )}
        {currentLabel && (
          <div className="mb-2 flex items-center gap-1.5 rounded bg-accent/10 px-2 py-1 text-xs text-accent-text">
            <Loader2 size={11} className="shrink-0 animate-spin" />
            <span className="font-medium shrink-0">Now</span>
            <span className="truncate min-w-0 text-text-secondary">{currentLabel}</span>
          </div>
        )}
        {histHasMore && (
          <div className="pb-2 text-center text-2xs text-text-tertiary">
            (더 과거는 사이드바 패널에서 위로 스크롤해 로드)
          </div>
        )}
        <div
          ref={modalScrollRef}
          onScroll={onModalScroll}
          className="max-h-[70vh] overflow-y-auto rounded border border-border-subtle bg-bg-hover/20 px-2 py-1"
        >
          <NodeList nodes={nodes} detailed />
        </div>
      </Modal>
    </PropertyGroup>
  )
}
