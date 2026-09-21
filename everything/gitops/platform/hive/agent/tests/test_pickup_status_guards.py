"""pre-dispatch TOCTOU 가드의 valid status 집합 검증.

INFRA-ISSUE-263 후속: terminal(issue done/cancelled · 컨테이너 done/archive)·error·
backlog 은 work_finder 가 더 이상(애초에) enqueue 하지 않으므로 pre-dispatch 가드의
valid 집합에서도 빠졌다. snapshot 이후 사람이 종결한 race 로 fresh status 가 그 상태가
되면 가드가 skip 한다 (loop._still_actionable 도 같은 의미 — 그쪽은 kubernetes import
때문에 로컬 단위테스트 불가, work_finder enqueue status 와 같은 집합으로 일관).
"""

import unittest
from types import SimpleNamespace

from app.phase_handlers.pre import (
    _fetch_and_guard,
    _VALID_STATUSES,
    _VALID_STATUSES_CONTAINER,
)


class _Client:
    def __init__(self, status):
        self._status = status

    def api_safe(self, name, params, **kw):
        return {"data": {"status": self._status, **params}}


def _ctx(status):
    return SimpleNamespace(
        client=_Client(status),
        log=SimpleNamespace(warning=lambda *a, **k: None),
    )


class ValidStatusSetTests(unittest.TestCase):
    def test_issue_set_is_enqueueable_only(self):
        self.assertEqual(_VALID_STATUSES, {"todo", "running", "waiting", "cleanup"})
        for excluded in ("done", "cancelled", "error"):
            self.assertNotIn(excluded, _VALID_STATUSES)

    def test_container_set_is_enqueueable_only(self):
        self.assertEqual(_VALID_STATUSES_CONTAINER, {"active", "waiting"})
        for excluded in ("done", "archive", "backlog"):
            self.assertNotIn(excluded, _VALID_STATUSES_CONTAINER)


class FetchAndGuardTests(unittest.TestCase):
    def test_terminal_issue_skipped(self):
        # race: enqueue(running 등) 이후 사람이 종결 → fresh 가 terminal → skip.
        for terminal in ("done", "cancelled"):
            self.assertIsNone(
                _fetch_and_guard(_ctx(terminal), "issue", "T-1", _VALID_STATUSES),
                f"terminal={terminal} 인데 skip 안 함",
            )

    def test_enqueueable_issue_passes(self):
        for ok in ("todo", "running", "waiting", "cleanup"):
            entity = _fetch_and_guard(_ctx(ok), "issue", "T-1", _VALID_STATUSES)
            self.assertIsNotNone(entity)
            self.assertEqual(entity["status"], ok)

    def test_terminal_container_skipped(self):
        for terminal in ("done", "archive"):
            self.assertIsNone(
                _fetch_and_guard(_ctx(terminal), "project", "G-1", _VALID_STATUSES_CONTAINER),
                f"terminal={terminal} 인데 skip 안 함",
            )

    def test_active_container_passes(self):
        for ok in ("active", "waiting"):
            entity = _fetch_and_guard(_ctx(ok), "project", "G-1", _VALID_STATUSES_CONTAINER)
            self.assertIsNotNone(entity)
            self.assertEqual(entity["status"], ok)


if __name__ == "__main__":
    unittest.main()
