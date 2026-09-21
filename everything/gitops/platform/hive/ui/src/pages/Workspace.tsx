import { LayoutDashboard } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { MomentumBar } from '@/components/MomentumBar'
import { DeckPanel } from '@/components/DeckPanel'
import { InboxPanel } from '@/components/InboxPanel'
import { useTitle } from '@/hooks/useTitle'

/**
 * Workspace — 일의 흐름 전체를 담는 단일 페이지(홈). 위→아래로:
 *   할 일(Deck — 지금 할 일) · 흐름(Momentum — 지금 일하는 중 / 오늘 변경 / 오늘 완료)
 *   · 알림(Inbox). Momentum 은 "내가 할 일"과 "에이전트가 하는 일/끝낸 일"을
 *   가르는 자리라 Deck 과 Inbox 사이에 둔다.
 * 패널은 재사용 컴포넌트(DeckPanel/MomentumBar/InboxPanel)로 임베드. 구 /deck·/inbox 는 여기로 리다이렉트.
 */
export default function Workspace() {
  useTitle('Workspace')
  return (
    <div className="space-y-3">
      <PageHeader title="Workspace" icon={LayoutDashboard} iconClass="text-accent" />

      {/* 할 일 → 흐름(에이전트가 하는/끝낸 일) → 알림 을 전체 폭으로 위→아래 스택.
          Inbox 는 우측 좁은 컬럼이 아니라 하단 한 칸(전체 폭)이라 각 알림 내용이 한 줄에 다 보인다. */}
      <DeckPanel />
      <MomentumBar />
      <InboxPanel />
    </div>
  )
}
