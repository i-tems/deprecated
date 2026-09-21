import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Target, ListTodo, CheckCircle2, Radio, Check, Undo2, Lightbulb } from 'lucide-react'
import { Empty } from '@/components/ui/empty'
import { FilterTabs } from '@/components/FilterTabs'
import { IconButton } from '@/components/IconButton'
import { CellBadge } from '@/components/CellBadge'
import { usePollingGate } from '@/hooks/usePollingGate'
import { appendCellTo } from '@/hooks/useCellAwareTo'
import { useToast } from '@/components/ui/toast'
import { useUrlState } from '@/hooks/useUrlState'
import { inboxListAll, inboxAck, inboxAckAll } from '@/lib/api'
import { notifyInboxSync } from '@/lib/inboxSync'
import { relativeTime } from '@/lib/utils'
import type { InboxItem, InboxStatus } from '@/lib/types'
import type { LucideIcon } from 'lucide-react'

type TabValue = 'unread' | 'read' | 'all'

interface TypeMeta {
  icon: LucideIcon
  label: string
  color: string
  linkPrefix: string
}

const TYPE_META: Record<string, TypeMeta> = {
  'project.done':        { icon: Target,    label: 'Project completed', color: 'text-project',    linkPrefix: '/projects/' },
  'issue.done':        { icon: ListTodo,  label: 'Issue completed', color: 'text-issue',    linkPrefix: '/issues/' },
  'signal.emitted':   { icon: Radio,     label: 'New signal',     color: 'text-signal',  linkPrefix: '/signals' },
  'insight.observed': { icon: Lightbulb, label: 'Insight',        color: 'text-info',    linkPrefix: '/inbox' },
}
const FALLBACK_META: TypeMeta = { icon: Bell, label: 'Notification', color: 'text-text-tertiary', linkPrefix: '/inbox' }

export function InboxPanel() {
  const toast = useToast()
  const navigate = useNavigate()
  const [tab, setTab] = useUrlState<TabValue>('tab', 'unread')

  const fetcher = useCallback(async () => {
    // hub 기본 조회 범위가 "오늘 하루"라(date_store.date_range_paths) 날짜를 안 주면 어제 이전
    // 알림(특히 안읽은 것)이 사라진다. 최근 30일을 명시해 최근 알림이 유지되게 한다.
    const date_from = new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10)
    const params = { date_from, ...(tab === 'all' ? {} : { status: tab }) }
    return await inboxListAll(params)
  }, [tab])

  // user-level aggregate: SSE 는 cell-scoped 라 쓸 수 없음 — 5s interval 폴링.
  const { data, refetch, setData, gate } = usePollingGate(fetcher, 5000)

  const handleToggle = async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation()
    e?.preventDefault()
    setData((prev) => prev?.map((i: InboxItem) =>
      i.inbox_id === id ? { ...i, status: i.status === 'unread' ? 'read' as InboxStatus : 'unread' as InboxStatus } : i
    ) ?? null)
    notifyInboxSync()
    try {
      await inboxAck(id)
    } catch (e) {
      toast.error(`상태 변경 실패: ${(e as Error).message}`)
      notifyInboxSync()
      refetch()
    }
  }

  const handleClick = async (item: InboxItem) => {
    const meta = TYPE_META[item.type] ?? FALLBACK_META
    if (item.status === 'unread') {
      setData((prev) => prev?.map((i: InboxItem) => i.inbox_id === item.inbox_id ? { ...i, status: 'read' as InboxStatus } : i) ?? null)
      notifyInboxSync()
      inboxAck(item.inbox_id).catch(() => {
        notifyInboxSync()
        refetch()
      })
    }
    const path = meta.linkPrefix.endsWith('/') ? `${meta.linkPrefix}${item.ref}` : meta.linkPrefix
    // 행의 cell_id 로 detail 진입 — aggregate 뷰에서는 현재 URL ?cell 이 없으므로
    // 항목 자체 cell_id 를 부착해야 detail 페이지가 그 cell scope 로 동작.
    navigate(appendCellTo(path, item.cell_id ?? null))
  }

  const handleAckAll = async () => {
    setData((prev) => prev?.map((i: InboxItem) => ({ ...i, status: 'read' as InboxStatus })) ?? null)
    notifyInboxSync()
    try {
      const result = await inboxAckAll()
      if (result.acked > 0) toast.success(`${result.acked}건 확인 완료`)
    } catch (e) {
      toast.error(`일괄 확인 실패: ${(e as Error).message}`)
      notifyInboxSync()
      refetch()
    }
  }

  if (gate) return gate
  const items = data ?? []
  const unreadCount = items.filter((i: InboxItem) => i.status === 'unread').length

  const TABS = [
    { value: 'unread' as TabValue, label: `Unread${unreadCount > 0 ? ` ${unreadCount}` : ''}` },
    { value: 'read' as TabValue, label: 'Read' },
    { value: 'all' as TabValue, label: 'All' },
  ]

  return (
    <div className="space-y-2">
      {/* 패널 헤더 — 페이지 제목은 Workspace 가 갖는다. */}
      <div className="flex items-center gap-2 px-1">
        <Bell size={15} className="shrink-0 text-warning" />
        <h2 className="text-sm font-medium shrink-0">알림</h2>
        <div className="flex-1" />
        {unreadCount > 0 && <IconButton icon={CheckCircle2} onClick={handleAckAll} title="모두 확인" />}
      </div>

      <FilterTabs value={tab} onChange={setTab} tabs={TABS} />

      {items.length === 0 ? (
        <Empty
          icon={<Bell size={20} />}
          title={tab === 'unread' ? '새 알림 없음' : '알림 없음'}
        />
      ) : (
        // 높이 고정 — 목록만 내부 스크롤(헤더·탭은 위에 고정). 페이지가 무한정 길어지지 않게.
        <div className="max-h-[42vh] overflow-y-auto">
          {items.map((item: InboxItem) => {
            const meta = TYPE_META[item.type] ?? FALLBACK_META
            const Icon = meta.icon
            const isUnread = item.status === 'unread'
            return (
              <div
                key={item.inbox_id}
                onClick={() => handleClick(item)}
                className="group flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-bg-hover transition-colors cursor-pointer"
              >
                {/* unread indicator dot */}
                <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${isUnread ? 'bg-accent' : 'bg-transparent'}`} />
                {/* type icon */}
                <Icon size={13} className={`shrink-0 ${isUnread ? meta.color : 'text-text-quaternary'}`} />
                {/* cell badge — user-level aggregate 행이 어느 cell 소속인지 */}
                {item.cell_id && <CellBadge cellId={item.cell_id} />}
                {/* type label (작게) */}
                <span className={`text-xs shrink-0 hidden sm:inline ${isUnread ? 'text-text-secondary' : 'text-text-tertiary'}`}>
                  {meta.label}
                </span>
                {/* summary — 전체 폭이라 대개 한 줄에 다 보이고, 길면 줄바꿈해 내용을 전부 노출 */}
                <span className={`text-sm flex-1 min-w-0 break-words ${isUnread ? 'text-text font-medium' : 'text-text-secondary'}`}>
                  {item.summary}
                </span>
                {/* hover: mark as read/unread */}
                <button
                  type="button"
                  onClick={(e) => handleToggle(item.inbox_id, e)}
                  className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity inline-flex items-center justify-center w-6 h-6 rounded text-text-tertiary hover:text-text hover:bg-bg-subtle"
                  title={isUnread ? '읽음 처리' : '안읽음으로 되돌리기'}
                >
                  {isUnread ? <Check size={13} /> : <Undo2 size={13} />}
                </button>
                {/* time */}
                <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-10 text-right">
                  {relativeTime(item.created_at)}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
