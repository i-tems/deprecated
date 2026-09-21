export function LastUpdated({ date }: { date: Date | null }) {
  if (!date) return null
  return (
    <span className="text-xs text-text-tertiary tabular-nums">
      Last updated {date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
    </span>
  )
}
