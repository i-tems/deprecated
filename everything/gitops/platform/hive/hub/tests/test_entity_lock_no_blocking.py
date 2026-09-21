"""INFRA-ISSUE-277 회귀 테스트 — entity_lock critical section 불변식.

entity_lock(flock) 은 동기 syscall 이라 이벤트 루프를 블록한다. 그 블록 안에서
``await`` 로 yield 하면, 같은 cell 의 다른 task 가 같은 flock 을 동기 획득하려다
루프를 멈춰 cross-task 데드락이 된다 (self-deadlock #641 의 cross-task 변종).
또 블록 안에서 blocking I/O(`preview_readiness`→urlopen)를 치면 그 네트워크 왕복
동안 루프 전체가 hang 한다.

따라서 불변식: ``with entity_lock(...)`` 블록 안에는
  (1) ``await`` 가 없어야 하고,
  (2) blocking I/O 헬퍼(`preview_readiness`)를 호출하지 않아야 한다.

hub 테스트 규약상 app 패키지(런타임 의존)를 import 하지 않는다 — 소스를 ast 로
정적 분석한다 (test_preview_review_guard 동일 패턴).
"""

import ast
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"

# entity_lock 을 쓰는 모든 모듈.
_TARGETS = sorted((_APP / "entities").glob("*.py")) + [_APP / "events.py"]

# 블록 안에서 부르면 루프를 막는 blocking I/O 헬퍼 (네트워크 등).
_BLOCKING_CALLS = {"preview_readiness"}


def _is_entity_lock_with(node: ast.With) -> bool:
    for item in node.items:
        call = item.context_expr
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "entity_lock":
            return True
    return False


def _violations(path: Path):
    """(file, lineno, kind) 리스트 — entity_lock 블록 안의 await / blocking 호출."""
    src = path.read_text()
    tree = ast.parse(src)
    out = []
    for with_node in ast.walk(tree):
        if not (isinstance(with_node, ast.With) and _is_entity_lock_with(with_node)):
            continue
        for inner in ast.walk(with_node):
            if inner is with_node:
                continue
            # 중첩 entity_lock 블록은 그 자체가 재진입(no-op)이라 await 검사는 바깥
            # 블록 기준으로 충분 — 그래도 walk 가 전부 훑으므로 await 면 어디든 잡는다.
            if isinstance(inner, ast.Await):
                out.append((path.name, inner.lineno, "await"))
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id in _BLOCKING_CALLS:
                out.append((path.name, inner.lineno, f"blocking:{inner.func.id}"))
    return out


class EntityLockNoBlockingTest(unittest.TestCase):
    def test_no_await_or_blocking_inside_entity_lock(self):
        all_violations = []
        for path in _TARGETS:
            if path.exists():
                all_violations.extend(_violations(path))
        self.assertEqual(
            all_violations, [],
            "entity_lock 블록 안에서 await/blocking I/O 발견 (cross-task 데드락·루프 hang 위험):\n"
            + "\n".join(f"  {f}:{ln} — {kind}" for f, ln, kind in all_violations),
        )


if __name__ == "__main__":
    unittest.main()
