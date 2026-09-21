import { useCallback, useMemo } from 'react'
import { useLocation, type To } from 'react-router-dom'
import { getRememberedCellId } from '@/lib/api'

function cellIdFromSearch(search: string): string | null {
  return new URLSearchParams(search).get('cell')
}

function appendCellToString(to: string, cellId: string): string {
  if (/^[a-z][a-z0-9+.-]*:/i.test(to)) return to

  const hashIndex = to.indexOf('#')
  const beforeHash = hashIndex >= 0 ? to.slice(0, hashIndex) : to
  const hash = hashIndex >= 0 ? to.slice(hashIndex) : ''
  const queryIndex = beforeHash.indexOf('?')
  const pathname = queryIndex >= 0 ? beforeHash.slice(0, queryIndex) : beforeHash
  const query = queryIndex >= 0 ? beforeHash.slice(queryIndex + 1) : ''
  const params = new URLSearchParams(query)

  if (!params.has('cell')) params.set('cell', cellId)
  const nextSearch = params.toString()
  return `${pathname}${nextSearch ? `?${nextSearch}` : ''}${hash}`
}

export function appendCellTo(to: To, cellId: string | null): To {
  if (!cellId) return to
  if (typeof to === 'string') return appendCellToString(to, cellId)

  const params = new URLSearchParams(to.search ?? '')
  if (!params.has('cell')) params.set('cell', cellId)
  return {
    ...to,
    search: `?${params.toString()}`,
  }
}

export function useCurrentCellIdInUrl(): string | null {
  const { search } = useLocation()
  return useMemo(() => cellIdFromSearch(search) ?? getRememberedCellId(), [search])
}

export function useCellAwareTo() {
  const cellId = useCurrentCellIdInUrl()
  return useCallback((to: To): To => appendCellTo(to, cellId), [cellId])
}

export function useCellAwarePath() {
  const toCell = useCellAwareTo()
  return useCallback((to: string): string => toCell(to) as string, [toCell])
}
