import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { EditableTitle } from '@/components/EditableTitle'
import { IconPickerButton } from '@/components/IconPickerButton'
import { relativeTime, formatDate } from '@/lib/utils'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import type { ReactNode } from 'react'

interface EntityHeaderProps {
  /** 상위 목록 페이지 (/issues, /projects) */
  backTo: string
  backLabel: string
  /** breadcrumb의 추가 노드 (e.g. parent project). 옵션. */
  breadcrumbExtra?: ReactNode
  title: string
  /** entity icon (이모지 등). 있으면 제목 왼쪽에 prefix 로 표시. raw title 과 분리해 inline edit input 에는 섞이지 않음. */
  icon?: string | null
  /** 넘기면 icon 클릭 시 emoji picker 활성화. 미지정이면 read-only icon (또는 미표시). */
  onIconChange?: (next: string | null) => Promise<void> | void
  /** 넘기면 제목 인라인 편집 활성화. 미지정이면 read-only h1. */
  onTitleSave?: (next: string) => Promise<void>
  createdAt: string
  updatedAt: string
  /** 도메인/표기용 짧은 이름 (e.g. "PEN-28"). 전달 시 breadcrumb 옆에 칩으로 노출. */
  shortName?: string | null
  /** breadcrumb 줄 우측 상태 배지 슬롯 (e.g. HOLD). 옵션. */
  headerBadge?: ReactNode
}

/** Linear-style entity 헤더: breadcrumb + 제목 단독 + 날짜 메타 */
export function EntityHeader({
  backTo, backLabel, breadcrumbExtra, title, icon, onIconChange, onTitleSave, createdAt, updatedAt, shortName,
  headerBadge,
}: EntityHeaderProps) {
  const toCell = useCellAwareTo()
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-text-tertiary">
        <Link to={toCell(backTo)} className="inline-flex items-center gap-1 hover:text-text transition-colors">
          <ArrowLeft size={11} /> {backLabel}
        </Link>
        {shortName && (
          <span className="font-mono text-text-secondary tabular-nums">{shortName}</span>
        )}
        {breadcrumbExtra}
        {headerBadge && <span className="ml-auto">{headerBadge}</span>}
      </div>
      <div className="flex items-baseline gap-2">
        {onIconChange
          ? <IconPickerButton icon={icon} onChange={onIconChange} size="lg" />
          : icon && <span className="text-2xl shrink-0 leading-tight">{icon}</span>}
        {onTitleSave
          ? <div className="flex-1 min-w-0"><EditableTitle value={title} onSave={onTitleSave} /></div>
          : <h1 className="text-2xl font-semibold leading-tight flex-1 min-w-0">{title}</h1>}
      </div>
      <div className="flex items-center gap-2 text-xs text-text-tertiary">
        <span>{formatDate(createdAt)}</span>
        <span>·</span>
        <span>updated {relativeTime(updatedAt)}</span>
      </div>
    </div>
  )
}
