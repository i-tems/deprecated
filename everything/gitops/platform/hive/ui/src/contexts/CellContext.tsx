import { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef, type ReactNode } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  cellList,
  forgetRememberedCellId,
  getRememberedCellId,
  rememberCellId,
  type Cell,
} from '@/lib/api'
import { isUserLevelPath } from '@/lib/userLevelPaths'
import { useAuth } from './AuthContext'

interface CellState {
  cells: Cell[]
  currentCell: Cell | null
  isLoading: boolean
  selectCell: (cellId: string) => void
  refreshCells: () => Promise<Cell[]>
  needsSelection: boolean
}

const CellContext = createContext<CellState | null>(null)

// 엔티티 상세 경로(/issues/:id, /projects/:id)는 cell 에 종속된다. 다른 cell 로
// 전환하면 그 엔티티는 새 cell 에 존재하지 않아 "not found" 가 난다. 따라서
// cell 전환 시 상세 경로는 해당 목록 루트로 내려보낸다. 목록/인덱스 경로는 유지.
function cellRootPath(pathname: string): string {
  const m = pathname.match(/^\/(issues|projects)\/[^/]+/)
  return m ? `/${m[1]}` : pathname
}

export function CellProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const [cells, setCells] = useState<Cell[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const bootstrappedRef = useRef(false)

  const cellIdInUrl = searchParams.get('cell')
  const activeCellId = cellIdInUrl ?? getRememberedCellId()
  const currentCell = useMemo(
    () => cells.find((c) => c.cell_id === activeCellId) ?? null,
    [cells, activeCellId],
  )

  const refreshCells = useCallback(async () => {
    try {
      const list = await cellList({ status: 'active' })
      setCells(list)
      return list
    } catch {
      setCells([])
      return []
    }
  }, [])

  // 인증 후 cell 목록 로드 + URL 부트스트랩
  useEffect(() => {
    if (!isAuthenticated) {
      bootstrappedRef.current = false
      setCells([])
      setIsLoading(false)
      return
    }
    if (bootstrappedRef.current) {
      setIsLoading(false)
      return
    }
    bootstrappedRef.current = true

    let cancelled = false
    setIsLoading(true)
    refreshCells().then((list) => {
      if (cancelled) return
      const params = new URLSearchParams(window.location.search)
      const urlCell = params.get('cell')
      const remembered = getRememberedCellId()
      let nextParams: URLSearchParams | null = null

      if (urlCell) {
        const found = list.find((c) => c.cell_id === urlCell)
        if (found) {
          rememberCellId(found.cell_id)
        } else {
          params.delete('cell')
          nextParams = params
          forgetRememberedCellId()
        }
      } else if (remembered) {
        const found = list.find((c) => c.cell_id === remembered)
        if (found) {
          params.set('cell', remembered)
          nextParams = params
        } else {
          forgetRememberedCellId()
        }
      }
      setIsLoading(false)
      if (nextParams) setSearchParams(nextParams, { replace: true })
    })
    return () => { cancelled = true }
  }, [isAuthenticated, refreshCells, setSearchParams])

  // api.ts 가 cell 접근 거부(403) 또는 cell 미정(400 & URL/localStorage 모두 빔)
  // 을 감지하면 dispatch — 여기서 URL `?cell=` 만 제거하고, CellGate 의
  // `needsSelection` 이 CellSelect 를 그려준다 (하드 reload 없이 React 전환).
  useEffect(() => {
    function handler() {
      const params = new URLSearchParams(window.location.search)
      if (!params.has('cell')) return
      params.delete('cell')
      setSearchParams(params, { replace: true })
    }
    window.addEventListener('hive:cell-reset', handler)
    return () => window.removeEventListener('hive:cell-reset', handler)
  }, [setSearchParams])

  const selectCell = useCallback((cellId: string) => {
    const found = cells.find((c) => c.cell_id === cellId)
    if (!found) return
    const params = new URLSearchParams(window.location.search)
    params.set('cell', cellId)
    // user-level 페이지(Inbox/Triage)에서 cell 선택 시 그 cell 의 기본 페이지(/projects)
    // 로 이동 — aggregate 뷰에 머무르면서 ?cell 만 부착하는 건 user-level 경로의
    // 의미와 충돌하기 때문.
    const currentPath = window.location.pathname
    const pathname = isUserLevelPath(currentPath)
      ? '/projects'
      : cellRootPath(currentPath)
    navigate({ pathname, search: `?${params.toString()}` })
    rememberCellId(cellId)
  }, [cells, navigate])

  const needsSelection = !isLoading && isAuthenticated && !currentCell && cells.length > 0

  return (
    <CellContext.Provider
      value={{ cells, currentCell, isLoading, selectCell, refreshCells, needsSelection }}
    >
      {children}
    </CellContext.Provider>
  )
}

export function useCell() {
  const ctx = useContext(CellContext)
  if (!ctx) throw new Error('useCell must be used within CellProvider')
  return ctx
}
