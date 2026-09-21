import { useEffect } from 'react'
import { ChevronUp, ChevronDown, RefreshCw, X } from 'lucide-react'
import { useFocus } from '@/contexts/FocusContext'

// 텍스트 입력 중(제목·설명 편집, 코멘트 작성 등)에는 단축키를 가로채지 않는다.
function isTypingTarget(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null
  if (!t) return false
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable
}

/**
 * Linear 식 "리스트에서 한 건씩 처리" 내비. focus 세션이 활성이고 지금 보는 페이지가
 * 큐의 현재 항목일 때만 TopBar 우측에 pos/total + 이전/다음/종료를 띄운다. 단축키는
 * 세션이 활성인 동안 항상 듣되, 텍스트 입력 중에는 양보한다.
 *
 * 단축키는 j(다음)·k(이전)만 — 방향키 ↑/↓는 브라우저 기본 스크롤이라 긴 상세를 읽으며
 * 스크롤하는 걸 막지 않도록 가로채지 않는다.
 */
export function FocusNav() {
  const { isActive, onCurrent, index, items, next, prev, exit, autoAdvance, toggleAutoAdvance } = useFocus()

  useEffect(() => {
    if (!isActive) return
    function handler(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (isTypingTarget(e.target)) return
      // 물리 키(code)로 판정 — 한글 입력 모드에선 e.key 가 조합문자(ㅓ/ㅏ)라 'j'/'k' 매칭이 안 된다.
      if (e.code === 'KeyJ') { e.preventDefault(); next() }
      else if (e.code === 'KeyK') { e.preventDefault(); prev() }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isActive, next, prev])

  if (!isActive || !onCurrent) return null

  const total = items.length
  const atFirst = index === 0
  const atLast = index >= total - 1
  const btn = 'rounded-md p-1.5 text-text-tertiary hover:bg-bg-hover hover:text-text disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-text-tertiary transition-colors'

  return (
    <div className="fixed top-0 right-0 z-40 h-12 flex items-center gap-0.5 pr-4 md:pr-6">
      <span className="text-xs text-text-tertiary tabular-nums mr-1.5">{index + 1} / {total}</span>
      {/* Linear 배치: 다음(↓) 왼쪽, 이전(↑) 오른쪽. */}
      <button onClick={next} disabled={atLast} title="다음 (j)" className={btn}>
        <ChevronDown size={16} />
      </button>
      <button onClick={prev} disabled={atFirst} title="이전 (k)" className={btn}>
        <ChevronUp size={16} />
      </button>
      <button
        onClick={toggleAutoAdvance}
        title={autoAdvance ? '자동 넘기기 켜짐 — 끄기' : '자동 넘기기 — 완료 시 다음 항목으로 이동'}
        className={`rounded-md p-1.5 ${autoAdvance ? 'text-text' : 'text-text-tertiary'} hover:bg-bg-hover hover:text-text transition-colors`}
      >
        <RefreshCw size={14} />
      </button>
      <button onClick={exit} title="한 건씩 처리 종료" className={btn}>
        <X size={15} />
      </button>
    </div>
  )
}
