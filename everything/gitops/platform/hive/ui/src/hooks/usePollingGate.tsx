import type { ReactNode } from 'react'
import { Spinner } from '@/components/ui/spinner'
import { ErrorState } from '@/components/ErrorState'
import { usePolling, type LiveOptions } from './usePolling'

// usePolling 래퍼 — `loading && !data → <Spinner/>` · `error && !data →
// <ErrorState onRetry=refetch/>` 보일러플레이트를 한 줄 (`if (gate) return
// gate`) 로 줄인다. 8 list/detail 페이지가 동일 2줄을 갖던 것을 통합.
//
// usePolling 자체는 그대로 — sandbox 같은 다른 callers 가 직접 쓰는 경로 유지.
export function usePollingGate<T>(
  fetcher: () => Promise<T>,
  intervalMs = 5000,
  live?: LiveOptions,
) {
  const result = usePolling<T>(fetcher, intervalMs, live)
  const gate: ReactNode | null =
    result.loading && !result.data
      ? <Spinner />
      : result.error && !result.data
        ? <ErrorState error={result.error} onRetry={result.refetch} />
        : null
  return { ...result, gate }
}
