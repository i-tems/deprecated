import { cn } from '@/lib/utils'
import type { LucideIcon } from 'lucide-react'

interface IconButtonProps {
  icon: LucideIcon
  onClick: () => void
  /** active=true이면 bg-bg-hover로 강조 (토글 활성 표현) */
  active?: boolean
  title?: string
  size?: number
}

/** Linear-style 아이콘 버튼. toolbar 토글 / 헤더 액션 등 공통 사용. */
export function IconButton({ icon: Icon, onClick, active = false, title, size = 14 }: IconButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        'rounded-md p-1.5 transition-colors',
        active
          ? 'bg-bg-hover text-text'
          : 'text-text-tertiary hover:bg-bg-hover hover:text-text',
      )}
    >
      <Icon size={size} />
    </button>
  )
}
