"""INFRA-ISSUE-277 회귀 테스트 — entity_lock 재진입.

issue_update 가 entity_lock 보유 중 emit_event→_touch_entity_activity 가 같은 file 을
재획득하던 self-deadlock(같은-프로세스·다른-fd flock 블록) 방지. 같은 실행 컨텍스트의
중첩 acquire 는 no-op 으로 통과해야 한다. (Deck M2 #609 회귀 고정.)

hub 테스트 규약상 app 패키지를 직접 import 하지 않는다 (fastapi·capability_framework
런타임 부재). storage/jsonl.py 를 importlib 로 격리 로드한다 — entity_lock 은 stdlib 만
쓰고 .sql 은 read_jsonl 안에서 lazy import 되므로 standalone 로드가 안전하다.
"""
import asyncio
import importlib.util
import os
import threading
import unittest
from pathlib import Path

_JSONL_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "storage", "jsonl.py")
_spec = importlib.util.spec_from_file_location("hive_jsonl_under_test", _JSONL_PATH)
_jsonl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jsonl)
entity_lock = _jsonl.entity_lock


class EntityLockReentrantTest(unittest.TestCase):
    def test_nested_same_path_no_deadlock(self):
        p = Path("/tmp/hive-test-reentrant-a.jsonl")
        done = []

        def work():
            with entity_lock(p):
                with entity_lock(p):  # 재진입 — 예전엔 flock self-deadlock
                    done.append(True)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(timeout=5)
        self.assertEqual(done, [True], "nested entity_lock deadlocked or did not complete")

    def test_reentrant_across_await(self):
        """issue_update→(await)→_touch_entity_activity 와 동일 구조."""
        p = Path("/tmp/hive-test-reentrant-b.jsonl")

        async def work():
            with entity_lock(p):
                await asyncio.sleep(0.01)
                with entity_lock(p):  # _touch 모사 — 같은 task 컨텍스트 → 재진입
                    return True

        self.assertTrue(asyncio.run(asyncio.wait_for(work(), timeout=5)))

    def test_sequential_acquire_still_serializes(self):
        """비중첩 순차 acquire — 블록 종료 시 flock·held 해제되어 재진입 가능."""
        p = Path("/tmp/hive-test-reentrant-c.jsonl")
        with entity_lock(p):
            pass
        with entity_lock(p):
            pass

    def test_held_set_cleared_after_block(self):
        p = Path("/tmp/hive-test-reentrant-d.jsonl")
        with entity_lock(p):
            self.assertEqual(len(_jsonl._held_lock_keys.get()), 1)
        self.assertEqual(len(_jsonl._held_lock_keys.get()), 0)


if __name__ == "__main__":
    unittest.main()
