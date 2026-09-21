"""worker activity 스트림이 워커 자신의 idle long-poll 을 깨우지 않게 하는
wake 키 분리 회귀 가드.

근본 버그(관측: issue `waiting` 진입 38s 동안 빈 유료 turn 6회, ~4-11s 간격):
`worker.activity_push` 가 `wake_bus.notify(entity_id)` 로 bare entity_id 키를
bump 했다. 그 키는 agent 워커의 idle long-poll
(`worker._wait_for_wake` → `wake.wait_for_change` → `wake_bus
.wait_for_change(entity_id)`)이 듣는 키와 동일 → 워커가 자기 transcript
스트림으로 자기 대기를 깨워 빈 turn 을 busy-loop 했다.

수정 계약 (이 테스트가 잠그는 불변식):
  1. `worker.activity_push` 의 wake 통지는 bare `entity_id` 가 아니라
     `_act_wake_key(entity_id)` (= `act:<id>`) 전용 키여야 한다.
  2. `_act_wake_key` 는 `act:` 접두 키를 만든다 (bare entity_id 와 분리).
  3. `sse.subscribe` 의 entity 구독은 `entity_id` 와 `act:{entity_id}` 를
     모두 포함해야 한다 — 워커는 안 깨우되 UI 패널은 near-real-time 유지.

hub 테스트 규약상 app 패키지를 import 하지 않는다 (capability_framework 등
런타임 전용 의존 부재). 대신 소스를 `ast` 로 파싱해 함수 본문 불변식을 검증한다.
"""

import ast
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"
_WORKER_SRC = _APP / "entities" / "worker.py"
_SSE_SRC = _APP / "entities" / "sse.py"


def _func(src: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{src.name}: {name} 정의를 찾지 못함")


class ActivityWakeKeyIsolationTest(unittest.TestCase):
    def test_activity_push_notifies_dedicated_key_not_bare_entity_id(self):
        """worker.activity_push 는 _act_wake_key(entity_id) 로만 notify 한다."""
        fn = _func(_WORKER_SRC, "worker_activity_push")
        notify_args = []
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "notify"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "wake_bus"
            ):
                notify_args.append(node.args[0] if node.args else None)

        self.assertEqual(
            len(notify_args), 1,
            "activity_push 내 wake_bus.notify 호출은 정확히 1곳이어야 함",
        )
        arg = notify_args[0]
        # 회귀 형태: wake_bus.notify(entity_id) — bare Name 직접 전달 금지.
        self.assertFalse(
            isinstance(arg, ast.Name) and arg.id == "entity_id",
            "activity_push 가 bare entity_id 로 notify → 워커 idle long-poll 자가-wake 회귀",
        )
        # 정상 형태: wake_bus.notify(_act_wake_key(entity_id)).
        self.assertTrue(
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Name)
            and arg.func.id == "_act_wake_key",
            "activity_push 는 _act_wake_key(entity_id) 전용 키로 notify 해야 함",
        )

    def test_act_wake_key_is_prefixed_and_distinct(self):
        """_act_wake_key 는 bare entity_id 와 구분되는 act: 접두 키를 만든다."""
        fn = _func(_WORKER_SRC, "_act_wake_key")
        ret = next((n for n in ast.walk(fn) if isinstance(n, ast.Return)), None)
        self.assertIsNotNone(ret, "_act_wake_key 에 return 이 없음")
        rendered = ast.unparse(ret.value)
        self.assertIn("act:", rendered, f"_act_wake_key 가 act: 접두를 안 붙임: {rendered}")
        self.assertIn("entity_id", rendered)
        # bare entity_id 그대로 반환(접두 없음)하는 회귀 차단.
        self.assertNotEqual(rendered.strip(), "entity_id")

    def test_sse_entity_subscription_includes_both_keys(self):
        """sse.subscribe 의 entity 구독은 entity_id 와 act:{entity_id} 둘 다 포함."""
        fn = _func(_SSE_SRC, "sse_subscribe")
        appended = set()
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "keys"
                and node.args
            ):
                appended.add(ast.unparse(node.args[0]))

        self.assertIn(
            "entity_id", appended,
            "sse 구독에 bare entity_id 누락 → 본문 변경 시 detail refetch 안 됨",
        )
        act_keys = [a for a in appended if "act:" in a and "entity_id" in a]
        self.assertTrue(
            act_keys,
            "sse 구독에 act:{entity_id} 누락 → activity 패널이 더 이상 "
            "near-real-time refetch 안 됨 (수정의 UI 보전 절반이 깨짐)",
        )


if __name__ == "__main__":
    unittest.main()
