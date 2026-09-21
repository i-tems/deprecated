# platform/hive — 사람 수동 셸 세션 (델타만)

이 디렉토리는 폐기 수순이다. hive 정본(specs·rules·skills·capability 계약·transport)은
**i-tems/hive(`~/hive/.claude`)** 와 동일하며 claude 실행 시 워킹디렉토리로 함께 로드된다 —
여기서 재기술·복제하지 않는다. 본 파일은 그 워커 환경과 **다를 수밖에 없는 최소 델타**만 적는다.

## 비혼동 가드 (이 파일의 유일한 존재 이유)

두 계약을 혼동하지 말 것:

- `~/hive/.claude/CLAUDE.md` 는 **auto Loop 워커** 계약 — "You are a hive Loop worker", per-turn entity 주입·한 turn 내 종결·미전이 시 `status=error` 강제. **이 세션엔 적용되지 않는다.**
- 여기는 **사람이 대화형으로 직접 모는 수동 셸 세션** — entity 자동 주입 없음, 강제 종결/에러 전이 없음, 한 turn 제약 없음.

## 진입점

- Issue outcome 주도 / 직접 실행: `/steering-issues <id> [--direct]` (구 `/running-issues` 흡수,
  `--direct` 가 hold 가드 + 사람 직접 코드 실행)
- Project outcome 주도: `/steering-projects <id>`
- Initiative outcome 주도: `/steering-initiatives <id>`
- 신규 Issue 생성: `/creating-issues` · 세션 마감: `/wrapping-sessions`
  (모두 thin 래퍼, 의미론 정본 = i-tems/hive specs·`/processing-issues`)
- cross-cell 광역 1:1: `/attending-user`

## 활성 cell · Transport

이 셸 세션의 활성 cell = **infra**. capability transport 는 사용자 스코프 MCP 서버 `hive`
(hub `/mcp/` 노출) — cell 바인딩 규약 정본은 i-tems/hive `capability_rule.md`. 이 환경의 델타:

- 셸 환경변수 `CELL_ID=infra` (워커 pod 가 쓰는 변수와 동일, `~/.bashrc` 에 기본값 export).
- 본 셸의 기본 대상 cell = `$CELL_ID`. 타 cell 작업(`/triaging-signals items` 등)은 `cell` 인자만 바꾼다.
- skill 의 cell 인자 생략 시 `$CELL_ID` 를 처리 대상 cell 로 본다.
- 구 계약의 kubectl port-forward·curl·토큰 발급 부트스트랩은 폐기(불필요).

## 사람 주도 델타

- 작업은 worktree+브랜치 안에서만. 원본 working tree 직접 수정 금지.
- 코드→PR→**merge→배포 반영 확인까지 이 세션에서 사람이 끝낸다** (워커의 cleanup 단계를
  사람이 직접 수행). PR 생성에서 멈추지 않는다.
- **PR 머지는 사용자 별도 승인 없이 진행한다.** 사용자가 변경 결과를 확인하려면 어차피 머지·배포 반영이
  필요해 매 PR 마다 게이트를 두면 마찰만 누적된다. 머지 후 sync·rollout 확인까지 한 번에 종결.
  단, PR 외 형태의 임계값 이상 변경(force push, schema/DB migration, 외부 통지 등)은 그 아래 "되돌리기
  어려운..." 줄 그대로 사용자 결정 요청.
- **merge 직후 두 working tree 를 sync (수동)** — `git -C /home/items/everything pull --ff-only origin main`·`git -C /home/items/hive pull --ff-only origin main`.
  ref(`origin main`) 를 명시한다 — 공유 `.git` 에서 다른 워커의 동시 `fetch` 가 `FETCH_HEAD` 를 덮어 인자 없는 `pull` 이 `Cannot fast-forward to multiple branches` 로 실패할 수 있다. 미수행 시 worktree 분기 기준(everything)·`~/hive/.claude` 직접 열람 정본(hive)이 stale 해 옛 spec/rule 로 판단한다.
- 되돌리기 어려운/공유 상태·공개 계약 변경은 사용자 결정을 요청한다.
- 개인 세션 중 대상 entity 는 `hold` 로 agent-loop 자동 픽업 차단 (정본 = `/steering-issues`
  `--direct` 모드 hold 계약). 세션 종료 시 hold 해제 누락 점검.
