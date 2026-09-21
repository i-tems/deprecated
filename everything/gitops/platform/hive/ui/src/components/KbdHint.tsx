/**
 * 피커 트리거에 붙는 단축키 힌트 — 모달(?)을 열지 않아도 행동하는 자리에서 키를 보여준다 (Linear 식).
 * 단축키 정본은 useDetailShortcuts·ShortcutsHelp 이고, 여기는 시각 표시만. 트리거의 title 에 이미
 * 키가 들어있어 스크린리더는 그것으로 충분하므로 aria-hidden.
 */
export function KbdHint({ k, className = '' }: { k: string; className?: string }) {
  return (
    <kbd
      aria-hidden
      className={`shrink-0 px-1 py-0.5 rounded border border-border-subtle text-2xs font-mono leading-none text-text-quaternary ${className}`}
    >
      {k}
    </kbd>
  )
}
