"""wake_bus in-process version-feed 단위테스트.

wake_bus 는 hub 단일 replica 전제의 in-process pubsub 이다: `notify(key)` 가
in-process version 을 +1 하고 그 key 의 condition 을 fanout, `wait_for_change`
는 진입 시 baseline 을 잡아 value 비교로 깬다 (edge-trigger lost-wakeup 없음).

검증 대상 (외부 계약 보존):
- 대기 중 notify → wait_for_change True (timeout 내, poll 없이 즉시)
- 변경 없으면 timeout 후 False
- baseline: 진입 *이전* 의 변경(version)은 깨우지 않음
- 진입 *이후* 의 변경만 깨움
- fanout issue 가 지연돼도(version 만 +1) value 비교로 결국 깬다 (lost-wakeup 방어)
- 대기자 없어도 notify 는 version 을 누적 (다음 wait 의 baseline 정확)
- 빈 key 는 timeout 후 False
- 대기 종료 후 refcount/condition 정리 (메모리 누수 방지)
"""

import asyncio
import importlib.util
import os
import unittest

# app/__init__.py 는 capability_framework 등 무거운 런타임 의존을 끌어오므로
# (다른 hub 테스트들과 동일하게) 패키지 import 를 피하고 wake_bus.py 만 파일에서
# 직접 로드한다. wake_bus 는 이제 stdlib(asyncio/logging) 만 의존한다.
_WB_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "wake_bus.py")
_spec = importlib.util.spec_from_file_location("wake_bus", _WB_PATH)
wake_bus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wake_bus)


class WakeBusTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        wake_bus._CONDS.clear()
        wake_bus._VERSION.clear()
        wake_bus._WATCH_COUNT.clear()

    async def test_notify_wakes_waiter_within_timeout(self):
        waiter = asyncio.create_task(wake_bus.wait_for_change("issue:1", timeout=5.0))
        await asyncio.sleep(0)            # 대기자 등록 (baseline=0) + cond.wait 진입
        wake_bus.notify("issue:1")         # in-process 변경 → 즉시 fanout
        self.assertTrue(await asyncio.wait_for(waiter, timeout=1.0))

    async def test_timeout_returns_false_without_change(self):
        self.assertFalse(await wake_bus.wait_for_change("issue:none", timeout=0.05))

    async def test_baseline_ignores_prior_change(self):
        # 진입 전에 일어난 변경은 baseline 으로 잡혀 깨우지 않는다.
        wake_bus.notify("cell:c1")        # 대기자 없음 — version=1 만 기록
        result = await wake_bus.wait_for_change("cell:c1", timeout=0.05)
        self.assertFalse(result)

    async def test_only_change_after_registration_wakes(self):
        wake_bus.notify("cell:c2")        # 진입 전 → baseline=1
        waiter = asyncio.create_task(wake_bus.wait_for_change("cell:c2", timeout=5.0))
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())   # baseline 과 동일 → 아직 안 깸
        wake_bus.notify("cell:c2")        # baseline 이후 새 변경 → version=2
        self.assertTrue(await asyncio.wait_for(waiter, timeout=1.0))

    async def test_delayed_fanout_still_wakes_via_value_compare(self):
        # version 은 +1 됐으나 _fanout issue 가 안 돈(=fanout 유실) 상황에서도
        # 짧은 timeout 의 inner wait 가 깨어 loop 상단 value 비교로 True.
        waiter = asyncio.create_task(
            wake_bus.wait_for_change("issue:lw", timeout=0.2)
        )
        await asyncio.sleep(0)            # 등록 + cond.wait 진입
        wake_bus._VERSION["issue:lw"] = wake_bus._VERSION.get("issue:lw", 0) + 1
        # cond.notify_all() 을 일부러 호출하지 않음 (fanout 유실 모사).
        self.assertTrue(await asyncio.wait_for(waiter, timeout=1.0))

    async def test_notify_accumulates_version_without_waiter(self):
        # 대기자가 없어도 notify 는 in-process version 을 누적한다.
        wake_bus.notify("cell:c3")
        wake_bus.notify("cell:c3")
        self.assertEqual(wake_bus._VERSION.get("cell:c3"), 2)

    async def test_empty_key_returns_false(self):
        self.assertFalse(await wake_bus.wait_for_change("", timeout=0.01))

    async def test_watch_refcount_cleaned_up(self):
        w = asyncio.create_task(wake_bus.wait_for_change("issue:rc", timeout=0.05))
        await asyncio.sleep(0)
        self.assertEqual(wake_bus._WATCH_COUNT.get("issue:rc"), 1)
        await w
        self.assertNotIn("issue:rc", wake_bus._WATCH_COUNT)
        self.assertNotIn("issue:rc", wake_bus._CONDS)


if __name__ == "__main__":
    unittest.main()
