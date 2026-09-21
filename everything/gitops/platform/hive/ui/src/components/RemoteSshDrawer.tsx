import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Loader2, TerminalSquare } from 'lucide-react'

import { fetchCliToken } from '@/lib/api'
import { useToast } from '@/components/ui/toast'
import { buildRunSnippet } from '@/lib/terminal'

// 떠 있는 원형 터미널 버튼(FAB). 누르면 **현재 페이지에 맞는 hive-term 연결 명령을
// 클립보드로 복사**한다(드로어·세션 관리 UI 없음). 로컬 터미널에 붙여넣기 1회로
// 그 페이지 세션에 붙는다(없으면 생성, 있으면 resume). cloudflared 1회 로그인 전제.
export function RemoteSshDrawer() {
  const toast = useToast()
  const location = useLocation()
  const [copying, setCopying] = useState(false)

  const copy = async () => {
    if (copying) return
    setCopying(true)
    try {
      const token = await fetchCliToken()
      await navigator.clipboard.writeText(buildRunSnippet(token, location.pathname))
      toast.success('연결 명령 복사됨 — 로컬 터미널에 붙여넣기')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '복사 실패')
    } finally {
      setCopying(false)
    }
  }

  // Cmd/Ctrl+` 단축키로도 복사 (기존 터미널 단축키 재활용). 최신 copy 를 ref 로 불러
  // effect 는 1회만 바인딩.
  const copyRef = useRef(copy)
  copyRef.current = copy
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const withMod = event.metaKey || event.ctrlKey
      if (withMod && !event.shiftKey && (event.key === '`' || event.code === 'Backquote')) {
        event.preventDefault()
        void copyRef.current()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-30 hidden lg:block">
      <button
        onClick={copy}
        disabled={copying}
        className="pointer-events-auto group relative flex h-12 w-12 items-center justify-center rounded-2xl border border-zinc-800/90 bg-zinc-950/88 text-zinc-100 shadow-[0_18px_60px_rgba(0,0,0,0.45)] backdrop-blur-xl transition-all duration-200 hover:-translate-y-0.5 hover:border-zinc-700 hover:bg-zinc-900/95 disabled:opacity-70"
        title="연결 명령 복사 (Ctrl+`) — 로컬 터미널에 붙여넣기"
        aria-label="연결 명령 복사"
      >
        <div className="absolute inset-0 rounded-2xl bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.1),transparent_58%)]" />
        {copying ? (
          <Loader2 size={17} className="relative z-10 animate-spin" />
        ) : (
          <TerminalSquare size={17} className="relative z-10 transition-transform duration-200 group-hover:scale-105" />
        )}
        <span className="pointer-events-none absolute right-[calc(100%+12px)] top-1/2 -translate-y-1/2 translate-x-1 whitespace-nowrap rounded-xl border border-zinc-700/90 bg-zinc-950/96 px-3 py-2 text-xs font-medium tracking-wide text-zinc-200 opacity-0 shadow-lg transition-all duration-150 group-hover:translate-x-0 group-hover:opacity-100">
          연결 명령 복사
          <span className="ml-2 text-zinc-400">Ctrl+`</span>
        </span>
      </button>
    </div>
  )
}
