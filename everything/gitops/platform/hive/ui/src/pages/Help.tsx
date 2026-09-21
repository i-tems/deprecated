import type { ReactNode } from 'react'
import {
  Info,
  ListTodo,
  Target,
  Compass,
  Radio,
  Box,
  FileText,
  Inbox,
  Layers,
  Blocks,
  Settings,
  TerminalSquare,
  Clock3,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { useTitle } from '@/hooks/useTitle'

// 처음 쓰는 cell 사용자용 안내. 내용 정본은 hive specs(model/project_issue_model,
// signals_model, runtime/loop_behavior_spec, knowledge_flow). 첫 사용 경로는
// 가장 단순한 단독 Issue 기준으로 설명한다.

function Card({ children }: { children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border-subtle bg-card p-4 md:p-5">
      {children}
    </section>
  )
}

function SectionTitle({ icon: Icon, n, children }: { icon: LucideIcon; n: number; children: ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-accent-muted text-accent-text text-xs font-semibold shrink-0">
        {n}
      </span>
      <Icon size={15} className="text-text-tertiary shrink-0" />
      <h2 className="text-sm font-semibold tracking-tight">{children}</h2>
    </div>
  )
}

function Concept({ icon: Icon, iconClass, term, children }: {
  icon: LucideIcon; iconClass?: string; term: string; children: ReactNode
}) {
  return (
    <div className="flex gap-2.5">
      <Icon size={15} className={`mt-0.5 shrink-0 ${iconClass ?? 'text-text-tertiary'}`} />
      <p className="text-sm text-text-secondary leading-relaxed">
        <span className="font-semibold text-text">{term}</span> — {children}
      </p>
    </div>
  )
}

function Step({ n, children }: { n: number; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="inline-flex items-center justify-center w-5 h-5 mt-0.5 rounded-full border border-border-strong text-2xs font-medium text-text-secondary shrink-0">
        {n}
      </span>
      <span className="text-sm text-text-secondary leading-relaxed">{children}</span>
    </li>
  )
}

function Chip({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'active' | 'warn' | 'done' }) {
  const tones = {
    default: 'border-border-subtle text-text-tertiary',
    active: 'border-accent/40 text-accent bg-accent-muted',
    warn: 'border-warning/40 text-warning bg-warning-muted',
    done: 'border-success/40 text-success',
  }
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-2xs font-medium border ${tones[tone]}`}>
      {children}
    </span>
  )
}

const TABS: { icon: LucideIcon; iconClass: string; name: string; desc: string }[] = [
  { icon: Compass, iconClass: 'text-initiative', name: 'Initiatives', desc: '전략 묶음 — Project 들이 advance 하는 큰 outcome' },
  { icon: Target, iconClass: 'text-project', name: 'Projects', desc: '프로젝트 위임·목록·상태/우선순위 관리' },
  { icon: ListTodo, iconClass: 'text-issue', name: 'Issues', desc: '작업 목록 — 단독 작업 또는 Project 이 분해한 자식' },
  { icon: Radio, iconClass: 'text-signal', name: 'Signals', desc: '들어온 신호 목록' },
  { icon: Layers, iconClass: 'text-accent', name: 'Workspace', desc: '한 화면에 알림(Inbox)·할 일(Deck)·진행 흐름을 모아 본다' },
  { icon: Blocks, iconClass: 'text-text-tertiary', name: 'Capabilities', desc: '워커가 호출할 수 있는 능력 목록' },
  { icon: Settings, iconClass: 'text-text-tertiary', name: 'Settings', desc: '사용자 설정 (예: 샌드박스 git 이름/이메일)' },
]

export default function Help() {
  useTitle('Guide')
  return (
    <div className="space-y-4">
      <PageHeader title="Guide" icon={Info} />

      <div className="max-w-3xl space-y-4">
        {/* 0. 한 줄 소개 */}
        <div className="rounded-lg border border-accent/30 bg-accent-muted/40 p-4 md:p-5">
          <p className="text-sm text-text leading-relaxed">
            여기는 여러분의 <span className="font-semibold">Cell</span> — 프로젝트만 위임하면 AI
            에이전트가 스스로 계획·실행·마무리하는 <span className="font-semibold">여러분 전용
            AI 작업 공간</span>입니다. 챗봇처럼 한 번 답하고 끝나는 게 아니라, 한 워커가 한
            작업의 전 과정을 맡아 세션을 넘겨가며 진행합니다. 여러분은 ‘어떻게’가
            아니라 <span className="font-semibold">무엇을 원하는지</span> 만 맡기고, 나머지는
            워커가 자율적으로 처리합니다. 배포·비용·판단처럼 사람이 봐야 할 지점에서만 멈추고
            부르는데, 이 방식을 업계에서는 <span className="font-semibold">휴먼 온 더 루프
            (human-on-the-loop)</span> 라고 합니다.
          </p>
        </div>

        {/* 1. 5분 개념 */}
        <Card>
          <SectionTitle icon={Box} n={1}>5분 개념</SectionTitle>
          <div className="space-y-2.5">
            <Concept icon={Box} term="Cell">
              여러분의 작업 공간(테넌트). Initiative·Issue·Project·Signal·지식이 Cell 단위로 완전히
              격리됩니다. 사이드바 좌상단에서 현재 Cell 을 확인·전환합니다.
            </Concept>
            <Concept icon={Compass} iconClass="text-initiative" term="Initiative">
              여러 Project 을 묶는 strategic anchor — 4-layer (Cell → Initiative → Project → Issue) 의 가장
              위. 자동 진행되지 않고 사람이 직접 갱신합니다 (Linear 정합 — manual curation only).
            </Concept>
            <Concept icon={Target} iconClass="text-project" term="Project">
              여러 Issue 로 분해될 만큼 큰 프로젝트. 워커가 자율적으로 자식 Issue 를 만들어 진행합니다.
              상위 Initiative 에 link 하거나 standalone 으로 둘 수 있습니다.
            </Concept>
            <Concept icon={ListTodo} iconClass="text-issue" term="Issue">
              워커에게 위임하는 한 덩어리의 실행 단위. 단독으로 두거나 Project 아래 둘 수 있습니다.
            </Concept>
            <Concept icon={Radio} iconClass="text-signal" term="Signal">
              시스템에 들어온 이벤트·제보. 검토를 거쳐 Issue/Project 로 전환됩니다.
            </Concept>
            <Concept icon={Info} term="Worker">
              한 항목의 전 생애주기(계획 → 실행 → 마무리)를 맡는 자율 AI 에이전트. 한 워커 = 한 항목.
            </Concept>
            <Concept icon={Blocks} term="Capability">
              워커가 호출해 시스템을 실제로 바꾸는 행동 단위 — 상태 전이·엔티티 생성·commit·배포 등.
              워커는 채팅이 아니라 이걸로 일합니다. 목록은 고정이 아니라 동적이라 cell 이 성숙할수록
              늘어납니다.
            </Concept>
            <Concept icon={FileText} term="Knowledge">
              작업 산출물과 정리된 지식. 항목별 공간에 자동 축적됩니다.
            </Concept>
          </div>
        </Card>

        {/* 2. 첫 사용 — Issue 하나 만들기 */}
        <Card>
          <SectionTitle icon={ListTodo} n={2}>첫 사용 — Issue 하나 만들기</SectionTitle>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            가장 단순한 출발점은 <span className="font-semibold text-text">단독 Issue</span> 입니다.
            큰 프로젝트라면 Project 로 시작해 워커가 Issue 로 분해하게 하지만, 처음엔 작업 하나를 위임해
            흐름을 익히는 편이 좋습니다.
          </p>
          <ol className="space-y-2.5">
            <Step n={1}>
              <span className="font-medium text-text">Issues</span> 탭에서 새 Issue 를 만들고, 끝난
              상태가 무엇인지 적습니다. <span className="text-text-tertiary">“무엇을 / 어디서 /
              무엇이 끝난 상태인지”</span> 가 분명할수록 워커가 헤매지 않습니다. 모호하면 워커가
              곧바로 되묻습니다.
            </Step>
            <Step n={2}>
              위임하면 상태가 <Chip>todo</Chip> → <Chip tone="active">running</Chip> 으로 바뀌고
              워커가 착수합니다.
            </Step>
            <Step n={3}>
              워커가 필요한 만큼 스스로 계획을 세운 뒤 실행합니다. 진행 과정(도구 호출·결과)은
              Issue 상세 페이지에서 실시간으로 흐릅니다.
            </Step>
            <Step n={4}>
              끝나면 <Chip tone="active">cleanup</Chip>(정리) 을 거쳐 <Chip tone="done">done</Chip>
              으로 마무리됩니다.
            </Step>
          </ol>
          <div className="mt-4 flex flex-wrap items-center gap-1.5">
            <span className="text-2xs text-text-tertiary mr-1">상태:</span>
            <Chip>backlog</Chip>
            <Chip>todo</Chip>
            <Chip tone="active">running</Chip>
            <Chip tone="warn">waiting</Chip>
            <Chip tone="active">cleanup</Chip>
            <Chip tone="done">done</Chip>
            <Chip>cancelled</Chip>
            <Chip tone="warn">error</Chip>
          </div>
        </Card>

        {/* 3. waiting */}
        <Card>
          <SectionTitle icon={Inbox} n={3}>워커가 멈춰 사람을 부를 때 (waiting)</SectionTitle>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            상태가 <Chip tone="warn">waiting</Chip> 이면 워커가 자율 실행을 멈추고 사람의 판단을
            기다립니다 — 인트로에서 말한 <span className="font-semibold text-text">휴먼 온 더
            루프</span> 가 작동하는 지점입니다. 사유는 네 가지입니다.
          </p>
          <div className="rounded-md border border-warning/30 bg-warning-muted/40 p-3 space-y-1.5">
            <p className="text-sm text-text-secondary"><span className="font-semibold text-text">정보 요청</span> — 범위·환경·제약 등 사람만 답할 수 있는 정보가 부족함.</p>
            <p className="text-sm text-text-secondary"><span className="font-semibold text-text">승인</span> — 배포·비용·보안 등 사람만 판단할 결정이 필요함.</p>
            <p className="text-sm text-text-secondary"><span className="font-semibold text-text">막힘</span> — 외부 의존성 때문에 더 못 나아감.</p>
            <p className="text-sm text-text-secondary"><span className="font-semibold text-text">직접 행동</span> — 사람이 직접 해야 할 일이 있음.</p>
          </div>
          <p className="text-sm text-text-secondary leading-relaxed mt-3">
            해당 Issue 상세의 댓글로 답하면 워커가 다시 깨어나 이어서 진행합니다.
          </p>
        </Card>

        {/* 4. Signal 분류 */}
        <Card>
          <SectionTitle icon={Radio} n={4}>Signal 분류</SectionTitle>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            들어온 Signal 은 <Chip>emitted</Chip> 상태로 쌓입니다. <span className="font-medium text-text">Signals</span> 탭에서
            목록을 확인하고 keep/dismiss 로 분류합니다. 사람이 처리할 항목은 <span className="font-medium text-text">Workspace</span> 에 모입니다.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-md border border-border-subtle p-3">
              <p className="text-sm font-semibold text-text mb-0.5">keep</p>
              <p className="text-sm text-text-secondary leading-relaxed">처리 가치 있음 → <Chip tone="active">kept</Chip>. 시스템이 Issue/Project 후보로 전환하고, 완료되면 <Chip tone="done">resolved</Chip>.</p>
            </div>
            <div className="rounded-md border border-border-subtle p-3">
              <p className="text-sm font-semibold text-text mb-0.5">dismiss</p>
              <p className="text-sm text-text-secondary leading-relaxed">처리 불필요 → <Chip>dismissed</Chip>.</p>
            </div>
          </div>
          <p className="text-sm text-text-tertiary leading-relaxed mt-3">
            <Chip>emitted</Chip> 는 자율 처리되지 않습니다. 사람이 keep 해야 다음 단계로 넘어갑니다.
          </p>
        </Card>

        {/* 5. 탭별 설명 */}
        <Card>
          <SectionTitle icon={Box} n={5}>탭별 한 줄 설명</SectionTitle>
          <div className="divide-y divide-border-subtle">
            {TABS.map((t) => (
              <div key={t.name} className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
                <t.icon size={15} className={`shrink-0 ${t.iconClass}`} />
                <span className="text-sm font-medium text-text w-28 shrink-0">{t.name}</span>
                <span className="text-sm text-text-secondary">{t.desc}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* 6. Initiative */}
        <Card>
          <SectionTitle icon={Compass} n={6}>Initiative — 전략 묶음 (수동 갱신)</SectionTitle>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            <span className="font-semibold text-text">Initiative</span> 는 4-layer
            (Cell → Initiative → Project → Issue) 의 가장 위 단위로, 여러 Project 이 advance 하는
            큰 outcome 을 묶는 anchor 입니다. Project/Issue 와 달리{' '}
            <span className="font-semibold text-text">워커가 자동으로 진행하지 않습니다</span> —
            사람·skill 이 명시적으로 갱신합니다 (Linear 정합 — manual curation only).
          </p>

          <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2">
            단일 축 — status (Project/Issue 와 동형)
          </p>
          <div className="rounded-md border border-border-subtle p-3 mb-4">
            <p className="text-sm font-semibold text-text mb-1">status — 진행 단계</p>
            <p className="text-sm text-text-secondary leading-relaxed mb-2">
              사람만 전이 (자동 없음). '잘 가나/위험/pivot' 평가는 별도 축이 아니라
              Activity 코멘트로 남깁니다 (Project 의 Activity 와 동일).
            </p>
            <div className="flex flex-wrap gap-1">
              <Chip>backlog</Chip>
              <Chip tone="active">active</Chip>
              <Chip tone="done">done</Chip>
              <Chip>archive</Chip>
            </div>
          </div>

          <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2">
            사용 흐름
          </p>
          <ol className="space-y-2.5">
            <Step n={1}>
              <span className="font-medium text-text">Initiatives</span> 탭의 <Chip>+ New Initiative</Chip>
              로 생성. 이름 + 짧은 description, 시작 status 선택 (보통 <Chip>backlog</Chip>).
            </Step>
            <Step n={2}>
              관련 <span className="font-medium text-text">Project</span> 의 상세 페이지에서 Initiative 를
              link (수동 — 자동 attach 없음). 한 Initiative 가 여러 Project 을 모을 수 있고, Project 은
              standalone 으로 두는 것도 가능합니다.
            </Step>
            <Step n={3}>
              큰 전략은 <span className="font-medium text-text">sub-initiative</span> 로 분해 (≤5 depth,
              multi-parent 허용).
            </Step>
            <Step n={4}>
              진행·위험·pivot 평가는 Initiative 상세의 <span className="font-medium text-text">Activity</span>
              코멘트로 남깁니다 (Project 의 Activity 와 동일 — 별도 health 축 없음).
            </Step>
            <Step n={5}>
              전략이 진행되면 사람이 status 를 <Chip>backlog</Chip> → <Chip tone="active">active</Chip>{' '}
              → <Chip tone="done">done</Chip> 로 직접 전이 (접으면 <Chip>archive</Chip>). 자식 Project 이 모두 done 되어도{' '}
              <span className="font-semibold text-text">자동 전이되지 않습니다</span> — 전략 마감은
              사람의 판단입니다.
            </Step>
          </ol>

          <div className="mt-4 rounded-md border border-accent/30 bg-accent-muted/40 p-3">
            <p className="text-sm text-text-secondary leading-relaxed">
              <span className="font-semibold text-text">Initiative 가 필요한 순간</span> — 여러 Project
              이 한 outcome 을 향할 때 (예: <span className="italic">"투자 인사이트 플랫폼"</span>{' '}
              아래에 <span className="italic">"뉴스 소스 검증"</span>·
              <span className="italic">"수집 파이프라인"</span> 같은 Project). Project 하나로 끝나는
              작업은 굳이 Initiative 로 묶을 필요 없습니다 — standalone Project 그대로 충분합니다.
            </p>
          </div>
        </Card>

        {/* 7. Cell 레포 */}
        <Card>
          <SectionTitle icon={Box} n={7}>Cell 레포 — 코드·지식·설정이 쌓이는 곳</SectionTitle>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            Cell 마다 전용 git 저장소가 있습니다. 앱 코드·누적 지식·cell 설정이 한곳에 모이고,
            워커는 보통 <span className="font-mono text-text">issue</span> 브랜치에서 이 레포를
            작업합니다.
          </p>
          <div className="space-y-2.5">
            <Concept icon={FileText} term="지식이 쌓이는 방식">
              작업은 해당 Issue·Project 의 space(<span className="font-mono text-text">issues/&#123;id&#125;</span>
              {' '}·<span className="font-mono text-text">projects/&#123;id&#125;</span>)에 기록되고,
              {' '}<Chip tone="active">cleanup</Chip> 단계에서 재사용 가치가 있는 내용이 Cell
              지식(<span className="font-mono text-text">knowledge/wiki</span>)으로 승격됩니다.
            </Concept>
            <Concept icon={Settings} term=".claude">
              cell 고유 동작을 여기서 커스터마이즈합니다 —
              {' '}<span className="font-mono text-text">.claude/CLAUDE.md</span>(cell 오버레이,
              플랫폼 공통 설정보다 우선), <span className="font-mono text-text">settings.json</span>(하네스
              설정), cell 전용 <span className="font-mono text-text">skills/</span>·
              <span className="font-mono text-text">specs/</span>. 플랫폼 공통 rule·spec 은 항상 함께
              적재됩니다.
            </Concept>
            <Concept icon={Blocks} term="앱 코드">
              <span className="font-mono text-text">gitops/apps/&#123;app&#125;/</span> 에 소스·
              Dockerfile 과 함께 meta 앱 선언 <span className="font-mono text-text">app.yaml</span>
              {' '}(<span className="font-mono text-text">kind: app</span>)을 둡니다. base/overlays
              같은 raw 쿠버네티스 매니페스트는 직접 두지 않고, 배포 의도를 담은
              {' '}<span className="font-mono text-text">app.yaml</span> 만 작성하면 Hub 가 격리
              빌드 → 매니페스트 렌더 → 배포까지 처리합니다. PR 머지는 항상 사람이 직접 합니다.
            </Concept>
            <Concept icon={Radio} iconClass="text-signal" term="Issue 미리보기">
              워커가 issue 브랜치에 push 하면 미리보기 환경이 자동 생성됩니다
              (<span className="font-mono text-text">&#123;app&#125;-issue-N.lab.i-tems.com</span>).
              issue 가 끝나면 자동으로 삭제됩니다.
            </Concept>
            <Concept icon={Info} term="파이프라인 (스케줄)">
              정기 실행 파이프라인은 meta 스케줄 선언
              {' '}(<span className="font-mono text-text">kind: Schedule</span>)으로 작성합니다 —
              실행 주기(<span className="font-mono text-text">@daily</span>·cron), 컨테이너
              issue 들, issue 간 의존 관계를 YAML 로 적으면 Airflow DAG 로 렌더돼 스케줄 실행됩니다.
              cell 사용자가 직접 작성할 수 있습니다.
            </Concept>
          </div>
        </Card>

        {/* 8. Cell 의 진짜 가치 (운영 모델 + 인프라) */}
        <Card>
          <SectionTitle icon={Target} n={8}>Cell 의 진짜 가치 — 지시 없이 끝내는 구조, 운영 없는 인프라</SectionTitle>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            핵심은 모델 성능이 아니라 <span className="font-semibold text-text">Cell 의 구조</span>
            입니다. 같은 AI 라도 이 구조를 거치면 반복 지시·확인·대기에 쓰는 사람 시간이 급격히
            줄고, 인프라는 매니페스트와 git push 만으로 프로덕션급을 그대로 씁니다. 챗봇·코파일럿과
            다른 점은 다음이 계약 수준으로 박혀 있다는 것입니다.
          </p>
          <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2">
            운영 모델 — 지시 없이 끝내는 구조
          </p>
          <div className="space-y-2.5">
            <Concept icon={Target} iconClass="text-project" term="위임하면 끝까지">
              한 워커가 한 항목의 계획 → 실행 → 정리 → 마감을 한 세션에서 자율 처리합니다. 단계마다
              “다음 뭐 해?”를 지시할 필요가 없습니다. 게다가 워커는 항목 수명 동안 살아 있어,
              {' '}<Chip tone="warn">waiting</Chip> 중 사람이 댓글을 달거나 외부 이벤트가 생기면
              같은 세션이 자동으로 이어집니다 — “다시 시작해”도 불필요.
            </Concept>
            <Concept icon={Blocks} term="팀처럼 분해·병렬">
              큰 Project 은 워커가 자식 Issue 로 분해하고, 자식들이 각자 독립 세션에서 병렬로
              진행합니다. 완료 감지·다음 단계 진출 같은 오케스트레이션은 시스템이 합니다.
            </Concept>
            <Concept icon={Inbox} iconClass="text-warning" term="사람은 결정 게이트만">
              저위험 결정은 AI 가 스스로 내리고, 배포·비용·보안·전략처럼 정말 사람이 봐야 할
              때만 <Chip tone="warn">waiting</Chip> 으로 부릅니다 (human-on-the-loop). 승인 피로
              최소.
            </Concept>
            <Concept icon={Radio} iconClass="text-signal" term="스스로 개선거리를 찾는다">
              세션 실패·반복 패턴·외부 정보를 자동으로 훑어 Signal 로 발행하고, triage 를 거쳐
              Project/Issue 로 전환합니다. 사람이 “문제 같아 보여”라고 지적할 때까지 기다리지
              않습니다.
            </Concept>
            <Concept icon={FileText} term="쓸수록 똑똑해진다 (지식 복리)">
              매 작업의 마무리(cleanup)에서 재사용할 지식이 Cell 지식으로 축적되고, 이후 워커가
              그걸 참조합니다. 같은 문제를 다시 푸는 비용이 시간이 갈수록 0 에 가까워집니다.
            </Concept>
            <Concept icon={Blocks} term="할 수 있는 일이 늘어난다 (행동 복리)">
              워커가 쓰는 capability·skill 목록은 고정이 아니라 동적입니다. 자기개선 루프가
              하네스를 점검해 부족한 능력을 Signal → Issue 로 만들어 추가하므로, 같은 cell 에서
              AI 가 해낼 수 있는 범위가 시간이 갈수록 넓어집니다 — 지식 복리의 ‘행동’ 버전.
            </Concept>
            <Concept icon={Settings} term="말이 아니라 실제로 ship">
              AI 가 설명만 하지 않습니다 — capability 호출로 상태 전이·자식 생성·commit·PR·
              preview·배포까지 실제로 수행합니다. 사람은 preview 링크 확인과 머지 결정만.
            </Concept>
          </div>
          <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mt-5 mb-2">
            인프라 — 클러스터·파이프라인·모니터링을 플랫폼이 운영
          </p>
          <div className="space-y-2.5">
            <Concept icon={Blocks} term="자동 배포 (Kubernetes + GitOps)">
              meta 앱 선언 + main 머지만으로 ArgoCD 가 dev·prd·preview 전 환경에 자동 동기화
              배포합니다. 빌드 이미지는 cell 격리 빌드로
              {' '}<span className="font-mono text-text">registry.lab.i-tems.com</span> 에 자동
              push. 클러스터 운영·매니페스트 작성·수동 sync 없음.
            </Concept>
            <Concept icon={Radio} term="스케줄 파이프라인 (Airflow)">
              <span className="font-mono text-text">kind: Schedule</span> YAML 만 쓰면 Kubernetes
              위 Airflow 에 DAG 로 자동 등록돼 cron 으로 실행되고 issue 로그는 보존됩니다. Airflow
              UI 조작·러너 관리 없음.
            </Concept>
            <Concept icon={Radio} iconClass="text-signal" term="비용 0 Preview">
              <span className="font-mono text-text">issue</span> 브랜치 push 시 미리보기 환경이
              자동 생성되고 브랜치 정리 시 자동 소멸합니다. 유휴 리소스 누적 0.
            </Concept>
            <Concept icon={Box} term="스토리지">
              S3 호환 오브젝트 스토리지 MinIO
              (<span className="font-mono text-text">minio.lab.i-tems.com</span>)와 공유 NFS
              작업공간이 제공됩니다. 버킷·디스크·NFS 서버 운영 없음.
            </Concept>
            <Concept icon={Settings} term="도메인·TLS·라우팅">
              <span className="font-mono text-text">*.lab.i-tems.com</span> 와일드카드 인증서와
              Traefik 으로, Ingress 만 만들면 HTTPS·DNS·라우팅이 자동 적용됩니다. 인증서 갱신 없음.
            </Concept>
            <Concept icon={Info} term="관찰가능성 포함">
              Prometheus·Grafana·Loki 가 메트릭·로그를 자동 수집하고, LLM 트레이스는 Langfuse 에
              연동됩니다. 모니터링 스택을 직접 구축할 필요 없음.
            </Concept>
          </div>
          <div className="mt-4 rounded-lg border border-accent/30 bg-accent-muted/40 p-4">
            <p className="text-sm text-text leading-relaxed">
              <span className="font-semibold">AI-enabled 가 아니라 AI-native.</span> 대부분의
              도구는 사람이 끌고 가는 기존 워크플로에 AI 를 ‘보조’로 얹습니다(AI-enabled). 여러분의
              Cell 은 작업의 실행 주체 자체가 에이전트이고 사람은 방향·게이트만 잡습니다 — 운영
              모델이 AI 중심으로 재설계된 <span className="font-semibold">AI-native</span>
              구조입니다. 그래서 처리량이 <span className="font-semibold">인원 수</span> 가 아니라
              {' '}<span className="font-semibold">위임한 프로젝트 수</span> 로 정해집니다: 한 사람이
              다수의 병렬 워커를 게이트로 운영하고(스쿼드 감독), 비용이 인원·성장과 분리됩니다.
              업계 보고도 AI-native 운영이 대규모 작업의 시간·노력을 최대 ~50% 줄이고 비용을
              인원과 디커플링한다고 말합니다. 여기에 위의 지식·행동 복리가 더해져 레버리지가
              시간이 갈수록 커집니다.
            </p>
          </div>
        </Card>

        {/* 9. 알아두면 좋은 것 */}
        <Card>
          <SectionTitle icon={Info} n={9}>알아두면 좋은 것</SectionTitle>
          <div className="space-y-2.5">
            <Concept icon={Info} term="hold">
              Issue/Project 에 hold 를 걸면 자동 워커가 그 항목을 집어가지 않습니다. 사람이 직접 손볼
              때 자율 실행과 충돌하지 않게 하는 안전장치이며, 끝나면 hold 를 해제합니다.
            </Concept>
            <Concept icon={Box} term="Cell 전환">
              Cell 마다 데이터가 격리됩니다. 좌상단에서 Cell 을 바꾸면 목록이 그 Cell 기준으로
              새로 로드됩니다.
            </Concept>
            <Concept icon={FileText} term="AI 활동 실시간 보기">
              Issue/Project 상세에서 워커의 도구 호출·결과·메시지가 흐릅니다. 막혔는지·진행 중인지
              여기서 확인합니다.
            </Concept>
          </div>
        </Card>

        {/* 10. 터미널 — 직접 claude 몰기 */}
        <Card>
          <SectionTitle icon={TerminalSquare} n={10}>터미널 — 직접 claude 몰기</SectionTitle>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            Issue 위임은 워커에게 <span className="font-semibold text-text">맡기고 게이트만</span>
            잡는 방식입니다. 반대로 직접 대화하며 손으로 몰고 싶을 때 — 막힌 Issue 디버깅, cell 레포
            탐색, 임시 분석 — 화면 우하단의 <span className="font-semibold text-text">터미널 버튼</span>
            {' '}(또는 <Chip>Ctrl+`</Chip>)으로 cell 샌드박스 셸을 엽니다. 처음 열면 현재
            Cell 의 세션이 자동 생성됩니다.
          </p>
          <div className="space-y-2.5">
            <Concept icon={TerminalSquare} term="claude 를 직접 실행">
              샌드박스 안에서 <span className="font-mono text-text">claude</span> 를 띄우면 워커와
              {' '}<span className="font-semibold text-text">같은 환경</span>입니다 — 그 Cell 의
              레포·<span className="font-mono text-text">.claude</span> 오버레이·skill·capability
              가 그대로 물려 있습니다. 다만 자동 Loop 워커 계약(상태 자동 전이·한 turn
              종결)은 적용되지 않는 <span className="font-semibold text-text">사람이 모는 대화형
              세션</span>이라, 단계마다 직접 지시하고 직접 마칩니다.
            </Concept>
            <Concept icon={Clock3} iconClass="text-warning" term="세션은 한시적">
              세션마다 TTL 이 있고(기본 4시간) 헤더의 남은 시간 배지가 만료가 가까우면 색으로
              경고합니다. 시계 버튼으로 1시간씩 연장, <span className="font-mono text-text">+</span>
              {' '}로 세션 추가, 드롭다운으로 전환, 휴지통으로 종료합니다
              (<Chip>Cmd/Ctrl+Shift+F</Chip> 전체화면).
            </Concept>
            <Concept icon={Info} term="끝나면 push 까지">
              샌드박스는 만료·종료 시 사라집니다. 워커와 같은 cell 레포이므로 작업은
              {' '}<span className="font-mono text-text">issue</span> 브랜치에서 하고 TTL 안에
              commit·push, PR 머지는 사람이 — 잃고 싶지 않은 변경은 세션을 닫기 전에 올립니다.
            </Concept>
          </div>
        </Card>
      </div>
    </div>
  )
}
