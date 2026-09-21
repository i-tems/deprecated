import { Server, Briefcase, User, Sparkles, Atom, Pen, Box } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

// Linear team identifier 스타일 — 아이콘 글리프만 cell 별 고유 컬러, 배경은 무채색.
// 모르는 cell 은 letter+muted fallback (Linear 새 팀 기본).
//
// 색상은 Linear 처럼 미디엄 채도 (text-X-600 dark:text-X-400) — 충분히 구분되되
// 컬러 블록 처럼 화려하지 않다.

interface CellMeta {
  icon: LucideIcon
  color: string  // tailwind text-color class (light + dark)
}

const CELL_META: Record<string, CellMeta> = {
  infra:  { icon: Server,    color: 'text-cyan-600 dark:text-cyan-400' },
  items:  { icon: Briefcase, color: 'text-indigo-600 dark:text-indigo-400' },
  ness:   { icon: User,      color: 'text-rose-600 dark:text-rose-400' },
  beauty: { icon: Sparkles,  color: 'text-amber-600 dark:text-amber-400' },
  mci:    { icon: Atom,      color: 'text-violet-600 dark:text-violet-400' },
  pen:    { icon: Pen,       color: 'text-slate-600 dark:text-slate-400' },
}

interface CellBadgeProps {
  cellId: string
  size?: number  // 아이콘·박스 변. 기본 14 — 사이드바·행 모두 호환.
  className?: string
}

export function CellBadge({ cellId, size = 14, className }: CellBadgeProps) {
  const meta = CELL_META[cellId]
  if (meta) {
    const Icon = meta.icon
    return (
      <span
        title={cellId}
        className={cn('inline-flex shrink-0 items-center justify-center', meta.color, className)}
        style={{ width: size, height: size }}
      >
        <Icon size={Math.round(size * 0.86)} />
      </span>
    )
  }
  // unknown cell, 너무 작은 사이즈면 letter 가독성 떨어져 Box 아이콘 fallback.
  if (size < 11) {
    return (
      <span
        title={cellId}
        className={cn('inline-flex shrink-0 items-center justify-center text-text-secondary', className)}
        style={{ width: size, height: size }}
      >
        <Box size={Math.round(size * 0.86)} />
      </span>
    )
  }
  // 첫 글자 letter fallback. muted 박스 안 1자.
  return (
    <span
      title={cellId}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-sm bg-bg-subtle text-text-secondary font-medium uppercase leading-none',
        className,
      )}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.6) }}
    >
      {cellId[0] ?? '?'}
    </span>
  )
}
