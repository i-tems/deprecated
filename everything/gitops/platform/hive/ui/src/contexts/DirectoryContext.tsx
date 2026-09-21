import { createContext, useContext, useState, useEffect, useCallback, useMemo, type ReactNode } from 'react'
import { userDirectoryList, type DirectoryUser } from '@/lib/api'
import { useAuth } from './AuthContext'

/**
 * 사용자 표시 override(닉네임/아바타) 디렉토리. 인증 후 1회 로드해 email→override 를
 * 캐시한다(소수 팀 + 작은 payload 전제). OwnerAvatar 등이 타 사용자 표시에 lookup 한다.
 * 본인 override 는 useAuth().user 가 이미 반영하므로 여기 들어와도 무방.
 */
interface DirectoryState {
  lookup: (email: string) => DirectoryUser | undefined
  refresh: () => Promise<void>
}

const DirectoryContext = createContext<DirectoryState | null>(null)

export function DirectoryProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const [byEmail, setByEmail] = useState<Map<string, DirectoryUser>>(new Map())

  const refresh = useCallback(async () => {
    try {
      const users = await userDirectoryList()
      setByEmail(new Map(users.map((u) => [u.email.toLowerCase(), u])))
    } catch {
      // 디렉토리는 표시 보조 — 실패해도 이니셜 폴백으로 동작하므로 조용히 무시.
    }
  }, [])

  useEffect(() => {
    if (!isAuthenticated) {
      setByEmail(new Map())
      return
    }
    void refresh()
  }, [isAuthenticated, refresh])

  const lookup = useCallback((email: string) => byEmail.get(email.toLowerCase()), [byEmail])

  const value = useMemo(() => ({ lookup, refresh }), [lookup, refresh])
  return <DirectoryContext.Provider value={value}>{children}</DirectoryContext.Provider>
}

export function useDirectory() {
  const ctx = useContext(DirectoryContext)
  if (!ctx) throw new Error('useDirectory must be used within DirectoryProvider')
  return ctx
}
