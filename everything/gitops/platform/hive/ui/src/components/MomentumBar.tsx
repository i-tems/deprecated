import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Zap, Target, ListTodo, History } from 'lucide-react'
import { CellBadge } from '@/components/CellBadge'
import { StatusBadge } from '@/components/StatusBadge'
import { usePollingGate } from '@/hooks/usePollingGate'
import { appendCellTo } from '@/hooks/useCellAwareTo'
import { issueListAll, projectListAll, workerListActive } from '@/lib/api'
import { relativeTime } from '@/lib/utils'
import type { Issue, Project, EntityStatus, ContainerStatus } from '@/lib/types'

/**
 * Momentum — Deck(지금 할 일)과 Inbox(알림) 사이의 패널. 두 블록을 세로 리스트로 보여준다:
 *   · 지금 일하는 중 — Agent(워커)가 *실제로 코드를 도는 중*인 Issue.
 *     판정 = live heartbeat(worker.list_active, TTL 30s) ∩ issue.status ∈ {running, cleanup}.
 *   · 오늘 변경 — 오늘 코멘트/상태전이/필드변경이 있었던 Issue/Project (지금 일하는 중은 위 블록에
 *     따로 있으니 제외). done 도 "오늘 변경"의 한 종류라 같은 리스트에 담고 status badge 로 구분한다.
 *
 * "오늘 변경" 은 effective activity(max(last_activity_ts, updated_at)) 기준 — 코멘트만 달려
 * updated_at 이 안 움직인 항목도 잡으려고 hub activity_since 필터를 쓴다. hub 가 아직 그 필터를
 * 모르는 배포 순서면(param 무시) updated_at desc 로 와도 client isToday 가드가 오늘로 좁힌다.
 * 한계: heartbeat record 는 issue_id 만 → Project 워커는 live 에서 빠짐(실제 코드는 Issue 워커가 돈다).
 */

const PHASE_LABEL: Record<string, string> = {
  bootstrap: '준비 중', claude_run: '실행 중', publish: '반영 중', post_dispatch: '마무리',
}

interface WorkRow { id: string; title: string; to: string; cell?: string; phase?: string; since?: string }
interface ChangeRow { id: string; title: string; to: string; cell?: string; kind: 'issue' | 'project'; ts: string; status: EntityStatus | ContainerStatus }

const activityTs = (e: { last_activity_ts?: string | null; updated_at: string }): string =>
  e.last_activity_ts ?? e.updated_at

const isToday = (iso: string | undefined, now: number): boolean => {
  if (!iso) return false
  const d = new Date(iso), n = new Date(now)
  return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate()
}

const issueTo = (t: Issue) => appendCellTo(`/issues/${t.issue_id}`, t.cell_id ?? null) as string
const projectTo = (g: Project) => appendCellTo(`/projects/${g.project_id}`, g.cell_id ?? null) as string

export function MomentumBar() {
  // useCallback 필수 — 인라인 fetcher 는 매 렌더 새 identity 라 usePolling effect 가
  // 매 렌더 재실행되며 무한 refetch 루프(hub stampede)를 만든다. 반응형 의존성 없음.
  const fetcher = useCallback(async () => {
    const now = Date.now()
    const start = new Date(now); start.setHours(0, 0, 0, 0)
    const since = start.toISOString() // 로컬 오늘 0시의 instant — hub activity_since 필터.

    const [run, chIss, chProj] = await Promise.all([
      issueListAll({ statuses: ['running', 'cleanup'], limit: 60 }),  // live 매핑용 (활동 무관)
      issueListAll({ activity_since: since, limit: 150 }),            // 오늘 변경된 Issue(전 status)
      projectListAll({ activity_since: since, limit: 150 }),          // 오늘 변경된 Project(전 status)
    ])

    // 지금 일하는 중: 활성 Issue 가 있는 cell 마다 worker.list_active fan-out → heartbeat ∩ running/cleanup.
    const cells = [...new Set(run.issues.map((t) => t.cell_id).filter(Boolean))] as string[]
    const lists = await Promise.all(cells.map((c) => workerListActive(c).catch(() => ({ workers: [] }))))
    const byId = new Map(run.issues.map((t) => [t.issue_id, t]))
    const seen = new Set<string>()
    const working: WorkRow[] = []
    for (const w of lists.flatMap((l) => l.workers)) {
      if (!w.issue_id || seen.has(w.issue_id)) continue
      const t = byId.get(w.issue_id)
      if (!t) continue // heartbeat 살아있어도 이슈가 이미 running/cleanup 이 아님(넘기고 마무리 중) → 제외.
      seen.add(w.issue_id)
      working.push({
        id: w.issue_id, title: t.title, to: issueTo(t), cell: t.cell_id,
        phase: w.phase ?? undefined, since: w.started_at ?? w.last_seen ?? undefined,
      })
    }
    const liveIds = new Set(working.map((w) => w.id))

    const tsDesc = <T extends { ts: string }>(a: T, b: T) => b.ts.localeCompare(a.ts)

    // 오늘 변경 = 오늘 활동 ∩ (지금 일하는 중 아님) — done 도 포함하고 status badge 로 구분.
    const changedToday: ChangeRow[] = [
      ...chIss.issues.filter((t) => !liveIds.has(t.issue_id) && isToday(activityTs(t), now))
        .map((t): ChangeRow => ({ id: t.issue_id, title: t.title, to: issueTo(t), cell: t.cell_id, kind: 'issue', ts: activityTs(t), status: t.status })),
      ...chProj.filter((g) => isToday(activityTs(g), now))
        .map((g): ChangeRow => ({ id: g.project_id, title: g.title, to: projectTo(g), cell: g.cell_id, kind: 'project', ts: activityTs(g), status: g.status })),
    ].sort(tsDesc)

    return { working, changedToday }
  }, [])

  const { data } = usePollingGate(fetcher, 5000)
  const d = data ?? { working: [], changedToday: [] }

  return (
    <div className="space-y-2">
      <Block icon={Zap} iconClass="text-warning" label="지금 일하는 중" count={d.working.length} tone="warning" live empty="지금 도는 워커 없음" maxH="28vh">
        {d.working.map((r) => (
          <Row key={r.id} to={r.to}>
            <Zap size={13} className="shrink-0 text-warning" />
            {r.cell && <CellBadge cellId={r.cell} />}
            <span className="text-sm truncate flex-1 min-w-0">{r.title}</span>
            {r.phase && (
              <span className="shrink-0 text-2xs px-1.5 py-px rounded-full bg-warning/15 text-warning whitespace-nowrap">
                {PHASE_LABEL[r.phase] ?? r.phase}
              </span>
            )}
            <TimeCell ts={r.since} />
          </Row>
        ))}
      </Block>

      <Block icon={History} iconClass="text-info" label="오늘 변경" count={d.changedToday.length} tone="info" empty="오늘 변경 없음" maxH="32vh">
        {d.changedToday.map((r) => (
          <Row key={`${r.kind}:${r.id}`} to={r.to}>
            <KindIcon kind={r.kind} />
            {r.cell && <CellBadge cellId={r.cell} />}
            <span className="text-sm truncate flex-1 min-w-0">{r.title}</span>
            <StatusBadge status={r.status} kind={r.kind === 'project' ? 'container' : 'issue'} />
            <TimeCell ts={r.ts} />
          </Row>
        ))}
      </Block>
    </div>
  )
}

function Block({
  icon: Icon, iconClass, label, count, tone, live = false, empty, maxH, children,
}: {
  icon: typeof Zap; iconClass: string; label: string; count: number
  tone: 'warning' | 'info'; live?: boolean; empty: string; maxH: string; children: React.ReactNode
}) {
  const pill = tone === 'warning' ? 'bg-warning/15 text-warning' : 'bg-info/15 text-info'
  return (
    <section className="rounded-md border border-border-subtle/60 bg-bg-subtle/20 p-2 space-y-1">
      <div className="flex items-center gap-2 px-0.5">
        <Icon size={15} className={`shrink-0 ${iconClass}`} />
        <h2 className="text-sm font-medium shrink-0">{label}</h2>
        <span className={`shrink-0 text-2xs tabular-nums px-1.5 py-px rounded-full ${pill}`}>{count}</span>
        {live && count > 0 && (
          <span className="shrink-0 h-1.5 w-1.5 rounded-full bg-warning animate-pulse" title="워커 작업 중" />
        )}
      </div>
      {count === 0
        ? <p className="px-1.5 py-1 text-xs text-text-quaternary">{empty}</p>
        : <div className="overflow-y-auto" style={{ maxHeight: maxH }}>{children}</div>}
    </section>
  )
}

function Row({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="group flex items-center gap-2 px-1.5 py-1.5 rounded-md hover:bg-bg-hover transition-colors">
      {children}
    </Link>
  )
}

function KindIcon({ kind }: { kind: 'issue' | 'project' }) {
  return kind === 'project'
    ? <Target size={13} className="shrink-0 text-project" />
    : <ListTodo size={13} className="shrink-0 text-issue" />
}

function TimeCell({ ts }: { ts?: string }) {
  if (!ts) return null
  return (
    <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-12 text-right whitespace-nowrap">
      {relativeTime(ts)}
    </span>
  )
}
