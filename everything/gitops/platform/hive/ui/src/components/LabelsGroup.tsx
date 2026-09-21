import { useMemo, useRef, useState } from 'react'
import { Tag, Plus, X } from 'lucide-react'
import { Popover } from './Popover'
import { KbdHint } from './KbdHint'
import { PropertyGroup, PropertyItem } from './PropertyRow'
import type { Label } from '@/lib/types'

interface LabelBadgeProps {
  label: Label
}

/** hex color dot + 이름. Linear sidebar 의 label 표시와 동일한 톤. */
function LabelBadge({ label }: LabelBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1.5 min-w-0">
      <span
        className="inline-block w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: label.color }}
        aria-hidden
      />
      <span className="truncate">{label.name}</span>
    </span>
  )
}

interface LabelPickerProps {
  /** 현재 선택된 label_id 들 */
  selected: string[]
  /** 셀 전체 label 마스터 */
  allLabels: Label[]
  /** 선택 토글 후 다음 label_id 전체 리스트 */
  onChange: (nextIds: string[]) => void
}

/** PropertyGroup action 슬롯의 "+" 트리거 + 라벨 체크리스트 Popover. PriorityPicker 와 동일 패턴. */
function LabelPicker({ selected, allLabels, onChange }: LabelPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const triggerRef = useRef<HTMLButtonElement>(null)
  const selectedSet = useMemo(() => new Set(selected), [selected])

  const filtered = useMemo(() => {
    const sorted = [...allLabels].sort((a, b) => a.name.localeCompare(b.name))
    const q = query.trim().toLowerCase()
    if (!q) return sorted
    return sorted.filter((l) => l.name.toLowerCase().includes(q))
  }, [allLabels, query])

  const toggle = (labelId: string) => {
    const next = selectedSet.has(labelId)
      ? selected.filter((id) => id !== labelId)
      : [...selected, labelId]
    onChange(next)
  }

  return (
    <>
      <KbdHint k="l" className="mr-1 align-middle" />
      <button
        ref={triggerRef}
        data-kb="labels"
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center justify-center w-5 h-5 rounded hover:bg-bg-hover text-text-tertiary transition-colors"
        title="Add label (l)"
        aria-label="Add label"
      >
        <Plus size={12} />
      </button>

      <Popover
        open={open}
        anchorRef={triggerRef}
        onClose={() => setOpen(false)}
        className="w-64 rounded-md border border-border bg-bg shadow-lg overflow-hidden"
      >
        <div className="p-1.5 border-b border-border-subtle">
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter labels…"
            className="w-full px-2 py-1 text-xs bg-bg-subtle rounded outline-none placeholder:text-text-quaternary"
          />
        </div>
        <ul className="py-1 max-h-64 overflow-y-auto">
          {filtered.length === 0 && (
            <li className="px-2 py-1.5 text-xs text-text-tertiary">
              {allLabels.length === 0 ? 'No labels in this cell' : 'No match'}
            </li>
          )}
          {filtered.map((label) => {
            const isOn = selectedSet.has(label.label_id)
            return (
              <li key={label.label_id}>
                <button
                  type="button"
                  onClick={() => toggle(label.label_id)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-bg-hover transition-colors"
                  title={label.description ?? undefined}
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: label.color }}
                    aria-hidden
                  />
                  <span className="flex-1 truncate">{label.name}</span>
                  {isOn && <span className="text-text-tertiary">✓</span>}
                </button>
              </li>
            )
          })}
        </ul>
      </Popover>
    </>
  )
}

interface LabelsGroupProps {
  /** 엔티티 record 에 들린 label_id 들 */
  labelIds: string[] | undefined
  /** 셀 전체 label 마스터. label_id → 이름·색상 lookup 용 */
  allLabels: Label[]
  /**
   * 라벨 편집 핸들러. 주어지면 picker(추가/제거) 노출, 없으면 읽기 전용.
   * 다음 label_id 전체 리스트를 받는다.
   */
  onChange?: (nextIds: string[]) => void
}

/**
 * Project/Issue sidebar 의 "Labels" 그룹.
 * - onChange 없음(읽기 전용): labelIds 비면 그룹 자체 숨김 (기존 동작 유지).
 * - onChange 있음(편집): 항상 그룹 표시 + "+" picker. 비어있으면 빈 상태 안내.
 */
export function LabelsGroup({ labelIds, allLabels, onChange }: LabelsGroupProps) {
  const ids = labelIds ?? []
  const byId = useMemo(() => new Map(allLabels.map((l) => [l.label_id, l])), [allLabels])
  const resolved = ids.map((id) => byId.get(id)).filter((l): l is Label => Boolean(l))

  if (!onChange) {
    // 읽기 전용 경로 — 기존 컨슈머 호환 (라벨 없으면 숨김).
    if (resolved.length === 0) return null
    return (
      <PropertyGroup title="Labels">
        {resolved.map((label) => (
          <PropertyItem
            key={label.label_id}
            icon={<Tag size={11} style={{ color: label.color }} />}
            title={label.description ?? undefined}
          >
            <LabelBadge label={label} />
          </PropertyItem>
        ))}
      </PropertyGroup>
    )
  }

  const remove = (labelId: string) => onChange(ids.filter((id) => id !== labelId))

  return (
    <PropertyGroup
      title="Labels"
      action={<LabelPicker selected={ids} allLabels={allLabels} onChange={onChange} />}
    >
      {resolved.length === 0 ? (
        <PropertyItem icon={<Tag size={11} className="text-text-tertiary" />} empty>
          No labels
        </PropertyItem>
      ) : (
        resolved.map((label) => (
          <PropertyItem
            key={label.label_id}
            icon={<Tag size={11} style={{ color: label.color }} />}
            title={label.description ?? undefined}
            className="group/label"
          >
            <span className="flex items-center gap-1.5 min-w-0">
              <LabelBadge label={label} />
              <button
                type="button"
                onClick={() => remove(label.label_id)}
                className="ml-auto opacity-0 group-hover/label:opacity-100 text-text-tertiary hover:text-text transition-opacity"
                title="Remove label"
                aria-label={`Remove ${label.name}`}
              >
                <X size={11} />
              </button>
            </span>
          </PropertyItem>
        ))
      )}
    </PropertyGroup>
  )
}
