import { useState, useEffect, type ReactNode } from 'react'
import { GoogleOAuthProvider } from '@react-oauth/google'

/**
 * auth.config에서 Google Client ID를 받아와 GoogleOAuthProvider를 초기화한다.
 * Client ID를 빌드 타임에 하드코딩하지 않고 런타임에 로드.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [clientId, setClientId] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch('/api/auth.config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then((r) => r.json())
      .then((json) => {
        if (json.status === 'ok' && json.data.google_client_id) {
          setClientId(json.data.google_client_id)
        } else {
          setError(true)
        }
      })
      .catch(() => setError(true))
  }, [])

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg">
        <p className="text-sm text-text-secondary">인증 설정을 불러올 수 없습니다.</p>
      </div>
    )
  }

  if (!clientId) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  return (
    <GoogleOAuthProvider clientId={clientId}>
      {children}
    </GoogleOAuthProvider>
  )
}
