import { PropertyGroup, MetaRow } from '@/components/PropertyRow'
import { relativeTime, formatDate } from '@/lib/utils'
import type { ReactNode } from 'react'
import type { Gates } from '@/lib/types'

interface EntityMetaProps {
  gates?: Gates | null
  createdAt: string
  updatedAt: string
  /** entity ID 라벨 + 값 (e.g. "Issue ID", issue.issue_id) */
  idLabel: string
  idValue: string
  metadata?: Record<string, unknown> | null
  /** Project/Issue가 자기만 가진 row를 끼워 넣을 슬롯 (예: Cadence, Project ID, Parent ID) */
  extraRows?: ReactNode
}

/** Linear-style meta 섹션. gates·dates·ID·metadata. */
export function EntityMeta({
  gates, createdAt, updatedAt, idLabel, idValue, metadata, extraRows,
}: EntityMetaProps) {
  return (
    <PropertyGroup title="Meta">
      {gates?.completion && gates.completion !== 'auto' && (
        <MetaRow label="Completion Gate">{gates.completion}</MetaRow>
      )}
      {extraRows}
      <MetaRow label="Created">{formatDate(createdAt)}</MetaRow>
      <MetaRow label="Updated">{relativeTime(updatedAt)}</MetaRow>
      <MetaRow label={idLabel}>
        <code className="block font-mono text-2xs text-text-secondary truncate" title={idValue}>{idValue}</code>
      </MetaRow>
      {metadata && Object.keys(metadata).length > 0 && (
        <>
          {Object.entries(metadata).map(([k, v]) => (
            <MetaRow key={k} label={k}>{String(v)}</MetaRow>
          ))}
        </>
      )}
    </PropertyGroup>
  )
}
