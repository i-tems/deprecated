import { Modal } from '@/components/ui/modal'

// 단축키 정본은 각 핸들러(useDetailShortcuts·FocusNav·Layout)에 있고, 여기는 사람용 목록.
const GROUPS: { title: string; items: [string, string][] }[] = [
  {
    title: '한 건씩 처리 (focus)',
    items: [
      ['j', '다음 항목'],
      ['k', '이전 항목'],
    ],
  },
  {
    title: 'Issue 상세 — 결정·응답',
    items: [
      ['s', '상태 변경'],
      ['p', '우선순위'],
      ['a', '담당자'],
      ['l', '라벨'],
      ['i', '나에게 할당'],
      ['c', '코멘트 작성'],
    ],
  },
  {
    title: '전역',
    items: [
      ['⌘ K', '커맨드 메뉴 (검색·액션)'],
      ['⌘ B', '사이드바 접기/펴기'],
      ['?', '단축키 도움말'],
    ],
  },
  {
    title: '터미널',
    items: [
      ['⌘ `', '드로어 열기/닫기'],
      ['⌘ ⇧ F', '전체화면 토글'],
      ['⇧ Enter', '줄바꿈 입력'],
      ['⌘ ⌫', '줄 처음까지 삭제'],
    ],
  },
]

function Kbd({ k }: { k: string }) {
  return (
    <kbd className="px-1.5 py-0.5 rounded border border-border bg-bg-subtle text-xs font-mono text-text-secondary min-w-[1.5rem] text-center">
      {k}
    </kbd>
  )
}

export function ShortcutsHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="단축키">
      <div className="space-y-4">
        {GROUPS.map((g) => (
          <div key={g.title}>
            <div className="text-xs font-medium text-text-tertiary mb-1.5">{g.title}</div>
            <ul className="space-y-1.5">
              {g.items.map(([k, label]) => (
                <li key={k} className="flex items-center justify-between gap-4 text-sm">
                  <span className="text-text-secondary">{label}</span>
                  <Kbd k={k} />
                </li>
              ))}
            </ul>
          </div>
        ))}
        <p className="text-2xs text-text-quaternary pt-1">
          텍스트 입력 중에는 단축키가 동작하지 않습니다. 상세 행동 키는 Issue 상세에서만 동작합니다.
        </p>
      </div>
    </Modal>
  )
}
