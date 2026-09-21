import type { ReactElement } from 'react'
import {
  CircleDashed, Circle,
  CircleEllipsis, XCircle, AlertCircle, Sparkles, Archive, PauseCircle,
} from 'lucide-react'
import { STATUS_LABEL, CONTAINER_STATUS_LABEL } from '@/lib/status'
import type { AnyStatus, ContainerStatus, EntityStatus, StatusKind } from '@/lib/types'

/** Linear 스타일 done: 채워진 원 + 흰색 체크 */
function FilledCheckCircle({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="currentColor" />
      <path d="M8 12.5l2.5 2.5L16 9.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Started 카테고리: 외곽선 + 절반 부채꼴 채움 */
function StartedCircle({ size = 14, fillRatio = 0.5 }: { size?: number; fillRatio?: number }) {
  const r = 10
  const startAngle = -90
  const endAngle = startAngle + 360 * fillRatio
  const toRad = (deg: number) => (deg * Math.PI) / 180
  const sx = 12 + r * Math.cos(toRad(startAngle))
  const sy = 12 + r * Math.sin(toRad(startAngle))
  const ex = 12 + r * Math.cos(toRad(endAngle))
  const ey = 12 + r * Math.sin(toRad(endAngle))
  const largeArc = fillRatio > 0.5 ? 1 : 0
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r={r} stroke="currentColor" strokeWidth="2" fill="none" />
      <path
        d={`M 12 12 L ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 1 ${ex} ${ey} Z`}
        fill="currentColor"
      />
    </svg>
  )
}

type IconRenderer = (props: { size?: number }) => ReactElement

interface IconConfig {
  render: IconRenderer
  className: string
}

const STATUS_ICON: Record<EntityStatus, IconConfig> = {
  backlog:   { render: ({ size }) => <CircleDashed size={size} />,    className: 'text-text-tertiary' },
  todo:      { render: ({ size }) => <Circle size={size} />,          className: 'text-text-tertiary' },
  running:   { render: ({ size }) => <StartedCircle size={size} fillRatio={0.5} />, className: 'text-text-secondary' },
  waiting:   { render: ({ size }) => <CircleEllipsis size={size} />,  className: 'text-text-tertiary' },
  cleanup:   { render: ({ size }) => <Sparkles size={size} />,         className: 'text-text-secondary' },
  done:      { render: ({ size }) => <FilledCheckCircle size={size} />, className: 'text-accent' },
  cancelled: { render: ({ size }) => <XCircle size={size} />,         className: 'text-text-tertiary' },
  error:     { render: ({ size }) => <AlertCircle size={size} />,     className: 'text-error' },
}

// Container(Project·Initiative) 5상태 아이콘.
const CONTAINER_STATUS_ICON: Record<ContainerStatus, IconConfig> = {
  backlog: { render: ({ size }) => <CircleDashed size={size} />,                   className: 'text-text-tertiary' },
  active:  { render: ({ size }) => <StartedCircle size={size} fillRatio={0.5} />,  className: 'text-info' },
  waiting: { render: ({ size }) => <PauseCircle size={size} />,                    className: 'text-warning' },
  done:    { render: ({ size }) => <FilledCheckCircle size={size} />,              className: 'text-success' },
  archive: { render: ({ size }) => <Archive size={size} />,                        className: 'text-text-quaternary' },
}

function iconConfig(status: AnyStatus, kind: StatusKind): IconConfig | undefined {
  return kind === 'container'
    ? CONTAINER_STATUS_ICON[status as ContainerStatus]
    : STATUS_ICON[status as EntityStatus]
}

function statusLabel(status: AnyStatus, kind: StatusKind): string {
  return kind === 'container'
    ? CONTAINER_STATUS_LABEL[status as ContainerStatus]
    : STATUS_LABEL[status as EntityStatus]
}

export interface StatusIconProps {
  status: AnyStatus
  size?: number
  className?: string
  /** 'issue'(8상태, 기본) | 'container'(Project·Initiative 4상태) */
  kind?: StatusKind
}

export function StatusIcon({ status, size = 14, className = '', kind = 'issue' }: StatusIconProps) {
  const cfg = iconConfig(status, kind)
  if (!cfg) return null
  return (
    <span className={`shrink-0 inline-flex items-center justify-center ${cfg.className} ${className}`}>
      {cfg.render({ size })}
    </span>
  )
}

interface StatusRowProps {
  status: AnyStatus
  size?: number
  className?: string
  kind?: StatusKind
}

/** 아이콘 + 라벨 한 줄. 헤더·sidebar property 행 등에 사용. */
export function StatusRow({ status, size = 14, className = '', kind = 'issue' }: StatusRowProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <StatusIcon status={status} size={size} kind={kind} />
      <span className="text-xs text-text">{statusLabel(status, kind)}</span>
    </span>
  )
}
