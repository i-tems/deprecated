import { useEffect } from 'react'
import { branding } from '@/lib/branding'

export function useTitle(page: string) {
  useEffect(() => {
    document.title = page ? `${page} — ${branding.titleSuffix}` : branding.titleSuffix
  }, [page])
}
