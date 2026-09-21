"""pr.status capability 의 순수 로직 검증 (HTTP 호출 없음).

PR URL parsing 과 GitHub PR 객체 → state derive 로직만 단위 테스트.
HTTP 경로 (httpx + 캐시) 는 별도 mock 인프라가 필요하므로 여기서 다루지 않는다.
"""

import importlib.util
import os
import sys
import types
import unittest


def _load(name: str, rel_path: str):
    here = os.path.dirname(os.path.abspath(__file__))
    full = os.path.normpath(os.path.join(here, "..", rel_path))
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# pr.py 는 base image 의 `capability_framework` (CapabilityResponse), fastapi
# (APIRouter, Request), pydantic, httpx, hub 의 `..gitea_mirror` 에 의존.
# 단위 테스트는 pure 로직(_parse_pr_url, _derive_state)만 보므로 다 가짜로 충분.
# 다른 hub 테스트가 fastapi 를 stub 으로 등록할 수 있으므로 (test_cursor_and_me_alias
# 등) 우리도 같은 패턴으로 필요한 심볼을 stub 에 추가한다.
_cf_stub = types.ModuleType("capability_framework")
_cf_stub.CapabilityResponse = lambda **kw: kw
sys.modules.setdefault("capability_framework", _cf_stub)

_fastapi = sys.modules.get("fastapi") or types.ModuleType("fastapi")
for _sym in ("APIRouter", "Request"):
    if not hasattr(_fastapi, _sym):
        setattr(_fastapi, _sym, type(_sym, (), {"__init__": lambda self, *a, **kw: None,
                                                 "post": lambda self, *a, **kw: lambda f: f}))
sys.modules["fastapi"] = _fastapi

_gitea_mirror = _load("gitea_mirror_under_test", "app/gitea_mirror.py")
sys.modules.setdefault("app", types.ModuleType("app"))
sys.modules["app.gitea_mirror"] = _gitea_mirror
_pr = _load("app.entities.pr_under_test", "app/entities/pr.py")


class TestParsePrUrl(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            _pr._parse_pr_url("https://github.com/i-tems/cell-beauty/pull/6"),
            ("i-tems", "cell-beauty", 6),
        )

    def test_trailing_slash(self):
        self.assertEqual(
            _pr._parse_pr_url("https://github.com/i-tems/everything/pull/123/"),
            ("i-tems", "everything", 123),
        )

    def test_extra_path_segment(self):
        # `/pull/6/files` 같은 deep link 도 PR 번호 추출은 동일하게.
        self.assertEqual(
            _pr._parse_pr_url("https://github.com/i-tems/cell-beauty/pull/6/files"),
            ("i-tems", "cell-beauty", 6),
        )

    def test_non_github(self):
        self.assertIsNone(_pr._parse_pr_url("https://gitlab.com/x/y/pull/1"))

    def test_not_a_pr(self):
        self.assertIsNone(_pr._parse_pr_url("https://github.com/i-tems/cell-beauty"))

    def test_pr_num_not_int(self):
        self.assertIsNone(_pr._parse_pr_url("https://github.com/i-tems/cell-beauty/pull/foo"))

    def test_empty(self):
        self.assertIsNone(_pr._parse_pr_url(""))


class TestDeriveState(unittest.TestCase):
    def test_merged_wins_over_state_closed(self):
        # GitHub 머지된 PR 은 state='closed' + merged=True. merged 가 우선.
        self.assertEqual(
            _pr._derive_state({"merged": True, "state": "closed", "draft": False}),
            {"state": "merged", "mergeable": None},
        )

    def test_closed_not_merged(self):
        self.assertEqual(
            _pr._derive_state({"merged": False, "state": "closed", "draft": False}),
            {"state": "closed", "mergeable": None},
        )

    def test_open_mergeable(self):
        self.assertEqual(
            _pr._derive_state({"merged": False, "state": "open", "draft": False, "mergeable": True}),
            {"state": "open", "mergeable": True},
        )

    def test_open_mergeable_unknown(self):
        # GitHub 가 mergeability 계산 중이면 null.
        self.assertEqual(
            _pr._derive_state({"merged": False, "state": "open", "draft": False, "mergeable": None}),
            {"state": "open", "mergeable": None},
        )

    def test_draft(self):
        self.assertEqual(
            _pr._derive_state({"merged": False, "state": "open", "draft": True, "mergeable": False}),
            {"state": "draft", "mergeable": False},
        )


if __name__ == "__main__":
    unittest.main()
