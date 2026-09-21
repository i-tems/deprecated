import { useEffect, useState, useMemo, useRef } from 'react'
import { ArrowUp, Paperclip, ChevronRight } from 'lucide-react'
import { FeedBlock } from '@/components/FeedBlocks'
import { parseOptions, runHandoffAction } from '@/lib/handoffOptions'
import { OwnerAvatar } from '@/components/OwnerAvatar'
import { useAuth } from '@/contexts/AuthContext'
import { useToast } from '@/components/ui/toast'
import { eventAdd } from '@/lib/api'
import type { FeedItem, CommentSubtype, PrincipalType } from '@/lib/types'

interface ActivityFeedProps {
  entityType: 'project' | 'issue' | 'initiative'
  entityId: string
  feed: FeedItem[]
  onRefetch: () => void
}

// 텍스트 입력 중에는 단축키 무시 — useDetailShortcuts 와 동일 정책.
function isTypingTarget(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null
  if (!t) return false
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable
}

// 활성 ask = 가장 최근 handoff/halt 코멘트 + 그 이후 user 댓글 없음 (= 아직 처리되지 않은 요청).
// 단축키는 이 활성 ask 의 options 만 등록 — 피드 안 다른 (이미 처리된) handoff 와 충돌 회피.
function findActiveAsk(feed: FeedItem[]): FeedItem | undefined {
  const comments = feed.filter((i) => i.kind === 'comment')
  let ask: FeedItem | undefined
  for (const c of comments) {
    const s = (c.data as { subtype?: CommentSubtype }).subtype
    if ((s === 'handoff' || s === 'halt') && (!ask || c.ts > ask.ts)) ask = c
  }
  if (!ask) return undefined
  if (comments.some((c) => (c.principal_type as PrincipalType | undefined) === 'user' && c.ts > ask!.ts)) {
    return undefined
  }
  return ask
}

// 워커 실행 자취(상태/필드 이벤트 + progress 코멘트)는 muted lane 으로 접는다.
// 사람 토론·transition(종결 결과 요약)·handoff·halt 는 primary 로 그대로 둔다.
// 데이터(kind·subtype)만으로 분류 — reply 트리·activeAsk 로직과 독립.
function isMutedRow(item: FeedItem): boolean {
  if (item.kind === 'status_change' || item.kind === 'field_change') return true
  if (item.kind === 'comment') {
    return ((item.data as { subtype?: CommentSubtype }).subtype ?? 'discussion') === 'progress'
  }
  return false
}

type FeedRow = { kind: 'primary'; item: FeedItem } | { kind: 'muted'; items: FeedItem[] }

// 연속한 muted item 을 하나의 cluster 로 묶는다 — 원래 순서 보존.
function groupFeedRows(topLevel: FeedItem[]): FeedRow[] {
  const rows: FeedRow[] = []
  for (const item of topLevel) {
    if (isMutedRow(item)) {
      const last = rows[rows.length - 1]
      if (last && last.kind === 'muted') last.items.push(item)
      else rows.push({ kind: 'muted', items: [item] })
    } else {
      rows.push({ kind: 'primary', item })
    }
  }
  return rows
}

interface MutedClusterProps {
  items: FeedItem[]
  entityType: 'project' | 'issue' | 'initiative'
  entityId: string
  replyMap: Map<string, FeedItem[]>
  onRefetch: () => void
  hoveredSession: string | null
  onSessionHover: (sessionId: string | null) => void
  activeAskId?: string
}

// 접히는 워커 실행 자취 묶음. 기본 접힘 — 사람 뷰는 깨끗, 펼치면 전체 자취.
function MutedCluster({ items, entityType, entityId, replyMap, onRefetch, hoveredSession, onSessionHover, activeAskId }: MutedClusterProps) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-1 py-0.5 text-xs text-text-tertiary hover:text-text-secondary transition-colors"
      >
        <ChevronRight size={13} className={`transition-transform ${open ? 'rotate-90' : ''}`} />
        {items.length} worker update{items.length > 1 ? 's' : ''}
      </button>
      {open && (
        <div className="mt-1 ml-2 pl-3 border-l border-border-subtle space-y-1.5">
          {items.map((it) => (
            <FeedBlock
              key={it.event_id}
              item={it}
              entityType={entityType}
              entityId={entityId}
              replies={replyMap.get(it.event_id)}
              replyMap={replyMap}
              onRefetch={onRefetch}
              hoveredSession={hoveredSession}
              onSessionHover={onSessionHover}
              activeAskId={activeAskId}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function ActivityFeed({ entityType, entityId, feed, onRefetch }: ActivityFeedProps) {
  const toast = useToast()
  const { user } = useAuth()
  const [commentText, setCommentText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // setSubmitting 은 비동기 render — ⌘↵ 빠른 2회·키 repeat·클릭+키 race 에 약함.
  // sync ref 로 동일 핸들러 재진입을 즉시 차단 (button disabled 보조).
  const submittingRef = useRef(false)
  const [hoveredSession, setHoveredSession] = useState<string | null>(null)

  // Build reply tree: separate top-level events from comment replies.
  // Orphaned replies (parent deleted/missing) are promoted to top-level so they're not lost.
  const { topLevel, replyMap } = useMemo(() => {
    const ids = new Set(feed.map((i) => i.event_id))
    const replyMap = new Map<string, FeedItem[]>()
    const topLevel: FeedItem[] = []
    for (const item of feed) {
      if (item.kind === 'comment') {
        const parent = (item.data as Record<string, unknown>)?.parent_event_id as string | undefined
        if (parent && ids.has(parent)) {
          if (!replyMap.has(parent)) replyMap.set(parent, [])
          replyMap.get(parent)!.push(item)
          continue
        }
      }
      topLevel.push(item)
    }
    for (const list of replyMap.values()) {
      list.sort((a, b) => (a.ts > b.ts ? 1 : -1))
    }
    return { topLevel, replyMap }
  }, [feed])

  const rows = useMemo(() => groupFeedRows(topLevel), [topLevel])

  // 활성 ask 의 options 단축키 — 클릭만큼 즉시. 입력창 focus·수정자 조합엔 비활성.
  const activeAsk = useMemo(() => findActiveAsk(feed), [feed])
  useEffect(() => {
    if (!activeAsk) return
    const payload = (activeAsk.data as { payload?: unknown }).payload
    if (!payload || typeof payload !== 'object') return
    const options = parseOptions((payload as Record<string, unknown>).options)
    if (options.length === 0) return
    const keyMap = new Map<string, typeof options[number]>()
    for (const o of options) if (o.key) keyMap.set(o.key, o)
    if (keyMap.size === 0) return

    let busy = false
    function handler(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (isTypingTarget(e.target)) return
      const opt = keyMap.get(e.key.toLowerCase())
      if (!opt || busy) return
      e.preventDefault()
      busy = true
      runHandoffAction(opt.action, {
        entityType, entityId, parentEventId: activeAsk!.event_id,
      })
        .then(() => onRefetch())
        .catch((err) => toast.error(`옵션 실행 실패 (${opt.label}): ${(err as Error).message}`))
        .finally(() => { busy = false })
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAsk?.event_id, entityType, entityId, onRefetch])

  const handleAddComment = async () => {
    const text = commentText.trim()
    if (!text || submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    try {
      await eventAdd({ entity_type: entityType, entity_id: entityId, text })
      setCommentText('')
      onRefetch()
    } catch (e) {
      toast.error(`Comment failed: ${(e as Error).message}`)
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-text">Activity</h2>

      {topLevel.length === 0 ? (
        <p className="text-xs text-text-tertiary">No activity yet.</p>
      ) : (
        <div className="space-y-2.5">
          {rows.map((row) =>
            row.kind === 'muted' ? (
              <MutedCluster
                key={`muted-${row.items[0].event_id}`}
                items={row.items}
                entityType={entityType}
                entityId={entityId}
                replyMap={replyMap}
                onRefetch={onRefetch}
                hoveredSession={hoveredSession}
                onSessionHover={setHoveredSession}
                activeAskId={activeAsk?.event_id}
              />
            ) : (
              <FeedBlock
                key={row.item.event_id}
                item={row.item}
                entityType={entityType}
                entityId={entityId}
                replies={replyMap.get(row.item.event_id)}
                replyMap={replyMap}
                onRefetch={onRefetch}
                hoveredSession={hoveredSession}
                onSessionHover={setHoveredSession}
                activeAskId={activeAsk?.event_id}
              />
            ),
          )}
        </div>
      )}

      {/* Comment composer — Linear style */}
      <div className="rounded-lg bg-bg">
        <div className="flex items-start gap-2.5 px-5 pt-4 pb-2">
          {user?.email ? (
            <OwnerAvatar email={user.email} size="sm" />
          ) : (
            <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-text-tertiary/20 shrink-0" />
          )}
          <textarea
            data-kb="comment"
            value={commentText}
            onChange={(e) => {
              setCommentText(e.target.value)
              e.target.style.height = 'auto'
              e.target.style.height = e.target.scrollHeight + 'px'
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.repeat) {
                e.preventDefault()
                handleAddComment()
              } else if (e.key === 'Escape') {
                setCommentText('')
                ;(e.target as HTMLTextAreaElement).blur()
              }
            }}
            placeholder="Leave a comment…"
            rows={1}
            className="flex-1 bg-transparent text-sm text-text placeholder:text-text-tertiary focus:outline-none focus-visible:outline-none resize-none overflow-hidden py-0.5 leading-relaxed"
          />
        </div>
        <div className="flex items-center gap-1.5 px-3 py-2">
          <button
            type="button"
            className="p-1.5 text-text-tertiary hover:text-text rounded-md hover:bg-bg-hover transition-colors"
            title="Attach"
            aria-label="Attach"
          >
            <Paperclip size={14} />
          </button>
          <span className="text-xs text-text-tertiary">⌘↵ Send · Markdown supported</span>
          <button
            type="button"
            disabled={!commentText.trim() || submitting}
            onClick={handleAddComment}
            className="ml-auto inline-flex items-center justify-center w-7 h-7 rounded-full bg-accent text-white hover:bg-accent/90 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            aria-label="Send comment"
            title="Send (⌘↵)"
          >
            <ArrowUp size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
