import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'

export interface Crumb {
  label: string
  href?: string
}

/**
 * Linear-style fixed breadcrumb bar.
 * 사이드바 옆부터 화면 우측 끝까지 가로로 깔림. 사이드바 collapsed 상태는
 * Layout 에서 노출한 --sidebar-w css var 로 동기화.
 *
 * Usage: detail 페이지의 max-width 컨테이너 첫 child 로 두되, 컨테이너에
 * pt-14 (또는 pt-16) 으로 본문이 TopBar 에 가려지지 않게 보정해줘야 한다.
 */
export function TopBar({ crumbs }: { crumbs: Crumb[] }) {
  const toCell = useCellAwareTo()
  return (
    <div
      className="fixed top-0 left-0 right-0 md:left-[var(--sidebar-w,244px)] z-30 h-12 flex items-center gap-1.5 px-4 md:px-6 bg-bg/85 backdrop-blur border-b border-border-subtle text-sm text-text-secondary transition-[left] duration-200"
    >
      {crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1
        return (
          <span key={i} className="flex items-center gap-1.5 min-w-0">
            {i > 0 && <ChevronRight size={12} className="text-text-tertiary shrink-0" />}
            {c.href && !isLast ? (
              <Link to={toCell(c.href)} className="hover:text-text transition-colors truncate">
                {c.label}
              </Link>
            ) : (
              <span className={isLast ? 'font-medium text-text truncate' : 'truncate'}>
                {c.label}
              </span>
            )}
          </span>
        )
      })}
    </div>
  )
}
