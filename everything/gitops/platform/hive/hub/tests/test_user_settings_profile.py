"""user_settings 프로필(닉네임/아바타) + 부분 저장 병합 단위 테스트.

실제 fastapi 환경 없이 capability_framework / app.auth 를 스텁하고 실제 모듈을
app.entities.user_settings 로 로드한다 (test_cursor_and_me_alias 의 _load 패턴).
가장 위험한 회귀: Profile 섹션 저장이 Git identity 를 덮어쓰지 않아야 한다.
"""

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

_PAYLOAD = {"sub": "alice@example.com", "name": "Alice OAuth"}

# --- 환경·순서 무관 스텁 ---
# 형제 standalone 테스트(test_cursor_and_me_alias)가 알파벳 순으로 먼저 로드되며
# sys.modules["fastapi"] 를 APIRouter 없는 가짜로 덮어쓴다. user_settings 로드가
# 깨지지 않도록, fastapi 에 APIRouter 가 없을 때만 identity 데코레이터 라우터를 보탠다
# (실제 fastapi 가 살아있으면 손대지 않음 → CI 의 정상 라우트 빌드 유지).
_fa = sys.modules.get("fastapi")
if _fa is None or not hasattr(_fa, "APIRouter"):
    if _fa is None:
        _fa = types.ModuleType("fastapi")
        sys.modules["fastapi"] = _fa
    if not hasattr(_fa, "Request"):
        class _FaRequest:  # noqa: D401
            pass
        _fa.Request = _FaRequest

    class _Router:
        def post(self, *a, **k):
            def deco(fn):
                return fn
            return deco

    _fa.APIRouter = _Router

# capability_framework 는 로컬엔 없고 CI엔 실제로 있다. 실제가 있으면 그대로 쓰고
# (속성 접근만 하므로 호환), 없을 때만 최소 스텁을 넣는다.
if "capability_framework" not in sys.modules:
    _cf = types.ModuleType("capability_framework")

    class CapabilityResponse:
        def __init__(self, status, data=None, error_code=None, message=None):
            self.status = status
            self.data = data
            self.error_code = error_code
            self.message = message

    _cf.CapabilityResponse = CapabilityResponse
    sys.modules["capability_framework"] = _cf

# 실제 app 패키지·타 테스트의 app 스텁과 충돌하지 않도록 고유 네임스페이스로 로드.
# user_settings 의 `from ..auth import request_auth_payload` 는 usmod.auth 로 해석된다.
_PKG = "usmod"
for _name in (_PKG, f"{_PKG}.entities"):
    if _name not in sys.modules:
        _m = types.ModuleType(_name)
        _m.__path__ = []
        sys.modules[_name] = _m
_auth_stub = types.ModuleType(f"{_PKG}.auth")
_auth_stub.request_auth_payload = lambda request: getattr(request, "_payload", _PAYLOAD)
sys.modules[f"{_PKG}.auth"] = _auth_stub


def _load():
    here = os.path.dirname(os.path.abspath(__file__))
    full = os.path.normpath(os.path.join(here, "..", "app/entities/user_settings.py"))
    spec = importlib.util.spec_from_file_location(f"{_PKG}.entities.user_settings", full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{_PKG}.entities.user_settings"] = mod
    spec.loader.exec_module(mod)
    return mod


us = _load()


def _f(resp, key):
    """응답 필드 접근 — 형제 테스트가 심는 capability_framework 스텁에 따라 응답이
    객체(.attr)일 수도 dict(lambda **kw: kw)일 수도 있어 양쪽을 흡수한다."""
    if isinstance(resp, dict):
        return resp.get(key)
    return getattr(resp, key, None)


class _Req:
    def __init__(self, payload=None):
        self._payload = payload or _PAYLOAD


def run(coro):
    # 핸들러가 sync(def)로 오프로드되면 코루틴이 아니라 결과를 직접 반환한다
    # (INFRA-ISSUE-276). 양쪽 시그니처를 모두 받는다.
    if asyncio.iscoroutine(coro):
        return asyncio.run(coro)
    return coro


class ProfileSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        Path(self.tmp.name).unlink()  # 시작은 파일 없음 상태
        us.USER_SETTINGS_PATH = Path(self.tmp.name)

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def _update(self, **kw):
        body = us.UserSettingsUpdateRequest(**kw)
        return run(us.user_settings_update(body, _Req()))

    def _get(self):
        return run(us.user_settings_get(us.UserSettingsGetRequest(), _Req()))

    def test_partial_save_does_not_clobber_git(self):
        # Git 먼저 저장
        self._update(git_name="alice", git_email="alice@git.com")
        # Profile 섹션만 저장 (git 필드는 None=미전송)
        r = self._update(display_name="앨리스", avatar="data:image/webp;base64,AAAA")
        self.assertEqual(_f(r, "status"), "ok")
        d = _f(r, "data")
        self.assertEqual(d["git_name"], "alice")
        self.assertEqual(d["git_email"], "alice@git.com")
        self.assertEqual(d["display_name"], "앨리스")
        self.assertEqual(d["avatar"], "data:image/webp;base64,AAAA")

    def test_empty_string_clears_only_that_field(self):
        self._update(git_name="alice", display_name="앨리스")
        r = self._update(display_name="")  # 닉네임만 해제
        d = _f(r, "data")
        self.assertIsNone(d["display_name"])
        self.assertEqual(d["git_name"], "alice")

    def test_effective_display_name_falls_back_to_oauth(self):
        r = self._get()  # 아무 override 없음
        d = _f(r, "data")
        self.assertIsNone(d["display_name"])
        self.assertEqual(d["default_display_name"], "Alice OAuth")
        self.assertEqual(d["effective_display_name"], "Alice OAuth")

    def test_avatar_must_be_image_data_uri(self):
        r = self._update(avatar="https://evil.example.com/x.png")
        self.assertEqual(_f(r, "status"), "error")
        self.assertEqual(_f(r, "error_code"), "invalid_input")

    def test_avatar_size_cap(self):
        big = "data:image/png;base64," + ("A" * (us.AVATAR_MAX_CHARS + 1))
        r = self._update(avatar=big)
        self.assertEqual(_f(r, "status"), "error")
        self.assertEqual(_f(r, "error_code"), "invalid_input")

    def test_display_name_length_cap(self):
        r = self._update(display_name="x" * (us.DISPLAY_NAME_MAX + 1))
        self.assertEqual(_f(r, "status"), "error")
        self.assertEqual(_f(r, "error_code"), "invalid_input")

    def test_clearing_all_fields_removes_entry(self):
        self._update(display_name="앨리스")
        self._update(display_name="")
        self.assertFalse(us._load_settings())  # 빈 엔트리는 제거

    def test_profile_override_helper(self):
        self._update(display_name="앨리스", avatar="data:image/webp;base64,BBBB")
        ov = us.profile_override("ALICE@example.com")  # 대소문자 무관 키
        self.assertEqual(ov["display_name"], "앨리스")
        self.assertEqual(ov["avatar"], "data:image/webp;base64,BBBB")

    def test_directory_lists_only_users_with_overrides(self):
        # git 만 설정한 사용자는 디렉토리에 안 나온다.
        self._update(git_name="alice")
        r = run(us.user_directory_list(us.UserDirectoryListRequest(), _Req()))
        self.assertEqual(_f(r, "data")["users"], [])
        self._update(display_name="앨리스")
        r = run(us.user_directory_list(us.UserDirectoryListRequest(), _Req()))
        emails = [u["email"] for u in _f(r, "data")["users"]]
        self.assertIn("alice@example.com", emails)


if __name__ == "__main__":
    unittest.main()
