import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { GoogleLogin } from '@react-oauth/google'
import { useAuth } from '@/contexts/AuthContext'
import { branding } from '@/lib/branding'

export default function Login() {
  const { isAuthenticated, isLoading, login } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    document.title = branding.titleSuffix
  }, [])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  const initial = (branding.appName[0] ?? 'H').toUpperCase()

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-6 py-12">
      <div className="w-full max-w-[360px] space-y-8">
        {/* Brand mark + title */}
        <div className="flex flex-col items-center text-center space-y-5">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-accent-muted text-accent-text text-lg font-semibold">
            {initial}
          </div>
          <div className="space-y-1.5">
            <h1 className="text-2xl font-semibold tracking-tight leading-tight text-text">
              Log in to {branding.appName}
            </h1>
            <p className="text-sm text-text-tertiary">{branding.loginSubtitle}</p>
          </div>
        </div>

        {/* Sign-in */}
        <div className="flex flex-col items-center space-y-3">
          <GoogleLogin
            onSuccess={async (response) => {
              if (!response.credential) {
                setError('Google 인증 정보를 받지 못했습니다.')
                return
              }
              setError(null)
              const result = await login(response.credential)
              if (!result.ok) {
                setError(result.message ?? '로그인에 실패했습니다.')
              }
            }}
            onError={() => setError('Google 로그인에 실패했습니다.')}
            theme="outline"
            size="large"
            shape="rectangular"
            width="320"
          />

          {error && (
            <p className="w-full rounded-md bg-danger-muted px-3 py-2 text-center text-xs text-danger">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
