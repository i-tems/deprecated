import { StatusIcon } from '@/components/StatusIcon'
import { INITIATIVE_STATUS_LABEL } from '@/lib/initiative'
import type { InitiativeStatus } from '@/lib/types'

// Initiative status 는 Project 과 동일한 container 모델 — 아이콘·라벨은 container 정의를 공유.
interface InitiativeStatusIconProps {
  status: InitiativeStatus
  size?: number
  className?: string
}

export function InitiativeStatusIcon({ status, size = 14, className = '' }: InitiativeStatusIconProps) {
  return (
    <span title={INITIATIVE_STATUS_LABEL[status]} className="inline-flex">
      <StatusIcon status={status} size={size} className={className} kind="container" />
    </span>
  )
}

interface InitiativeStatusRowProps {
  status: InitiativeStatus
  size?: number
}

export function InitiativeStatusRow({ status, size = 13 }: InitiativeStatusRowProps) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <InitiativeStatusIcon status={status} size={size} />
      <span className="text-xs text-text">{INITIATIVE_STATUS_LABEL[status]}</span>
    </span>
  )
}
