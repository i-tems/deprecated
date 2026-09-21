"""Entity 변경 push 알림 — in-process version-feed bus.

worker / agent-loop 가 `wake.wait_for_change` 로 long-poll 진입 → 해당 key
(entity_id 또는 `cell:<cell_id>` 등) 변경 시 즉시 응답. `emit_event` 와 status
전이 / entity 생성 capability 가 `notify` 를 호출.

설계 (hub replicas=1 전제):
- capability_invoke · emit_event · status 전이가 전부 단일 Hub 프로세스를
  통과하므로, 변경을 일으키는 쪽과 wait 중인 쪽이 같은 event loop 를 공유한다.
  따라서 in-process `asyncio.Condition` 으로 완결·정확하다 — poll · DB 왕복 ·
  executor offload 없음, wake 지연 0.
- lost-wakeup 방어: `notify` 가 올린 in-process version 을 wait 진입 시점
  `baseline` 과 *value 비교* 한다 (edge-trigger 아님, textbook condition 패턴).
  notify 가 wait 진입 직전에 발생해도 version 이 이미 올라가 있어 안 놓친다.

PR97~100 의 cross-process MySQL `wake_versions` version-feed + 1s poller 는
단일 replica 에선 "없는 문제를 푸는" 오버헤드라 제거했다. 외부 계약은 PR97 과
동일하게 보존된다: `notify(key)` / `async wait_for_change(key, timeout) -> bool`
시그니처와 `wake.wait_for_change` HTTP 응답(`wake_reason`) 의미.

hub 가 동시 다중 replica 로 확장되면(규모 ↑) cross-process bus 가 필요해진다:
이 파일이 그 교체 seam 이다 — `notify` → 외부 bus(Kafka 등) produce,
별도 consumer issue → `_VERSION` bump + `cond.notify_all()`. `wait_for_change`
와 공개 API 는 그대로 둔 채 내부만 갈아끼우면 된다.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("hub.wake_bus")

_CONDS: dict[str, asyncio.Condition] = {}
_VERSION: dict[str, int] = {}       # key 별 in-process 단조 변경 카운터
_WATCH_COUNT: dict[str, int] = {}   # key 별 활성 대기자 수 (condition GC 용)


def _cond_for(key: str) -> asyncio.Condition:
    cond = _CONDS.get(key)
    if cond is None:
        cond = asyncio.Condition()
        _CONDS[key] = cond
    return cond


def notify(key: str) -> None:
    """key 변경을 알린다 — in-process version +1 후 대기자 fanout.

    sync / async 어느 컨텍스트에서 호출해도 안전. version bump 는 **동기**라
    즉시 가시화되어 lost-wakeup 을 막는다 (대기자가 baseline 비교로 관측).
    condition fanout 은 running loop 가 있을 때만 schedule — Hub 의 모든 변경
    경로(capability 핸들러·emit_event)는 event loop 안에서 도므로 정상 경로엔
    항상 loop 가 있다. loop 가 없는 예외 컨텍스트(CLI/테스트)에선 version 만
    올라가고, 다음 `wait_for_change` 가 baseline 비교로 그 변경을 관측한다.
    """
    if not key:
        return
    _VERSION[key] = _VERSION.get(key, 0) + 1
    cond = _CONDS.get(key)
    if cond is None:
        return  # 대기자 없음 — version 만 기록 (다음 wait 가 baseline 으로 관측)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _fanout() -> None:
        async with cond:
            cond.notify_all()

    loop.create_task(_fanout())


async def wait_for_change(key: str, timeout: float) -> bool:
    """key 변경 발생까지 대기. timeout 초 후 False.

    baseline(진입 시점 version) 대비 version 이 증가하면 True. value 비교라
    notify 가 baseline 확보 직후·wait 진입 직전에 발생해도 놓치지 않는다.
    """
    if not key:
        await asyncio.sleep(max(0.0, timeout))
        return False
    cond = _cond_for(key)
    _WATCH_COUNT[key] = _WATCH_COUNT.get(key, 0) + 1
    baseline = _VERSION.get(key, 0)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout)
    try:
        async with cond:
            while _VERSION.get(key, 0) == baseline:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return False
                try:
                    await asyncio.wait_for(cond.wait(), remaining)
                except asyncio.TimeoutError:
                    # 진짜 timeout 인지 fanout 지연(version 은 +1 됐으나
                    # _fanout issue 가 아직 안 돈 경우)인지는 loop 상단의
                    # value 비교가 판정한다 — 여기서 단정하지 않는다.
                    pass
            return True
    finally:
        n = _WATCH_COUNT.get(key, 0) - 1
        if n <= 0:
            _WATCH_COUNT.pop(key, None)
            # 대기자가 없어진 key 의 condition 은 메모리 누수 방지로 제거
            # (다음 대기자가 재생성). version 은 보존 — 대기자 0 동안의
            # notify +1 누적이 다음 wait 의 baseline 을 정확히 만든다
            # (단일 프로세스 메모리 dict, 프로세스 생명주기 한정).
            _CONDS.pop(key, None)
        else:
            _WATCH_COUNT[key] = n
