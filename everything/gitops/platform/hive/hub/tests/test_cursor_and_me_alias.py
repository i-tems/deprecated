"""cursor / me-alias 단위 테스트 — Linear MCP 흡수 Wave 1.

opaque cursor 인코딩 라운드트립 + offset_page 페이지 경계 + resolve_me_alias 단축형 치환.
실제 fastapi 환경 없이 ast 로 안전하게 단독 로드한다 (test_is_mcp_channel 패턴과 동일).
"""

import importlib.util
import os
import sys
import types
import unittest


# fastapi stub — owner.py 가 from fastapi import Request 만 한다 (타입 힌트용).
if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")

    class _Request:
        def __init__(self, headers=None):
            self.headers = headers or {}

    fastapi_stub.Request = _Request
    sys.modules["fastapi"] = fastapi_stub


# storage stub — owner.py 가 from .storage import find_entity 한다.
def _stub_storage_pkg():
    pkg = types.ModuleType("app")
    pkg.__path__ = []  # mark as package
    sys.modules["app"] = pkg
    storage = types.ModuleType("app.storage")
    storage.find_entity = lambda *a, **k: (None, None)
    sys.modules["app.storage"] = storage


_stub_storage_pkg()


def _load(name: str, rel_path: str):
    here = os.path.dirname(os.path.abspath(__file__))
    full = os.path.normpath(os.path.join(here, "..", rel_path))
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cursor_mod = _load("app.cursor", "app/cursor.py")
owner_mod = _load("app.owner", "app/owner.py")


class _State:
    pass


class _Req:
    def __init__(self, email=None):
        self.state = _State()
        if email is not None:
            self.state.user_email = email


class TestCursor(unittest.TestCase):
    def test_round_trip(self):
        tok = cursor_mod.encode_cursor({"offset": 42})
        self.assertEqual(cursor_mod.decode_cursor(tok), {"offset": 42})

    def test_decode_none_returns_empty(self):
        self.assertEqual(cursor_mod.decode_cursor(None), {})

    def test_decode_garbage_returns_empty(self):
        # 손상된 토큰은 호출자가 처음부터 다시 시작하도록 빈 dict.
        self.assertEqual(cursor_mod.decode_cursor("not-a-real-cursor!!!"), {})

    def test_offset_page_first(self):
        items = list(range(20))
        page, nc = cursor_mod.offset_page(items, offset=0, limit=5)
        self.assertEqual(page, [0, 1, 2, 3, 4])
        self.assertIsNotNone(nc)

    def test_offset_page_continuation(self):
        items = list(range(20))
        _, nc = cursor_mod.offset_page(items, offset=0, limit=5)
        page2, _ = cursor_mod.offset_page(items, offset=cursor_mod.resolve_offset(nc, 0), limit=5)
        self.assertEqual(page2, [5, 6, 7, 8, 9])

    def test_offset_page_last_returns_none_cursor(self):
        items = list(range(20))
        page, nc = cursor_mod.offset_page(items, offset=18, limit=5)
        self.assertEqual(page, [18, 19])
        self.assertIsNone(nc)

    def test_resolve_offset_prefers_cursor(self):
        tok = cursor_mod.encode_cursor({"offset": 7})
        # cursor 주어지면 fallback offset 무시.
        self.assertEqual(cursor_mod.resolve_offset(tok, 99), 7)

    def test_resolve_offset_fallback(self):
        self.assertEqual(cursor_mod.resolve_offset(None, 3), 3)
        self.assertEqual(cursor_mod.resolve_offset("", 3), 3)


class TestResolveMeAlias(unittest.TestCase):
    def test_me_resolves_to_caller_email(self):
        req = _Req("dahuin000@gmail.com")
        self.assertEqual(owner_mod.resolve_me_alias("me", req), "dahuin000@gmail.com")

    def test_me_without_email_returns_none(self):
        # 인증 안 된 호출의 "me" 는 해석 불가 → None. create 의 `if not owner`
        # 가드(owner_required)가 truthy 리터럴 "me" 를 통과시켜 저장하던 버그 방지.
        req = _Req()
        self.assertIsNone(owner_mod.resolve_me_alias("me", req))

    def test_explicit_email_passthrough(self):
        req = _Req("dahuin000@gmail.com")
        self.assertEqual(owner_mod.resolve_me_alias("alice@example.com", req), "alice@example.com")

    def test_none_passthrough(self):
        req = _Req("dahuin000@gmail.com")
        self.assertIsNone(owner_mod.resolve_me_alias(None, req))


if __name__ == "__main__":
    unittest.main()
