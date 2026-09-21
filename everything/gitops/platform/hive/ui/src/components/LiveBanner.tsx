import { WifiOff } from 'lucide-react'

/**
 * 실시간(SSE) 갱신이 끊겼을 때 페이지 상단에 띄우는 경고 배너.
 * interval 폴링 fallback 을 제거했으므로(usePolling 참고), 끊기면 화면
 * 데이터가 더 이상 자동 갱신되지 않는다는 사실을 명시적으로 알린다.
 * 마지막으로 받은 데이터는 그대로 표시된다.
 */
export function LiveBanner({ stale }: { stale: boolean }) {
  if (!stale) return null
  return (
    <div
      role="status"
      className="mb-3 flex items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
    >
      <WifiOff size={14} className="shrink-0" />
      <span>
        실시간 갱신이 끊겼습니다. 표시된 데이터는 최신이 아닐 수 있습니다 —
        연결이 복구되면 자동으로 갱신됩니다.
      </span>
    </div>
  )
}
