import type { ReactNode } from 'react'
import { TopBar } from '@/components/TopBar'
import { EntityHeader } from '@/components/EntityHeader'
import { useCell } from '@/contexts/CellContext'

interface DetailHeaderProps {
  /** workspace 다음 list 페이지 — TopBar 의 두 번째 crumb + EntityHeader back link. */
  list: { label: string; path: string }
  /** entity 타이틀 — TopBar 마지막 crumb 와 EntityHeader 제목 양쪽에 사용. */
  title: string
  /** entity icon (이모지 등). EntityHeader 로 forward — title 왼쪽 prefix. */
  icon?: string | null
  /** 넘기면 icon 클릭 시 emoji picker 활성화. EntityHeader 로 forward. */
  onIconChange?: (next: string | null) => Promise<void> | void
  /** 인라인 편집 활성화 (Initiative 의 name, Project/Issue 의 title). 미지정이면 read-only. */
  onTitleSave?: (next: string) => Promise<void>
  /** parent project · parent initiative · Initiative breadcrumb 등 entity-specific 노드. */
  breadcrumbExtra?: ReactNode
  createdAt: string
  updatedAt: string
  /** 짧은 표시용 ID (e.g. "INFRA-ISSUE-78"). */
  shortName?: string | null
  /** HOLD 배지 등 헤더 우측 상태 슬롯. */
  headerBadge?: ReactNode
}

// 3 detail 페이지 (ProjectDetail · IssueDetail · InitiativeDetail) 의 TopBar +
// EntityHeader 호출이 동일 구조라 추출. cell 컨텍스트는 hook 으로 직접 읽어
// caller boilerplate 도 제거.
export function DetailHeader({
  list, title, icon, onIconChange, onTitleSave, breadcrumbExtra, createdAt, updatedAt, shortName, headerBadge,
}: DetailHeaderProps) {
  const { currentCell } = useCell()
  return (
    <>
      <TopBar
        crumbs={[
          { label: currentCell?.name ?? 'Workspace', href: '/' },
          { label: list.label, href: list.path },
          { label: title },
        ]}
      />
      <EntityHeader
        backTo={list.path}
        backLabel={list.label}
        breadcrumbExtra={breadcrumbExtra}
        title={title}
        icon={icon}
        onIconChange={onIconChange}
        onTitleSave={onTitleSave}
        createdAt={createdAt}
        updatedAt={updatedAt}
        shortName={shortName}
        headerBadge={headerBadge}
      />
    </>
  )
}
