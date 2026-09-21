import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

interface PropertyItemProps {
  /** 좌측 작은 아이콘 (lucide 등) */
  icon: ReactNode
  /** 우측 텍스트 또는 노드 */
  children: ReactNode
  /** 비어 있는 placeholder 표시 ('Set priority' 등) */
  empty?: boolean
  onClick?: () => void
  className?: string
  title?: string
}

/** Linear sidebar item: 작은 아이콘 + 값 한 줄. 라벨 컬럼 없음. */
export function PropertyItem({ icon, children, empty, onClick, className = '', title }: PropertyItemProps) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      title={title}
      className={`w-full flex items-center gap-2 min-h-[28px] px-1 py-1 rounded transition-colors text-left ${
        onClick ? 'hover:bg-bg-hover cursor-pointer' : ''
      } ${className}`}
    >
      <span className="shrink-0 inline-flex items-center justify-center w-4 h-4">{icon}</span>
      <span className={`flex-1 min-w-0 text-sm ${empty ? 'text-text-tertiary' : 'text-text'}`}>
        {children}
      </span>
    </Tag>
  )
}

interface PropertyGroupProps {
  title: string
  children: ReactNode
  /** 기본은 펼쳐진 상태. */
  defaultOpen?: boolean
  /** 우측 + 같은 액션 버튼 슬롯 */
  action?: ReactNode
  className?: string
}

/** Linear sidebar group: disclosure 헤더 + 그룹 박스. */
export function PropertyGroup({ title, children, defaultOpen = true, action, className = '' }: PropertyGroupProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`rounded-md border border-border bg-card shadow-card ${className}`}>
      <div className="flex items-center px-2 py-1.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-xs font-medium text-text-secondary hover:text-text transition-colors"
        >
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <span>{title}</span>
        </button>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {open && <div className="px-1.5 pb-1.5 space-y-0.5">{children}</div>}
    </div>
  )
}

interface MetaRowProps {
  label: string
  children: ReactNode
}

/** Meta 정보용 라벨+값 행 (작은 폰트). 헤더가 아닌 일반 정보 표시. */
export function MetaRow({ label, children }: MetaRowProps) {
  return (
    <div className="flex items-center min-h-[22px] gap-3 px-1">
      <span className="w-[88px] shrink-0 text-2xs text-text-tertiary">{label}</span>
      <div className="flex-1 min-w-0 text-xs text-text-secondary">{children}</div>
    </div>
  )
}

// 기존 import 호환
export const PropertyRow = MetaRow
export const PropertyValue = ({ children, className = '' }: { children: ReactNode; className?: string }) => (
  <div className={`flex items-center gap-1.5 min-w-0 ${className}`}>{children}</div>
)
