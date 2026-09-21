// 커맨드 팔레트의 "나에게 할당" 액션이 click 으로 invoke 하는 hidden 트리거.
// useDetailShortcuts 의 'i' 단축키는 prop callback 으로 따로 도는 게 정본이라
// 두 경로가 같은 핸들러를 공유하면 된다 — 이 버튼은 팔레트 전용.
export function AssignMeTrigger({ onAssignToMe }: { onAssignToMe: () => void }) {
  return (
    <button
      type="button"
      data-kb="assign-me"
      onClick={onAssignToMe}
      className="sr-only"
      aria-hidden="true"
      tabIndex={-1}
    >
      Assign to me
    </button>
  )
}
