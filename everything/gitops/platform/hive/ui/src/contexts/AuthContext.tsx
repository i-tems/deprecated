import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { forgetRememberedCellId } from '@/lib/api'

interface User {
  email: string
  name: string
  picture: string
  is_admin: boolean
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (credential: string) => Promise<{ ok: boolean; message?: string }>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)
const LEGACY_TOKEN_KEY = 'auth_token'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // 앱 시작 시 서버 쿠키 기반 세션 검증
  useEffect(() => {
    localStorage.removeItem(LEGACY_TOKEN_KEY)

    fetch('/api/auth.verify', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Source': 'console',
      },
    })
      .then((r) => r.json())
      .then((json) => {
        if (json.status === 'ok') {
          setToken('cookie')
          setUser(json.data)
        } else {
          setToken(null)
          setUser(null)
        }
      })
      .catch(() => {
        setToken(null)
        setUser(null)
      })
      .finally(() => setIsLoading(false))
  }, [])

  const login = useCallback(async (credential: string) => {
    const res = await fetch('/api/auth.login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Source': 'console' },
      body: JSON.stringify({ credential }),
    })
    const json = await res.json()
    if (json.status !== 'ok') {
      return { ok: false, message: json.message || '로그인에 실패했습니다.' }
    }
    const { user: u } = json.data
    localStorage.removeItem(LEGACY_TOKEN_KEY)
    setToken('cookie')
    setUser(u)
    return { ok: true }
  }, [])

  const logout = useCallback(() => {
    fetch('/api/auth.logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Source': 'console' },
      body: '{}',
    }).finally(() => {
      localStorage.removeItem(LEGACY_TOKEN_KEY)
      forgetRememberedCellId()
      setToken(null)
      setUser(null)
    })
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, token, isAuthenticated: !!token, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
