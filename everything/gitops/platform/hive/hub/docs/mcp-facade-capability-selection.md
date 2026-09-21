# MCP 전용 함수(facade) 선정 — 실측 호출 빈도 근거

> INFRA-TASK-17. 자주 쓰는 capability 를 generic `capability_invoke` 인다이렉션
> 없이 호출하도록 레지스트리 기반 전용 함수 툴로 동적 노출한다. 어떤
> capability 를 승격할지는 **추정이 아니라 실측**으로 정한다.

## 측정 방법

소스: 운영 hub 의 Prometheus 카운터 `hive_capability_total`
(`/metrics`, `app/metrics.py`). principal_type 별 누적 호출수.
스냅샷: **2026-05-17** (hive-hub.hive.svc.cluster.local:8000, 전 기간 누적).

선정 대상은 "MCP 호출자가 describe→invoke 인다이렉션 비용을 실제로 무는
capability". 따라서 다음을 분리한다.

- **`worker`(AI 워커) + `cli`(수동 platform-hive-shell)** = MCP 도구 호출자.
  이 둘이 generic `capability_invoke` + 선행 `capability_describe` 왕복
  비용을 직접 무는 주체 → **선정 기준 축**.
- `user`(콘솔 UI) 는 MCP 가 아니라 HTTP API 를 직접 호출하므로 인다이렉션
  비용 대상이 아니다. "자주 쓰임"의 방증으로만 괄호 참고.
- `system`(agent-loop·poller) 의 `worker.heartbeat`/`wake.wait_for_change`/
  `task.list`/`goal.list` 대량 호출은 하네스 기계 호출이지 AI/사람의 MCP
  도구 사용이 아니다 → 선정 대상에서 제외.

## 실측 (worker+cli 기준 내림차순, 인프라 기계호출 제외)

| capability | worker | cli | (user) | **worker+cli** | 비고 |
|---|--:|--:|--:|--:|---|
| worker.heartbeat | 7287 | 0 | 0 | 7287 | 하네스 기계호출 — 제외 |
| wake.wait_for_change | 492 | 0 | 0 | 492 | 하네스 기계호출 — 제외 |
| **goal.get** | 88 | 16 | 214 | **104** | 선정 |
| **task.get** | 74 | 12 | 110 | **86** | 선정 (1차 후보·DoD) |
| **task.update** | 32 | 45 | 0 | **77** | 선정 (1차 후보·DoD) |
| **task.list** | 37 | 23 | 286 | **60** | 선정 (1차 후보·DoD) |
| **event.list** | 42 | 11 | 231 | **53** | 선정 |
| **event.add** | 14 | 34 | 5 | **48** | 선정 |
| **goal.list** | 29 | 7 | 291 | **36** | 선정 |
| goal.update | 12 | 22 | 0 | 34 | 후보 — 1차 제외(아래) |
| task.save | 0 | 21 | 0 | 21 | cli upsert. 1차 제외 |
| signal.emit | 8 | 13 | 0 | 21 | long-tail 유지 |
| **task.create** | 9 | 0 | 1 | **9** | 선정 (1차 후보·DoD) |

## 선정 결과 (기본 8종)

```
task.create  task.get  task.update  task.list
goal.get     goal.list event.list   event.add
```

근거:

1. **task 4종**(`task.create/get/update/list`) — 과제 1차 후보이자 DoD 명시
   대상. `task.create` 는 절대 호출수는 낮지만(주로 신규 ticket 생성 시점)
   ticket 워크플로의 진입점이라 발견성 가치가 커 포함. ticket/task 계열
   인다이렉션 제거가 본 과제의 원천 동기(NESS-TASK-4).
2. **goal.get / goal.list / event.list / event.add** — worker+cli 실측에서
   task 4종과 동급 이상으로 빈번하고 ticket 작업 흐름에 직접 인접
   (goal 맥락 조회·활동 피드 읽기/코멘트). 인다이렉션 제거 효용이 가장 큰
   구간.
3. **제외**: `goal.update`(34) 는 경계선이나 1차 범위를 task/ticket 핵심에
   고정. `task.save`·`signal.*`·`*.set_session`·`worker.*` 등은 long-tail
   → generic `capability_invoke` 로 그대로(무변경).

선정 *집합*은 운영 데이터가 바뀌면 재평가한다. 코드 변경 없이
`MCP_FACADE_CAPABILITIES`(콤마구분 env)로 재정의 가능하며, **스키마는 항상
레지스트리에서 동적 생성**된다(정적 작성 0 → 드리프트 0).

## 설계 (요약)

- `app/mcp_facade.py`: tools/list 시점에 선정 capability 별 전용 Tool 을
  동적 생성. inputSchema 는 `capability.describe` 와 **동일 코드 경로**
  (`introspection._extract_request_schema`/`_resolve_ref`)로 hub OpenAPI 에서
  추출 → 손으로 박은 정적 스키마 0, 정본과 드리프트 0.
- generic `capability_invoke`/`_list`/`_describe` 는 무변경. 전용 함수는 그
  위 facade 로 동일 dispatch(`_invoke_internal`)·동일 응답 봉투·동일
  cell/auth 헤더 전파 → long-tail 경로·하위호환 무영향.
- 동등성·하위호환 회귀는
  `tests/test_mcp_facade_schema_equivalence.py` 가 자동 검증
  (facade.parameters == capability.describe.parameters 바이트 동일,
  메타툴 3종 잔존, 비선정 capability 전용 함수 부재, passthrough dispatch).
