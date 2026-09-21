import { Link } from 'react-router-dom'
import { OwnerAvatar } from '@/components/OwnerAvatar'
import { StatusSelect } from '@/components/StatusSelect'
import { HoldBadge } from '@/components/HoldBadge'
import { PriorityIcon, valueToLevel, PRIORITY_COLOR } from '@/components/PriorityPicker'
import { relativeTime, entityShortName } from '@/lib/utils'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import type { Issue, Project, EntityStatus } from '@/lib/types'

interface IssueListRowProps {
  issue: Issue
  project?: Project
  onTransition: (status: EntityStatus) => void
  /** Project 라벨을 표시할지 (Project 페이지 안에서는 필요 없음) */
  showGoal?: boolean
}

/** Issues 리스트/그룹/Project 상세에서 공용으로 쓰는 한 줄 issue row (Linear-style 컴팩트) */
export function IssueListRow({ issue, project, onTransition, showGoal = true }: IssueListRowProps) {
  const level = valueToLevel(issue.priority?.value)
  const shortName = entityShortName(issue.issue_id, issue.cell_id, issue.seq)
  const toCell = useCellAwareTo()
  return (
    <Link
      to={toCell(`/issues/${issue.issue_id}`)}
      className="group flex items-center gap-2 px-2 py-1 rounded-md hover:bg-bg-hover transition-colors"
    >
      <span className={`shrink-0 ${PRIORITY_COLOR[level]}`}>
        <PriorityIcon level={level} size={13} />
      </span>
      <StatusSelect
        status={issue.status}
        previousStatus={issue.previous_status}
        onTransition={(s) => onTransition(s as EntityStatus)}
        iconSize={14}
      />
      {issue.hold && <HoldBadge />}
      {shortName && (
        <span className="text-xs text-text-tertiary tabular-nums shrink-0">{shortName}</span>
      )}
      <span className="text-sm truncate flex-1 min-w-0">{issue.title}</span>
      {showGoal && project && (
        <span className="hidden sm:inline text-xs text-text-tertiary truncate shrink-0 max-w-[180px]">
          {project.title}
        </span>
      )}
      <div className="shrink-0 w-5 flex justify-center">
        {issue.resolved_owner ? <OwnerAvatar email={issue.resolved_owner} size="xs" /> : null}
      </div>
      <span className="text-xs text-text-tertiary shrink-0 tabular-nums w-14 text-right whitespace-nowrap">
        {relativeTime(issue.updated_at)}
      </span>
    </Link>
  )
}
