import { Check, X, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'
import type { SignalStatus } from '@/lib/types'

type ActionKey = 'consumed' | 'dismissed' | 'emitted'

interface ActionDef {
  key: ActionKey
  icon: LucideIcon
  label: string
  /** Tailwind text color */
  tone: string
  /** Tailwind hover bg */
  hoverBg: string
  /** 이 액션이 노출되는 currentStatus 집합 ('all' = 자기 자신 제외 모두) */
  visibleFor: 'active' | 'done' | 'all'
}

const ACTIVE_LIKE = new Set<SignalStatus>(['emitted'])

const ACTIONS: ActionDef[] = [
  // Reopen: 종료 상태(consumed/dismissed) 에서만 노출
  { key: 'emitted',   icon: RotateCcw, label: 'Reopen',  tone: 'text-warning',        hoverBg: 'hover:bg-warning/10', visibleFor: 'done' },
  // 종료 액션들: 자기 자신 제외 모든 상태에서 노출. consumed=Issue/Project 로 흡수, dismissed=처리 불필요
  { key: 'consumed',  icon: Check,     label: 'Consume', tone: 'text-success',        hoverBg: 'hover:bg-success/10', visibleFor: 'all' },
  { key: 'dismissed', icon: X,         label: 'Dismiss', tone: 'text-text-tertiary',  hoverBg: 'hover:bg-bg-hover',   visibleFor: 'all' },
]

interface SignalActionsProps {
  currentStatus: SignalStatus
  onAction: (key: ActionKey) => void
  /** rail = 좌측 세로 아이콘만 / inline = 라벨 포함 가로 버튼 (모바일 expanded용) */
  layout: 'rail' | 'inline'
}

export function SignalActions({ currentStatus, onAction, layout }: SignalActionsProps) {
  const isActive = ACTIVE_LIKE.has(currentStatus)
  const visible = ACTIONS.filter((a) => {
    if (a.visibleFor === 'done') return !isActive
    return (a.key as string) !== currentStatus
  })

  if (layout === 'rail') {
    return (
      <div className="flex items-center gap-0.5">
        {visible.map(({ key, icon: Icon, label, tone, hoverBg }) => (
          <button
            key={key}
            onClick={(e) => { e.stopPropagation(); onAction(key) }}
            title={label}
            className={cn('p-1.5 rounded-md transition-colors', tone, hoverBg)}
          >
            <Icon size={14} />
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1">
      {visible.map(({ key, icon: Icon, label, tone, hoverBg }) => (
        <button
          key={key}
          onClick={(e) => { e.stopPropagation(); onAction(key) }}
          className={cn('flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors', tone, hoverBg)}
        >
          <Icon size={13} /> {label}
        </button>
      ))}
    </div>
  )
}

export type { ActionKey as SignalActionKey }
