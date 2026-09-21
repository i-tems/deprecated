import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
import { PropertyGroup } from '@/components/PropertyRow'
import { InitiativePickerPill } from '@/components/InitiativePickerPill'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import { useToast } from '@/components/ui/toast'
import { initiativeList } from '@/lib/api'
import type { Initiative } from '@/lib/types'

interface InitiativePropertyGroupProps {
  initiativeId: string | null | undefined
  onChange: (initiativeId: string | null) => Promise<void> | void
  title?: string
  // 지정 시 이 id 와 그 하위 트리 전체를 picker 에서 제외 — initiative 의 parent 선택에서
  // 자기 자신·후손을 고르면 순환이 되므로(hub 가 거부) UI 에서 미리 거른다.
  excludeDescendantsOf?: string
}

// id 와 그 하위 트리 전체 id 집합 (자기 자신 포함).
function descendantIds(rootId: string, all: Initiative[]): Set<string> {
  const childrenOf = new Map<string, string[]>()
  for (const i of all) {
    if (!i.parent_initiative_id) continue
    const arr = childrenOf.get(i.parent_initiative_id) ?? []
    arr.push(i.initiative_id)
    childrenOf.set(i.parent_initiative_id, arr)
  }
  const out = new Set<string>([rootId])
  const stack = [rootId]
  while (stack.length) {
    for (const child of childrenOf.get(stack.pop()!) ?? []) {
      if (!out.has(child)) { out.add(child); stack.push(child) }
    }
  }
  return out
}

// Initiative 표시·편집 사이드바 그룹. picker pill 이 항상 노출되므로 선택·변경·
// clear (dropdown "No initiative") 가 모두 같은 트리거로 작동한다. 선택된 initiative
// 가 있으면 옆에 작은 화살표 아이콘으로 detail 페이지 링크. Project 의 소속 Initiative
// 선택과 Initiative 자신의 parent 선택(title="Parent") 양쪽에서 재사용.
export function InitiativePropertyGroup({ initiativeId, onChange, title = 'Initiative', excludeDescendantsOf }: InitiativePropertyGroupProps) {
  const toast = useToast()
  const toCell = useCellAwareTo()
  const [initiatives, setInitiatives] = useState<Initiative[] | null>(null)

  useEffect(() => {
    initiativeList({ parent_initiative_id: '__all__' })
      .then(setInitiatives)
      .catch((e) => toast.error(`Initiative 목록 로드 실패: ${(e as Error).message}`))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const excluded = excludeDescendantsOf && initiatives
    ? descendantIds(excludeDescendantsOf, initiatives)
    : null

  // 완료·보관(terminal)은 picker 에서 제외하되, 이미 연결된 항목은 유지해 노출.
  // excludeDescendantsOf 지정 시 자기 자신·후손도 제외 (순환 방지).
  const pickerInitiatives = initiatives === null
    ? null
    : initiatives.filter(
        (i) =>
          ((i.status !== 'done' && i.status !== 'archive') || i.initiative_id === initiativeId)
          && !excluded?.has(i.initiative_id),
      )

  return (
    <PropertyGroup title={title}>
      <div className="px-1 py-1 flex items-center gap-1.5">
        <InitiativePickerPill
          initiatives={pickerInitiatives}
          value={initiativeId ?? ''}
          onChange={(next) => { void onChange(next === '' ? null : next) }}
        />
        {initiativeId && (
          <Link
            to={toCell(`/initiatives/${initiativeId}`)}
            className="p-1 text-text-tertiary hover:text-text rounded hover:bg-bg-hover transition-colors"
            title="Open initiative"
          >
            <ArrowUpRight size={12} />
          </Link>
        )}
      </div>
    </PropertyGroup>
  )
}
