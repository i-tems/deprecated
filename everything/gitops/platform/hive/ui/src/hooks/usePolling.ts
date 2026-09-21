import { useState, useEffect, useCallback, useRef } from 'react'

import { changeStreamUrl } from '../lib/api'

export interface LiveOptions {
  /** SSE 구독 scope. cell(기본) | signals | inbox */
  scopes?: string[]
  /** 더 좁은 entity 단위 구독 (상세 페이지) */
  entityId?: string
}

/**
 * 데이터 fetcher 를 주기적으로 / push 로 갱신한다.
 *
 * - `live` 미지정: 순수 interval 폴링 (기존 동작 그대로 — 비-라이브 호출부
 *   영향 없음). 탭이 hidden 이면 폴링 정지, 복귀 시 재개.
 * - `live` 지정: SSE(`/sse.subscribe`)로만 push 구독한다. **interval 폴링
 *   fallback 은 없다** — mount 시 1회 fetch + SSE `change` 시 refetch +
 *   탭 복귀 시 1회 refetch 가 전부다. SSE 가 establish 되지 않으면 조용히
 *   폴링으로 degrade 하는 대신 `liveStale=true` 로 노출해 페이지가 상단
 *   경고 배너를 띄운다(loud). 마지막 data 는 유지한다. EventSource 의
 *   네이티브 자동 재연결은 그대로 살아 있어 일시적 끊김은 자가 복구된다.
 *   탭 hidden 시 SSE 정지, 복귀 시 재개.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 5000,
  live?: LiveOptions,
) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  // live 호출부에서 SSE 가 끊겨 실시간 갱신이 멈춘 상태. 초기엔 false 라
  // 최초 연결 중에는 배너가 깜빡이지 않고, onerror 후에만 true 가 된다.
  const [liveDown, setLiveDown] = useState(false)
  const mountedRef = useRef(true)

  const refetch = useCallback(async () => {
    try {
      const result = await fetcher()
      if (mountedRef.current) {
        setData(result)
        setError(null)
        setLastUpdated(new Date())
      }
    } catch (e) {
      if (mountedRef.current) setError(e as Error)
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [fetcher])

  // live 옵션을 안정적인 primitive 로 환원 — 인라인 객체 identity 변화로
  // effect 가 재실행되지 않게 한다.
  const liveScopes = live?.scopes?.join(',') ?? ''
  const liveEntityId = live?.entityId ?? ''
  const liveEnabled = !!live

  useEffect(() => {
    mountedRef.current = true
    refetch()

    const isHidden = () =>
      typeof document !== 'undefined' && document.visibilityState === 'hidden'

    // ── live 경로: SSE 전용, interval fallback 없음 ───────────────────────
    if (liveEnabled) {
      const sseSupported =
        typeof window !== 'undefined' && 'EventSource' in window
      const buildUrl = () =>
        sseSupported
          ? changeStreamUrl({
              scopes: liveScopes ? liveScopes.split(',') : undefined,
              entityId: liveEntityId || undefined,
            })
          : null

      let es: EventSource | null = null
      const closeSse = () => {
        if (es) { es.close(); es = null }
      }
      const openSse = () => {
        if (es) return
        const url = buildUrl()
        if (!url) {
          // EventSource 미지원 또는 cell 미정 → 실시간 불가. 폴링으로
          // 숨기지 않고 명시적으로 stale 표시 (loud).
          if (mountedRef.current) setLiveDown(true)
          return
        }
        let src: EventSource
        try {
          src = new EventSource(url)
        } catch {
          if (mountedRef.current) setLiveDown(true)
          return
        }
        es = src
        src.addEventListener('change', () => { refetch() })
        src.onopen = () => { if (mountedRef.current) setLiveDown(false) }
        // onerror: EventSource 가 자동 재연결한다(재연결 성공 시 onopen 에서
        // 해제). 폴링으로 degrade 하지 않고 stale 만 표시한다.
        src.onerror = () => { if (mountedRef.current) setLiveDown(true) }
      }

      const onVisibility = () => {
        if (isHidden()) {
          closeSse()
        } else {
          refetch()   // 복귀 시 즉시 1회 새로고침 (stale 방지)
          openSse()
        }
      }

      if (!isHidden()) openSse()
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', onVisibility)
      }
      return () => {
        mountedRef.current = false
        closeSse()
        if (typeof document !== 'undefined') {
          document.removeEventListener('visibilitychange', onVisibility)
        }
      }
    }

    // ── 비-live 경로: 순수 interval 폴링 (기존 동작 그대로) ───────────────
    if (intervalMs <= 0) {
      return () => { mountedRef.current = false }
    }

    let id: ReturnType<typeof setInterval> | null = null
    const startInterval = () => { if (id === null) id = setInterval(refetch, intervalMs) }
    const stopInterval = () => { if (id !== null) { clearInterval(id); id = null } }

    const onVisibility = () => {
      if (isHidden()) {
        stopInterval()
      } else {
        refetch()
        startInterval()
      }
    }

    if (!isHidden()) startInterval()
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibility)
    }

    return () => {
      mountedRef.current = false
      stopInterval()
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibility)
      }
    }
  }, [refetch, intervalMs, liveEnabled, liveScopes, liveEntityId])

  return {
    data,
    error,
    loading,
    lastUpdated,
    refetch,
    setData,
    /** live 호출부에서 SSE 가 끊겨 실시간 갱신이 멈춘 상태 (배너용). */
    liveStale: liveEnabled && liveDown,
  }
}
