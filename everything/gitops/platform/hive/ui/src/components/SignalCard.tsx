import { forwardRef } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { Markdown } from '@/components/Markdown'
import { SignalActions, type SignalActionKey } from '@/components/SignalActions'
import { SignalRaw } from '@/components/SignalRaw'
import { StatusBadge } from '@/components/StatusBadge'
import { PriorityIcon, valueToLevel, PRIORITY_COLOR, type PriorityLevel } from '@/components/PriorityPicker'
import { SIGNAL_STATUS_COLOR, SIGNAL_STATUS_LABEL } from '@/lib/status'
import { formatDate, relativeTime, cn } from '@/lib/utils'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import type { Signal, EntityMap } from '@/lib/types'

interface SignalCardProps {
  signal: Signal
  entityMap: EntityMap
  onAction: (key: SignalActionKey) => void
  highlighted?: boolean
}

const PRIORITY_LABEL: Record<PriorityLevel, string> = {
  urgent: 'Urgent',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  none: 'No priority',
}

/** Signals 피드 카드. Linear Issues 톤 — strip 없음, header pill 단순화, footer 통합. */
export const SignalCard = forwardRef<HTMLElement, SignalCardProps>(function SignalCard(
  { signal, entityMap, onAction, highlighted },
  ref,
) {
  const level = valueToLevel(signal.priority)
  const projectId = signal.project_id ?? undefined
  const issueId = signal.issue_id ?? undefined
  const sessionId = signal.session_id ?? undefined
  const toCell = useCellAwareTo()
  const hasLinks = projectId || issueId || sessionId

  return (
    <article
      ref={ref}
      className={cn(
        'rounded-lg border border-border-subtle bg-bg-subtle transition-colors hover:border-border',
        highlighted && 'ring-2 ring-accent border-accent',
      )}
    >
      {/* header — priority icon · type · status dot · signal_id · time */}
      <header className="flex items-center gap-2 px-3 pt-2.5 pb-1.5 flex-wrap">
        {level !== 'none' && (
          <span
            className={cn('shrink-0 inline-flex items-center', PRIORITY_COLOR[level])}
            title={PRIORITY_LABEL[level]}
          >
            <PriorityIcon level={level} size={12} />
          </span>
        )}

        <span className="text-xs font-semibold text-text-secondary">{signal.type}</span>

        <span className="inline-flex items-center gap-1 text-[11px] text-text-tertiary">
          <span className={cn('inline-block w-1.5 h-1.5 rounded-full', SIGNAL_STATUS_COLOR[signal.status])} />
          {SIGNAL_STATUS_LABEL[signal.status]}
        </span>

        <span className="ml-auto text-xs font-mono text-text-tertiary tabular-nums shrink-0">
          {signal.signal_id}
        </span>

        <span
          className="text-xs text-text-tertiary tabular-nums shrink-0"
          title={formatDate(signal.ts_emitted)}
        >
          {relativeTime(signal.ts_emitted)}
        </span>
      </header>

      {/* body */}
      <div className="px-3 pb-2.5 space-y-2">
        {signal.title && (
          <h3 className="text-base font-semibold text-text leading-snug break-words">
            {signal.title}
          </h3>
        )}

        {signal.description && (
          <div className="text-sm text-text-secondary leading-relaxed">
            <Markdown className="break-words">{signal.description}</Markdown>
          </div>
        )}

        {signal.raw && <SignalRaw raw={signal.raw} />}

        {hasLinks && (
          <div className="flex flex-col gap-1 text-xs">
            {projectId && (
              <Link
                to={toCell(`/projects/${projectId}`)}
                className="flex items-center gap-2 text-text-tertiary hover:text-text transition-colors"
              >
                <span className="w-12 shrink-0 text-text-quaternary">Project</span>
                {entityMap[projectId] ? (
                  <>
                    <StatusBadge status={entityMap[projectId].status} />
                    <span className="text-accent truncate">{entityMap[projectId].title}</span>
                  </>
                ) : (
                  <span className="text-accent font-mono truncate">{projectId}</span>
                )}
              </Link>
            )}
            {issueId && (
              <Link
                to={toCell(`/issues/${issueId}`)}
                className="flex items-center gap-2 text-text-tertiary hover:text-text transition-colors"
              >
                <span className="w-12 shrink-0 text-text-quaternary">Issue</span>
                {entityMap[issueId] ? (
                  <>
                    <StatusBadge status={entityMap[issueId].status} />
                    <span className="text-accent truncate">{entityMap[issueId].title}</span>
                  </>
                ) : (
                  <span className="text-accent font-mono truncate">{issueId}</span>
                )}
              </Link>
            )}
            {sessionId && (
              <Link
                to={toCell(`/sessions/${sessionId}`)}
                className="flex items-center gap-2 text-text-tertiary hover:text-text transition-colors"
              >
                <span className="w-12 shrink-0 text-text-quaternary">Session</span>
                <span className="font-mono text-accent truncate">{sessionId.slice(0, 12)}</span>
              </Link>
            )}
          </div>
        )}

        {signal.history.length > 0 && (
          <details className="group">
            <summary className="text-xs text-text-tertiary cursor-pointer hover:text-text-secondary inline-flex items-center gap-1 select-none">
              <ChevronRight size={10} className="group-open:rotate-90 transition-transform" />
              History · {signal.history.length}
            </summary>
            <div className="mt-1.5 space-y-0.5 text-xs">
              {signal.history.map((h, i) => (
                <div key={i} className="flex items-center gap-2 text-text-tertiary">
                  <span className="tabular-nums">{formatDate(h.ts)}</span>
                  <span className="text-text-secondary">{h.status}</span>
                  {h.by && <span>· {h.by}</span>}
                  {h.note && <span className="text-text-secondary">· {h.note}</span>}
                </div>
              ))}
            </div>
          </details>
        )}

        {/* actions inline at body bottom — 별도 footer/구분선 없음 */}
        <div className="pt-0.5">
          <SignalActions currentStatus={signal.status} onAction={onAction} layout="inline" />
        </div>
      </div>
    </article>
  )
})
