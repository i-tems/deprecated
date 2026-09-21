import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '방금'
  if (mins < 60) return `${mins}분 전`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}시간 전`
  const days = Math.floor(hours / 24)
  return `${days}일 전`
}

export function truncate(str: string, len: number): string {
  return str.length > len ? str.slice(0, len) + '...' : str
}

export function oneLine(s: string | undefined | null): string {
  if (!s) return ''
  return s.replace(/\s+/g, ' ').trim()
}

/**
 * 엔티티 표시용 짧은 ID.
 *
 * canonical id 는 이제 `<CELL>-<TYPE>-<SEQ>` (예: `ITEMS-ISSUE-302`) 라
 * 그 자체가 사람이 읽는 짧은 이름 — id 가 있으면 그대로 노출.
 * 구형 데이터(id 없이 cell+seq 만) fallback 으로 `<CELL>-<SEQ>` 합성.
 */
export function entityShortName(
  id?: string | null,
  cellId?: string | null,
  seq?: number | null,
): string | null {
  if (id) return id
  if (cellId && seq != null) return `${cellId.toUpperCase()}-${seq}`
  return null
}

