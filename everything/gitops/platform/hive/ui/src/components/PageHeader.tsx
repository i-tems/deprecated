import { LastUpdated } from '@/components/LastUpdated'
import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  /** 작은 카운트/요약. 인라인 회색으로 제목 우측에 표시 */
  subtitle?: string
  icon?: LucideIcon
  iconClass?: string
  lastUpdated?: Date | null
  actions?: ReactNode
}

/** Linear-style 컴팩트 페이지 헤더: 아이콘 + 제목 + (count) | 우측 actions + lastUpdated */
export function PageHeader({ title, subtitle, icon: Icon, iconClass, lastUpdated, actions }: PageHeaderProps) {
  return (
    <div className="-mx-4 md:-mx-6 px-4 md:px-6 pb-3 border-b border-border-subtle">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          {Icon && <Icon size={15} className={cn('shrink-0', iconClass ?? 'text-text-tertiary')} />}
          <h1 className="text-base font-semibold tracking-tight truncate">{title}</h1>
          {subtitle && (
            <span className="text-sm text-text-tertiary tabular-nums truncate">{subtitle}</span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {lastUpdated && <LastUpdated date={lastUpdated} />}
          {actions}
        </div>
      </div>
    </div>
  )
}
