import { Lock } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

/**
 * agent-loop 자동 픽업이 차단된(hold=true) entity 표식.
 * 리스트 행·상세 헤더에서 status 옆에 노출해 "수동 보류 중"임을 한눈에 보이게 한다.
 */
export function HoldBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex shrink-0 ${className}`}
      title="agent-loop 자동 픽업 차단됨. 해제 전까지 워커가 진행하지 않음."
    >
      <Badge variant="warning" className="gap-1">
        <Lock size={10} />
        HOLD
      </Badge>
    </span>
  )
}
