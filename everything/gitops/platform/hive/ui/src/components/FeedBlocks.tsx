import { useEffect, useRef, useState } from 'react'
import {
  Pencil, Reply, Trash2, ArrowUp, Paperclip,
  Activity, ArrowRightLeft, Send, OctagonAlert,
} from 'lucide-react'
import { Markdown } from '@/components/Markdown'
import { StatusIcon } from '@/components/StatusIcon'
import { OwnerAvatar } from '@/components/OwnerAvatar'
import { useAuth } from '@/contexts/AuthContext'
import { useToast } from '@/components/ui/toast'
import { relativeTime } from '@/lib/utils'
import { eventAdd, eventUpdateComment, eventDeleteComment } from '@/lib/api'
import { parseOptions, runHandoffAction } from '@/lib/handoffOptions'
import { STATUS_LABEL, CONTAINER_STATUS_LABEL } from '@/lib/status'
import type {
  FeedItem, PrincipalType, EntityStatus, ContainerStatus, AnyStatus, StatusKind, CommentSubtype,
  HandoffOption,
} from '@/lib/types'

export const FIELD_LABELS: Record<string, string> = {
  title: 'title',
  description: 'description',
  plan: 'plan',
}

const PRINCIPAL_DOT: Record<PrincipalType, string> = {
  user: 'var(--color-info)',
  worker: 'var(--color-accent)',
  system: 'var(--color-text-tertiary)',
  cli: 'var(--color-text-tertiary)',
}

function principalEmail(item: { principal_id?: string; principal_type?: PrincipalType }): string | null {
  if (item.principal_type !== 'user' || !item.principal_id) return null
  return item.principal_id.startsWith('user:') ? item.principal_id.slice(5) : item.principal_id
}

function actorLabel(item: FeedItem): string {
  const ptype = item.principal_type
  const pid = item.principal_id
  if (ptype && pid) {
    const stripped = pid.startsWith(`${ptype}:`) ? pid.slice(ptype.length + 1) : pid
    if (ptype === 'user') return stripped.split('@')[0]
    return `${ptype}:${stripped}`
  }
  return 'system'
}

function actorDotColor(item: FeedItem): string {
  const ptype = item.principal_type
  if (ptype) return PRINCIPAL_DOT[ptype] ?? 'var(--color-text-tertiary)'
  return 'var(--color-text-tertiary)'
}

// comment 내부 subtype의 시각 메타. discussion(기본)은 배지 없음.
const SUBTYPE_META: Record<Exclude<CommentSubtype, 'discussion'>, {
  label: string
  Icon: typeof Activity
  className: string
}> = {
  progress: { label: 'progress', Icon: Activity, className: 'bg-info/10 text-info' },
  transition: { label: 'transition', Icon: ArrowRightLeft, className: 'bg-text-tertiary/15 text-text-secondary' },
  handoff: { label: 'handoff', Icon: Send, className: 'bg-success/10 text-success' },
  halt: { label: 'halt', Icon: OctagonAlert, className: 'bg-error/10 text-error' },
}

function SubtypeBadge({ subtype }: { subtype: CommentSubtype }) {
  if (subtype === 'discussion') return null
  const meta = SUBTYPE_META[subtype]
  if (!meta) return null
  const { Icon, label, className } = meta
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-2xs font-medium ${className}`}
      title={`comment subtype: ${label}`}
    >
      <Icon size={10} />
      {label}
    </span>
  )
}

/** payload dict를 간단한 key/value 블록으로 렌더. URL 값은 링크화.
 *  handoff/halt 의 `options` 는 OptionsRow 가 별도로 버튼으로 렌더하므로 여기서는 숨긴다. */
function PayloadBlock({ payload }: { payload: Record<string, unknown> }) {
  const entries = Object.entries(payload).filter(
    ([k, v]) => k !== 'options' && v !== null && v !== undefined && v !== '',
  )
  if (entries.length === 0) return null
  return (
    <div className="mt-2 rounded border border-border-subtle bg-bg-elevated/40 px-3 py-2 text-xs space-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-2">
          <span className="text-text-tertiary font-medium shrink-0">{k}</span>
          <span className="text-text-secondary break-all">{renderPayloadValue(v)}</span>
        </div>
      ))}
    </div>
  )
}

// ── Handoff options (인라인 원클릭 버튼) ───────────────────────────────────
// handoff/halt 코멘트의 `payload.options[]` 를 본문 아래 버튼 row 로 렌더. 워커가
// 채우지 않으면 빈 배열이라 row 자체가 나오지 않음 — 하위 호환. 파싱·실행 helper 는
// `@/lib/handoffOptions` (ActivityFeed 의 단축키 hook 과 공유).

const OPTION_TONE_BTN: Record<NonNullable<HandoffOption['tone']>, string> = {
  primary: 'border-accent/60 bg-accent/10 text-accent hover:bg-accent/20',
  danger: 'border-error/60 bg-error/10 text-error hover:bg-error/20',
  default: 'border-border bg-bg-elev hover:bg-bg-elev-hover text-text',
}

interface OptionsRowProps {
  options: HandoffOption[]
  entityType: 'project' | 'issue' | 'initiative'
  entityId: string
  parentEventId: string
  onRefetch: () => void
  onError?: (message: string) => void
}

function OptionsRow({ options, entityType, entityId, parentEventId, onRefetch, onError }: OptionsRowProps) {
  // 클릭 즉시 시각 피드백 — async 가 끝날 때까지 모든 버튼 disabled + opacity 변경, 선택한 버튼에 spinner.
  // 중복 입력 차단(ref) + sync state(submittingIdx) 둘 다.
  const [submittingIdx, setSubmittingIdx] = useState<number | null>(null)
  const submittingRef = useRef(false)
  async function execute(opt: HandoffOption, idx: number) {
    if (submittingRef.current) return
    submittingRef.current = true
    setSubmittingIdx(idx)
    try {
      await runHandoffAction(opt.action, { entityType, entityId, parentEventId })
      onRefetch()
    } catch (e) {
      onError?.(`옵션 실행 실패 (${opt.label}): ${(e as Error).message}`)
    } finally {
      submittingRef.current = false
      setSubmittingIdx(null)
    }
  }
  const busy = submittingIdx !== null
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {options.map((opt, idx) => {
        const isSelf = submittingIdx === idx
        const isOther = busy && !isSelf
        return (
          <button
            key={`${opt.label}-${idx}`}
            type="button"
            disabled={busy}
            onClick={() => void execute(opt, idx)}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${OPTION_TONE_BTN[opt.tone ?? 'default']} ${isOther ? 'opacity-40' : ''} ${busy ? 'cursor-wait' : 'cursor-pointer'} disabled:hover:bg-inherit`}
          >
            {isSelf && (
              <span className="inline-block h-3 w-3 rounded-full border-2 border-current border-r-transparent animate-spin" />
            )}
            <span>{opt.label}</span>
            {opt.key && (
              <kbd className="rounded border border-current/30 px-1 py-px text-[10px] opacity-70">
                {opt.key.toUpperCase()}
              </kbd>
            )}
          </button>
        )
      })}
    </div>
  )
}

function renderPayloadValue(v: unknown): React.ReactNode {
  if (typeof v === 'string') {
    if (/^https?:\/\//.test(v)) {
      return <a href={v} target="_blank" rel="noreferrer" className="text-info hover:underline">{v}</a>
    }
    return v
  }
  if (Array.isArray(v)) {
    return (
      <span className="space-x-1">
        {v.map((item, i) => (
          <span key={i} className="inline-block">
            {typeof item === 'object' ? JSON.stringify(item) : String(item)}
            {i < v.length - 1 ? ',' : ''}
          </span>
        ))}
      </span>
    )
  }
  if (typeof v === 'object' && v !== null) return <code className="font-mono">{JSON.stringify(v)}</code>
  return String(v)
}

export interface FeedBlockProps {
  item: FeedItem
  entityType: 'project' | 'issue' | 'initiative'
  entityId: string
  replies?: FeedItem[]
  replyMap?: Map<string, FeedItem[]>
  onRefetch: () => void
  hoveredSession: string | null
  onSessionHover: (sessionId: string | null) => void
  /** 활성(미답변) handoff/halt ask 의 event_id. 그 ask 만 live 옵션 버튼을 보인다. */
  activeAskId?: string
}

export function FeedBlock(props: FeedBlockProps) {
  const { item, entityType, entityId, replies, replyMap, onRefetch, hoveredSession, onSessionHover, activeAskId } = props
  const sid = item.session_id
  const sessionActive = sid ? hoveredSession === sid : false

  if (item.kind === 'comment') {
    return (
      <CommentItem
        item={item}
        entityType={entityType}
        entityId={entityId}
        replies={replies ?? []}
        replyMap={replyMap}
        onRefetch={onRefetch}
        activeAskId={activeAskId}
      />
    )
  }

  return (
    <EventLine item={item} entityType={entityType} sid={sid} sessionActive={sessionActive} onSessionHover={onSessionHover} />
  )
}

interface EventLineProps {
  item: FeedItem
  entityType: 'project' | 'issue' | 'initiative'
  sid?: string
  sessionActive: boolean
  onSessionHover: (sessionId: string | null) => void
}

/** 한 줄짜리 비-comment 이벤트 (status_change·field_change). */
function EventLine({ item, entityType, sid, sessionActive, onSessionHover }: EventLineProps) {
  const sessionRing = sessionActive ? 'bg-bg-elevated' : ''

  const wrapper = (children: React.ReactNode) => (
    <div
      onMouseEnter={() => sid && onSessionHover(sid)}
      onMouseLeave={() => sid && onSessionHover(null)}
      className={`flex items-center gap-2 py-1 rounded transition-colors ${sessionRing}`}
    >
      {children}
    </div>
  )

  if (item.kind === 'status_change') {
    const data = item.data as Record<string, unknown>
    // Project·Initiative 는 container 4상태, Issue 는 8상태 — entityType 으로 라벨·아이콘 표 선택.
    const statusKind: StatusKind = entityType === 'issue' ? 'issue' : 'container'
    const from = data.from as AnyStatus | undefined
    const to = data.to as AnyStatus | undefined
    const label = (s: AnyStatus) =>
      statusKind === 'container'
        ? CONTAINER_STATUS_LABEL[s as ContainerStatus] ?? s
        : STATUS_LABEL[s as EntityStatus] ?? s
    return wrapper(
      <>
        {to && <StatusIcon status={to} size={14} kind={statusKind} />}
        <span className="text-xs text-text-secondary leading-relaxed flex items-baseline gap-1 flex-1 min-w-0">
          <span className="font-medium text-text">{actorLabel(item)}</span>
          <span>moved {from && to ? `from ${label(from)} to ${label(to)}` : 'status'}</span>
          <span className="text-text-tertiary">·</span>
          <span className="text-text-tertiary tabular-nums">{relativeTime(item.ts)}</span>
        </span>
      </>,
    )
  }

  if (item.kind === 'field_change') {
    const data = item.data as Record<string, unknown>
    const fieldName = FIELD_LABELS[data.field as string] ?? (data.field as string)
    return wrapper(
      <>
        <Pencil size={13} className="text-text-tertiary shrink-0" />
        <span className="text-xs text-text-secondary leading-relaxed flex items-baseline gap-1 flex-1 min-w-0">
          <span className="font-medium text-text">{actorLabel(item)}</span>
          <span>updated {fieldName}</span>
          <span className="text-text-tertiary">·</span>
          <span className="text-text-tertiary tabular-nums">{relativeTime(item.ts)}</span>
        </span>
      </>,
    )
  }

  // fallback
  return wrapper(
    <span className="text-xs text-text-tertiary">
      {actorLabel(item)} · {item.kind} · {relativeTime(item.ts)}
    </span>,
  )
}

// ── Comment block ──────────────────────────────────────────────────────────

interface CommentItemProps {
  item: FeedItem
  entityType: 'project' | 'issue' | 'initiative'
  entityId: string
  replies: FeedItem[]
  /** 전체 reply tree. 자식 reply 가 자기 손자 reply 를 찾을 때 사용. */
  replyMap?: Map<string, FeedItem[]>
  onRefetch: () => void
  isReply?: boolean
  /** 활성(미답변) handoff/halt ask 의 event_id. 이 코멘트가 그 ask 일 때만 ask 버튼을 live 로 렌더. */
  activeAskId?: string
}

function CommentItem({ item, entityType, entityId, replies, replyMap, onRefetch, isReply, activeAskId }: CommentItemProps) {
  const { user } = useAuth()
  const toast = useToast()
  const text = (item.data?.text as string) ?? ''
  const subtype = ((item.data?.subtype as CommentSubtype) ?? 'discussion')
  const payload = (item.data?.payload as Record<string, unknown> | undefined) ?? null
  const email = principalEmail(item)
  const label = email ? (user?.email === email ? 'Me' : email.split('@')[0]) : actorLabel(item)
  const isMine = !!email && user?.email === email

  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(text)
  const [replyOpen, setReplyOpen] = useState(false)
  const [replyText, setReplyText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const saveEdit = async () => {
    const next = editText.trim()
    if (!next || next === text) {
      setEditing(false)
      return
    }
    setSubmitting(true)
    try {
      await eventUpdateComment({
        entity_type: entityType, entity_id: entityId,
        target_event_id: item.event_id, text: next,
      })
      setEditing(false)
      onRefetch()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const removeComment = async () => {
    if (!confirm('이 코멘트를 삭제할까요?')) return
    setSubmitting(true)
    try {
      await eventDeleteComment({
        entity_type: entityType, entity_id: entityId,
        target_event_id: item.event_id,
      })
      onRefetch()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const submitReply = async () => {
    const next = replyText.trim()
    if (!next) return
    setSubmitting(true)
    try {
      await eventAdd({
        entity_type: entityType, entity_id: entityId,
        text: next, parent_event_id: item.event_id,
      })
      setReplyText('')
      setReplyOpen(false)
      onRefetch()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card shadow-card overflow-hidden group">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-5 pt-3.5">
        {email ? (
          <OwnerAvatar email={email} size="sm" />
        ) : (
          <span
            className="inline-flex items-center justify-center h-5 w-5 rounded-full text-2xs font-medium shrink-0 text-white"
            style={{ backgroundColor: actorDotColor(item) }}
          >
            {label[0]?.toUpperCase()}
          </span>
        )}
        <span className="text-sm font-medium text-text">{label}</span>
        <SubtypeBadge subtype={subtype} />
        <span className="text-xs text-text-tertiary tabular-nums">{relativeTime(item.ts)}</span>
        {item.edited_at && (
          <span className="text-xs text-text-tertiary italic" title={`edited ${relativeTime(item.edited_at)}`}>
            (edited)
          </span>
        )}
        {!editing && (
          <div className="ml-auto flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <IconButton title="Reply" onClick={() => setReplyOpen((v) => !v)}>
              <Reply size={14} />
            </IconButton>
            {isMine && (
              <>
                <IconButton title="Edit" onClick={() => { setEditing(true); setEditText(text) }}>
                  <Pencil size={14} />
                </IconButton>
                <IconButton title="Delete" onClick={removeComment} variant="danger">
                  <Trash2 size={14} />
                </IconButton>
              </>
            )}
          </div>
        )}
      </div>

      {/* Body / edit */}
      <div className={editing ? 'px-5 pb-4 pt-2.5' : 'px-5 pb-4 pt-2'}>
        {editing ? (
          <InlineComposer
            value={editText}
            onChange={setEditText}
            onCancel={() => setEditing(false)}
            onSubmit={saveEdit}
            submitting={submitting}
            submitLabel="Save"
            autoFocus
          />
        ) : (
          <>
            {text && <Markdown className="text-sm text-text leading-relaxed">{text}</Markdown>}
            {payload && <PayloadBlock payload={payload} />}
            {payload && (() => {
              // handoff/halt 의 ask 버튼 + done 의 후속 create 버튼 — options 있으면 subtype 무관 렌더.
              const opts = parseOptions(payload.options)
              if (opts.length === 0) return null
              // 이미 답변된 ask 의 재클릭 방지 — handoff/halt 버튼은 활성(미답변) ask 일 때만 live.
              // (키보드 단축키의 findActiveAsk 가드와 동일 정책.) done 후속 create 등 비-ask options 는 항상 렌더.
              const isAsk = subtype === 'handoff' || subtype === 'halt'
              if (isAsk && item.event_id !== activeAskId) return null
              return (
                <OptionsRow
                  options={opts}
                  entityType={entityType}
                  entityId={entityId}
                  parentEventId={item.event_id}
                  onRefetch={onRefetch}
                  onError={(m) => toast.error(m)}
                />
              )
            })()}
          </>
        )}
      </div>

      {/* Replies — 손자 reply 까지 재귀로 표시. depth 는 카드 중첩으로 자연스럽게 드러남. */}
      {replies.length > 0 && (
        <div className="border-t border-border-subtle bg-bg-elevated/40 px-5 py-3.5 space-y-2.5">
          {replies.map((reply) => (
            <CommentItem
              key={reply.event_id}
              item={reply}
              entityType={entityType}
              entityId={entityId}
              replies={replyMap?.get(reply.event_id) ?? []}
              replyMap={replyMap}
              onRefetch={onRefetch}
              activeAskId={activeAskId}
              isReply
            />
          ))}
        </div>
      )}

      {/* Reply composer
          - top-level: 큰 ReplyTrigger 박스 + 클릭 시 InlineComposer
          - reply 카드: 헤더 hover Reply 아이콘 → 클릭 시 InlineComposer 만 (시각 노이즈 톤다운) */}
      {(replyOpen || !isReply) && (
        <div className="border-t border-border-subtle">
          {replyOpen ? (
            <div className="px-5 py-3.5">
              <InlineComposer
                value={replyText}
                onChange={setReplyText}
                onCancel={() => { setReplyOpen(false); setReplyText('') }}
                onSubmit={submitReply}
                submitting={submitting}
                placeholder="Leave a reply…"
                submitLabel="Reply"
                autoFocus
                leadingAvatar={user?.email ? (
                  <OwnerAvatar email={user.email} size="sm" />
                ) : (
                  <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-text-tertiary/20 shrink-0" />
                )}
              />
            </div>
          ) : (
            <ReplyTrigger email={user?.email ?? null} onOpen={() => setReplyOpen(true)} />
          )}
        </div>
      )}
    </div>
  )
}

function ReplyTrigger({ email, onOpen }: { email: string | null; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full flex items-center gap-2.5 px-5 py-3.5 text-left hover:bg-bg-hover transition-colors"
    >
      {email ? (
        <OwnerAvatar email={email} size="sm" />
      ) : (
        <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-text-tertiary/20 shrink-0" />
      )}
      <span className="text-sm text-text-tertiary">Leave a reply…</span>
    </button>
  )
}

function IconButton({
  children, title, onClick, variant = 'default',
}: {
  children: React.ReactNode
  title: string
  onClick: () => void
  variant?: 'default' | 'danger'
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`p-1.5 rounded-md transition-colors ${
        variant === 'danger'
          ? 'text-text-tertiary hover:text-error hover:bg-error/10'
          : 'text-text-tertiary hover:text-text hover:bg-bg-hover'
      }`}
    >
      {children}
    </button>
  )
}

interface InlineComposerProps {
  value: string
  onChange: (v: string) => void
  onCancel: () => void
  onSubmit: () => void
  submitting: boolean
  placeholder?: string
  submitLabel: string
  autoFocus?: boolean
  /** textarea 좌측에 함께 보이는 leading 노드 (예: avatar). 비우면 textarea 만 렌더. */
  leadingAvatar?: React.ReactNode
}

export function InlineComposer({
  value, onChange, onCancel, onSubmit, submitting, placeholder, submitLabel, autoFocus, leadingAvatar,
}: InlineComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 마운트 시 + value 변경 시 컨텐츠 높이에 맞게 자동 리사이즈.
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = ta.scrollHeight + 'px'
  }, [value])

  const textarea = (
    <textarea
      ref={textareaRef}
      value={value}
      onChange={(e) => {
        onChange(e.target.value)
        e.target.style.height = 'auto'
        e.target.style.height = e.target.scrollHeight + 'px'
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
          e.preventDefault()
          onSubmit()
        } else if (e.key === 'Escape') {
          onCancel()
        }
      }}
      placeholder={placeholder}
      rows={1}
      autoFocus={autoFocus}
      className="flex-1 w-full bg-transparent text-sm text-text placeholder:text-text-tertiary focus:outline-none resize-none overflow-hidden leading-relaxed"
    />
  )

  return (
    <div className="space-y-2.5">
      {leadingAvatar ? (
        <div className="flex items-start gap-2.5">
          {leadingAvatar}
          {textarea}
        </div>
      ) : textarea}
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          className="p-1.5 text-text-tertiary hover:text-text rounded-md hover:bg-bg-hover transition-colors"
          title="Attach"
          aria-label="Attach"
        >
          <Paperclip size={14} />
        </button>
        <span className="text-xs text-text-tertiary">⌘↵ Send · Esc Cancel</span>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="px-2.5 py-1 text-xs text-text-tertiary hover:text-text rounded-md hover:bg-bg-hover transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!value.trim() || submitting}
            className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-accent text-white hover:bg-accent/90 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title={`${submitLabel} (⌘↵)`}
            aria-label={submitLabel}
          >
            <ArrowUp size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}

// 호환 export
export function sessionColor(id: string): string {
  const SESSION_COLORS = [
    '#6366f1', '#f59e0b', '#10b981', '#8b5cf6',
    '#ec4899', '#06b6d4', '#f97316', '#14b8a6',
  ]
  const tail = id.length > 12 ? id.slice(-12) : id
  let h = 0
  for (let i = 0; i < tail.length; i++) h = ((h << 5) - h + tail.charCodeAt(i)) | 0
  return SESSION_COLORS[Math.abs(h) % SESSION_COLORS.length]
}

