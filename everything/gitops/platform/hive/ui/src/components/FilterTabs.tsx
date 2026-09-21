import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'

export interface FilterTab<T extends string> {
  value: T
  label: string
}

interface FilterTabsProps<T extends string> {
  value: T
  onChange: (value: T) => void
  tabs: FilterTab<T>[]
  /** 우측에 추가 컨트롤(정렬, mine 토글 등) */
  trailing?: ReactNode
}

/** Linear-style 알약 필터 탭. 우측에 정렬/필터 아이콘을 trailing으로 함께 배치 */
export function FilterTabs<T extends string>({ value, onChange, tabs, trailing }: FilterTabsProps<T>) {
  return (
    <div className="-mx-4 md:-mx-6 px-4 md:px-6 pb-2 border-b border-border-subtle">
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-0.5 overflow-x-auto pb-0.5 -mb-0.5 flex-1 min-w-0">
          {tabs.map((tab) => {
            const active = tab.value === value
            return (
              <button
                key={tab.value}
                type="button"
                onClick={() => onChange(tab.value)}
                className={cn(
                  'shrink-0 rounded-full px-2.5 py-1 text-sm transition-colors',
                  active
                    ? 'bg-bg-hover text-text font-medium'
                    : 'text-text-secondary hover:bg-bg-hover hover:text-text',
                )}
              >
                {tab.label}
              </button>
            )
          })}
        </div>
        {trailing && <div className="flex items-center gap-1 shrink-0">{trailing}</div>}
      </div>
    </div>
  )
}
