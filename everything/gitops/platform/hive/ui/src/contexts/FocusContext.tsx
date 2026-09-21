import { createContext, useContext, useCallback, useEffect, useMemo, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { usePersistedState } from '@/hooks/usePersistedState'
import { issueListAll, projectListAll, initiativeListAll } from '@/lib/api'
import { buildTriageQueue, ISSUE_ATTENTION, type QueueParams } from '@/lib/triageQueue'
import type { Project, Initiative } from '@/lib/types'

/** 한 건씩 처리(focus) 큐의 한 항목. 리스트(Triage 등)에서 만든 순서를 그대로 담는다. */
export interface FocusItem {
  /** cell-aware 전체 이동 경로 — e.g. "/issues/abc?cell=infra" */
  to: string
  /** 라우트 매칭용 pathname(쿼리 제외) — 현재 보는 페이지가 이 항목인지 판정에 쓴다. */
  pathname: string
  /** 표시·디버깅용 라벨(제목). UI 필수는 아님. */
  label?: string
}

interface FocusSession {
  items: FocusItem[]
  index: number
  /** 라이브 재구성에 쓰는 ▶ 누른 시점의 정렬·필터. 없으면(구 세션) 갱신 없이 스냅샷으로 동작. */
  params?: QueueParams
}

interface FocusContextValue {
  isActive: boolean
  items: FocusItem[]
  index: number
  current: FocusItem | undefined
  /** 지금 보고 있는 라우트가 큐의 현재 항목인가 — nav 표시 조건. */
  onCurrent: boolean
  /** 처리 완료 시 자동으로 다음 항목으로 넘어가는 옵트인 토글. 기본 off. */
  autoAdvance: boolean
  /** 정렬된 큐로 한 건씩 처리 시작. params 로 이후 라이브 재구성. startIndex 항목 상세로 이동. */
  start: (items: FocusItem[], params?: QueueParams, startIndex?: number) => void
  next: () => void
  prev: () => void
  exit: () => void
  toggleAutoAdvance: () => void
}

const FocusCtx = createContext<FocusContextValue | null>(null)
const EMPTY: FocusSession = { items: [], index: 0 }

// 탭(sessionStorage) 단위로 큐를 보관 — 새로고침·페이지 이동에도 살아남고 새 창은 빈 상태.
export function FocusProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = usePersistedState<FocusSession>('focus:session', EMPTY, 'session')
  const [autoAdvance, setAutoAdvance] = usePersistedState<boolean>('focus:autoAdvance', false, 'session')
  const autoAdvanceRef = useRef(autoAdvance)
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => { autoAdvanceRef.current = autoAdvance }, [autoAdvance])

  const { items, index, params } = session
  const isActive = items.length > 0
  const current = items[index]

  // 큐의 다른 항목으로 사람이 직접 이동하면(브레드크럼·뒤로가기 등) index 를 동기화해 pos 가 따라가게 한다.
  useEffect(() => {
    if (!isActive) return
    const i = items.findIndex((it) => it.pathname === location.pathname)
    if (i >= 0 && i !== index) setSession((s) => ({ ...s, index: i }))
  }, [location.pathname, isActive, items, index, setSession])

  // 라이브 갱신: 세션이 활성이고 params 가 있으면 Triage 와 같은 소스를 5s 폴링해 큐를 재구성한다.
  // 완료(waiting/error 이탈)된 항목은 빠지고 새 waiting/error 는 정렬 위치에 들어온다. 단 지금 보고 있는
  // 항목이 완료돼도 결과 확인을 위해 그 자리에 핀해 두고, 다음/이전으로 이동하면 다음 갱신에서 빠진다.
  // autoAdvance on: 핀 대신 즉시 다음 항목으로 이동. 큐 소진 시 세션 종료.
  useEffect(() => {
    if (!isActive || !params) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      try {
        const [waitErr, projects, initiatives] = await Promise.all([
          issueListAll({ statuses: ISSUE_ATTENTION }),
          projectListAll({ limit: 1000 }),
          initiativeListAll({ limit: 1000 }),
        ])
        if (cancelled) return
        const fresh = buildTriageQueue(waitErr.issues, projects as Project[], initiatives as Initiative[], params)
        let autoNavigateTo: string | null = null
        setSession((prev) => {
          if (prev.items.length === 0) return prev // 그새 종료됨
          const cur = prev.items[prev.index]
          if (!cur) return prev
          const aliveIdx = fresh.findIndex((f) => f.pathname === cur.pathname)
          if (aliveIdx >= 0) return { ...prev, items: fresh, index: aliveIdx }
          // 현재 항목이 큐에서 빠짐(완료)
          if (autoAdvanceRef.current) {
            if (fresh.length === 0) return EMPTY // 큐 소진 — 세션 종료
            const at = Math.min(prev.index, fresh.length - 1)
            autoNavigateTo = fresh[at].to
            return { ...prev, items: fresh, index: at }
          }
          // 기본: 결과 확인용으로 같은 자리에 핀, 사람이 이동하면 다음 tick 에 사라진다.
          const at = Math.min(prev.index, fresh.length)
          const pinned = [...fresh.slice(0, at), cur, ...fresh.slice(at)]
          return { ...prev, items: pinned, index: at }
        })
        if (autoNavigateTo) navigate(autoNavigateTo)
      } catch {
        // 일시 오류는 무시하고 다음 tick 에 재시도.
      }
      if (!cancelled) timer = setTimeout(tick, 5000)
    }
    tick()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [isActive, params, setSession, navigate])

  const start = useCallback((next: FocusItem[], queueParams?: QueueParams, startIndex = 0) => {
    if (next.length === 0) return
    setSession({ items: next, index: startIndex, params: queueParams })
    navigate(next[startIndex].to)
  }, [setSession, navigate])

  const move = useCallback((delta: number) => {
    const i = index + delta
    if (i < 0 || i >= items.length) return
    setSession((s) => ({ ...s, index: i }))
    navigate(items[i].to)
  }, [index, items, setSession, navigate])

  const next = useCallback(() => move(1), [move])
  const prev = useCallback(() => move(-1), [move])
  const exit = useCallback(() => setSession(EMPTY), [setSession])
  const toggleAutoAdvance = useCallback(() => setAutoAdvance((v) => !v), [setAutoAdvance])

  const onCurrent = isActive && !!current && current.pathname === location.pathname

  const value = useMemo<FocusContextValue>(
    () => ({ isActive, items, index, current, onCurrent, autoAdvance, start, next, prev, exit, toggleAutoAdvance }),
    [isActive, items, index, current, onCurrent, autoAdvance, start, next, prev, exit, toggleAutoAdvance],
  )

  return <FocusCtx.Provider value={value}>{children}</FocusCtx.Provider>
}

export function useFocus(): FocusContextValue {
  const ctx = useContext(FocusCtx)
  if (!ctx) throw new Error('useFocus must be used within FocusProvider')
  return ctx
}
