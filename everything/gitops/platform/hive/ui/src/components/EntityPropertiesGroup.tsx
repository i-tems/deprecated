import { Lock, LockOpen } from 'lucide-react'
import { StatusPicker } from '@/components/StatusPicker'
import { PriorityPicker } from '@/components/PriorityPicker'
import { AssigneePicker } from '@/components/AssigneePicker'
import { SnoozePicker } from '@/components/SnoozePicker'
import { ModelPicker } from '@/components/ModelPicker'
import type { ModelTier } from '@/components/ModelPicker'
import { PropertyGroup, PropertyItem } from '@/components/PropertyRow'
import type { AnyStatus, StatusKind } from '@/lib/types'

interface EntityPropertiesGroupProps {
  status: AnyStatus
  previousStatus?: AnyStatus | null
  onStatusChange: (status: AnyStatus) => void
  /** 'issue'(8상태, 기본) | 'container'(Project 4상태) */
  statusKind?: StatusKind

  priorityValue: number | null | undefined
  onPriorityChange: (value: number | null) => void

  owner: string | null | undefined
  resolvedOwner?: string | null
  onOwnerChange: (email: string | null) => void

  /** agent-loop 자동 픽업 차단 상태 */
  hold?: boolean
  onHoldChange: (hold: boolean) => void

  /** Triage 큐 시한부 숨김 (metadata.snooze_until). null=꺼짐. */
  snoozeUntil?: Date | null
  onSnoozeChange: (until: Date | null) => void

  /** 워커 모델 tier. 두 prop 모두 있을 때 ModelPicker 렌더. */
  model?: string | null
  onModelChange?: (model: ModelTier | null) => void
}

/** Status / Priority / Assignee / Model / Hold / Snooze picker 묶음. Project·Issue 공용. */
export function EntityPropertiesGroup(props: EntityPropertiesGroupProps) {
  const held = !!props.hold
  return (
    <PropertyGroup title="Properties">
      <div className="px-1 py-1 space-y-1">
        <StatusPicker
          status={props.status}
          previousStatus={props.previousStatus}
          onChange={props.onStatusChange}
          kind={props.statusKind}
        />
        <PriorityPicker
          value={props.priorityValue}
          onChange={props.onPriorityChange}
        />
        <AssigneePicker
          owner={props.owner}
          resolvedOwner={props.resolvedOwner}
          onChange={props.onOwnerChange}
        />
        {props.onModelChange !== undefined && (
          <ModelPicker
            value={props.model}
            onChange={props.onModelChange}
          />
        )}
        <PropertyItem
          icon={held
            ? <Lock size={12} className="text-warning" />
            : <LockOpen size={12} className="text-text-tertiary" />}
          onClick={() => props.onHoldChange(!held)}
          title="agent-loop 자동 픽업 차단 토글. 개인 세션 수동작업 중 켜고, 끝나면 반드시 해제."
          empty={!held}
        >
          {held ? <span className="text-warning font-medium">Hold</span> : 'Hold off'}
        </PropertyItem>
        <SnoozePicker
          until={props.snoozeUntil ?? null}
          onChange={props.onSnoozeChange}
        />
      </div>
    </PropertyGroup>
  )
}
