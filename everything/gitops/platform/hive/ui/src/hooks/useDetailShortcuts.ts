import { useEffect } from 'react'

// 텍스트 입력 중(제목·설명 편집, 코멘트 작성 등)에는 단축키를 가로채지 않는다.
function isTypingTarget(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null
  if (!t) return false
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable
}

// 상세 페이지에 렌더된 data-kb 트리거(피커 버튼)를 클릭해 연다 — 없으면 무시.
function clickKb(name: string) {
  document.querySelector<HTMLElement>(`[data-kb="${name}"]`)?.click()
}

function focusComment() {
  const el = document.querySelector<HTMLTextAreaElement>('[data-kb="comment"]')
  if (!el) return
  el.scrollIntoView({ block: 'center' })
  el.focus()
}

/**
 * Linear 식 상세 단축키 — s 상태, p 우선순위, a 담당자, l 라벨, c 코멘트, i 나에게 할당.
 * 피커는 data-kb 트리거를 click 해 열고, 코멘트는 작성창을 포커스한다. 텍스트 입력 중·수정자 조합엔
 * 양보하고, 한글 입력 모드에서도 동작하도록 물리 키(e.code)로 판정한다.
 */
export function useDetailShortcuts(opts: { onAssignToMe?: () => void; enabled?: boolean }) {
  const { onAssignToMe, enabled = true } = opts
  useEffect(() => {
    if (!enabled) return
    function handler(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (isTypingTarget(e.target)) return
      switch (e.code) {
        case 'KeyS': e.preventDefault(); clickKb('status'); break
        case 'KeyP': e.preventDefault(); clickKb('priority'); break
        case 'KeyA': e.preventDefault(); clickKb('assignee'); break
        case 'KeyL': e.preventDefault(); clickKb('labels'); break
        case 'KeyC': e.preventDefault(); focusComment(); break
        case 'KeyI': if (onAssignToMe) { e.preventDefault(); onAssignToMe() } break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onAssignToMe, enabled])
}
