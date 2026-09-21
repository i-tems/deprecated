import { Link } from 'react-router-dom'
import { GitBranch, Signal } from 'lucide-react'
import { StatusIcon } from '@/components/StatusIcon'
import { PropertyGroup, PropertyItem } from '@/components/PropertyRow'
import { useCellAwareTo } from '@/hooks/useCellAwareTo'
import type { DepDetail } from '@/lib/api'

/**
 * Project/Issue detail 사이드바의 "Dependencies" 블록.
 * dependency id 를 issue/project 로 resolve 한 [[depDetails]] 를 받아 링크와 status 를 노출.
 * blocked = 의존 대상이 미해결(done/cancelled 아님) 인 경우 노란색.
 */
export function DependenciesGroup({
  dependencies,
  depDetails,
}: {
  dependencies: string[] | undefined
  depDetails: DepDetail[] | undefined
}) {
  const toCell = useCellAwareTo()
  if (!dependencies || dependencies.length === 0) return null
  return (
    <PropertyGroup title="Dependencies">
      {dependencies.map((d) => {
        const det = depDetails?.find((x) => x.id === d)
        const target = det?.kind === 'project' ? `/projects/${d}` : det?.kind === 'issue' ? `/issues/${d}` : null
        const blocked = det && !det.satisfied
        const icon = det?.status
          ? <StatusIcon status={det.status} size={12} kind={det.kind === 'project' ? 'container' : 'issue'} />
          : <GitBranch size={12} className="text-text-tertiary" />
        const body = (
          <span className={`truncate ${blocked ? 'text-warning' : ''}`}>
            {det?.title ?? <code className="font-mono text-2xs text-text-secondary">{d}</code>}
          </span>
        )
        return (
          <PropertyItem key={d} icon={icon}>
            {target ? <Link to={toCell(target)} className="hover:underline">{body}</Link> : body}
          </PropertyItem>
        )
      })}
    </PropertyGroup>
  )
}

/**
 * Project/Issue detail 사이드바의 "Signals" 블록.
 * 엔티티가 어떤 source signal 들로부터 파생됐는지 (focus 쿼리로 Signals 페이지 점프).
 */
export function SourceSignalsGroup({ signalIds }: { signalIds: string[] | undefined }) {
  const toCell = useCellAwareTo()
  if (!signalIds || signalIds.length === 0) return null
  return (
    <PropertyGroup title="Signals" defaultOpen={false}>
      {signalIds.map((sid) => (
        <Link
          key={sid}
          to={toCell(`/signals?focus=${sid}`)}
          className="flex items-center gap-2 min-h-[28px] px-1 py-1 rounded hover:bg-bg-hover transition-colors"
        >
          <Signal size={12} className="text-text-tertiary shrink-0" />
          <code className="font-mono text-2xs text-text-secondary">{sid}</code>
        </Link>
      ))}
    </PropertyGroup>
  )
}
