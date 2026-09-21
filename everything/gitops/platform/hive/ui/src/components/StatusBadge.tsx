import { Badge } from '@/components/ui/badge'
import {
  STATUS_BADGE, STATUS_LABEL,
  CONTAINER_STATUS_BADGE, CONTAINER_STATUS_LABEL,
} from '@/lib/status'
import type { AnyStatus, ContainerStatus, EntityStatus, StatusKind } from '@/lib/types'

export function StatusBadge({ status, kind = 'issue' }: { status: AnyStatus; kind?: StatusKind }) {
  if (kind === 'container') {
    const s = status as ContainerStatus
    return <Badge variant={CONTAINER_STATUS_BADGE[s]}>{CONTAINER_STATUS_LABEL[s]}</Badge>
  }
  const s = status as EntityStatus
  return <Badge variant={STATUS_BADGE[s]}>{STATUS_LABEL[s]}</Badge>
}
