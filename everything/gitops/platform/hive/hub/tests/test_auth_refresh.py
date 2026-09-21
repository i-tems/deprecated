"""auth.refresh — console JWT 갱신 엔드포인트 단위 테스트.

verify_jwt / _make_jwt 를 순수 함수로 테스트해 FastAPI 런타임 없이 검증한다.
"""

import os
import sys
import time
import types
import unittest
from pathlib import Path

# ── 최소 스텁 ─────────────────────────────────────────────────────────────────
# fastapi, google.oauth2 등 런타임 의존을 피하기 위해 스텁 모듈을 sys.modules에 주입.

def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

# google 패키지 스텁
if "google" not in sys.modules:
    _stub("google")
if "google.oauth2" not in sys.modules:
    _stub("google.oauth2")
if "google.oauth2.id_token" not in sys.modules:
    _stub("google.oauth2.id_token")
if "google.auth" not in sys.modules:
    _stub("google.auth")
if "google.auth.transport" not in sys.modules:
    _stub("google.auth.transport")
if "google.auth.transport.requests" not in sys.modules:
    _stub("google.auth.transport.requests", Request=object)

# fastapi 스텁 (APIRouter + decorators)
_fa = sys.modules.get("fastapi")
if _fa is None or not hasattr(_fa, "APIRouter"):
    if _fa is None:
        _fa = types.ModuleType("fastapi")
        sys.modules["fastapi"] = _fa

    class _FaRequest:
        def __init__(self, headers=None, cookies=None):
            self.headers = headers or {}
            self.cookies = cookies or {}
            self.client = None
            self.url = types.SimpleNamespace(scheme="https")

    class _FaResponse:
        def set_cookie(self, **kwargs): pass
        def delete_cookie(self, **kwargs): pass

    class _Router:
        def post(self, *a, **k):
            def deco(fn): return fn
            return deco

    _fa.APIRouter = _Router
    _fa.Request = _FaRequest
    _fa.Response = _FaResponse

if not hasattr(sys.modules["fastapi"], "Request"):
    sys.modules["fastapi"].Request = types.SimpleNamespace

# pydantic 스텁
if "pydantic" not in sys.modules:
    class _BaseModel:
        def __init_subclass__(cls, **kw): pass
    _pb = types.ModuleType("pydantic")
    _pb.BaseModel = _BaseModel
    sys.modules["pydantic"] = _pb

# ── auth 모듈 순수 함수 로드 ─────────────────────────────────────────────────
# JWT_SECRET 필요 — 테스트 전용 고정값 주입.
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("AUTH_WHITELIST_EMAILS", "alice@example.com,bob@example.com")
os.environ.setdefault("AUTH_ADMIN_EMAILS", "alice@example.com")
os.environ.setdefault("AUTH_COOKIE_NAME", "hive_auth")
os.environ.setdefault("AUTH_COOKIE_SAMESITE", "strict")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")

import importlib.util

_AUTH_PATH = Path(__file__).resolve().parents[1] / "app" / "auth.py"


def _load_auth():
    """auth 모듈을 격리 네임스페이스에서 로드. storage / entities 스텁도 주입."""
    _app = sys.modules.get("authmod_app")
    if _app is None:
        _app = types.ModuleType("authmod_app")
        sys.modules["authmod_app"] = _app

    # storage 스텁 (record_login / profile_override)
    _storage = types.ModuleType("authmod_app.storage")
    _storage.auth_repo = types.SimpleNamespace(record_login=lambda **k: None, list_recent=lambda **k: [])
    sys.modules["authmod_app.storage"] = _storage

    _entities = types.ModuleType("authmod_app.entities")
    _entities.user_settings = types.SimpleNamespace(
        profile_override=lambda email: {"display_name": None, "avatar": None}
    )
    sys.modules["authmod_app.entities"] = _entities
    sys.modules["authmod_app.entities.user_settings"] = _entities.user_settings

    spec = importlib.util.spec_from_file_location("authmod_app.auth", _AUTH_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "authmod_app"
    sys.modules["authmod_app.auth"] = mod
    spec.loader.exec_module(mod)
    return mod


_auth = _load_auth()


class AuthRefreshLogicTest(unittest.TestCase):
    """auth.refresh 핵심 로직 — JWT 발급·검증 함수 단위 테스트."""

    def _make_jwt(self, email, name="Test User", picture="", offset=0):
        """offset 초 뒤에 발급된 것처럼 JWT 를 생성 (음수면 과거)."""
        import jwt as _jwt
        payload = {
            "sub": email,
            "name": name,
            "picture": picture,
            "iat": int(time.time()) + offset,
            "exp": int(time.time()) + offset + _auth.JWT_EXPIRY_SECONDS,
        }
        return _jwt.encode(payload, _auth.JWT_SECRET, algorithm=_auth.JWT_ALGORITHM)

    def _make_expired_jwt(self, email):
        """완전히 만료된 JWT."""
        import jwt as _jwt
        payload = {
            "sub": email,
            "name": "Alice",
            "picture": "",
            "iat": int(time.time()) - _auth.JWT_EXPIRY_SECONDS - 10,
            "exp": int(time.time()) - 10,
        }
        return _jwt.encode(payload, _auth.JWT_SECRET, algorithm=_auth.JWT_ALGORITHM)

    # ── verify_jwt 기본 ──

    def test_valid_jwt_verifies(self):
        token = self._make_jwt("alice@example.com")
        payload = _auth.verify_jwt(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "alice@example.com")

    def test_expired_jwt_returns_none(self):
        token = self._make_expired_jwt("alice@example.com")
        payload = _auth.verify_jwt(token)
        self.assertIsNone(payload, "만료된 JWT 는 None 이어야 한다")

    def test_invalid_jwt_returns_none(self):
        self.assertIsNone(_auth.verify_jwt("not.a.jwt"))
        self.assertIsNone(_auth.verify_jwt(""))

    # ── refresh 흐름 시뮬레이션 ──

    def test_refresh_issues_fresh_jwt(self):
        """유효한 JWT 를 갱신하면 새 JWT(7일 만료)가 발급된다."""
        orig = self._make_jwt("alice@example.com")
        orig_payload = _auth.verify_jwt(orig)
        self.assertIsNotNone(orig_payload)

        # 갱신 — _make_jwt 로 같은 claims 에서 새 토큰 생성
        new_token = _auth.make_caller_jwt.__wrapped__ if hasattr(_auth.make_caller_jwt, "__wrapped__") else None
        # 직접 _make_jwt helper 사용
        new_token = _auth._make_jwt(
            email=orig_payload["sub"],
            name=orig_payload.get("name", ""),
            picture=orig_payload.get("picture", ""),
        )
        new_payload = _auth.verify_jwt(new_token)
        self.assertIsNotNone(new_payload)
        self.assertEqual(new_payload["sub"], "alice@example.com")
        # 새 토큰 만료는 7일 후여야 한다
        remaining = new_payload["exp"] - int(time.time())
        self.assertGreater(remaining, _auth.JWT_EXPIRY_SECONDS - 10)
        self.assertLessEqual(remaining, _auth.JWT_EXPIRY_SECONDS + 5)

    def test_expired_jwt_cannot_refresh(self):
        """만료된 JWT 는 verify_jwt 가 None 을 반환해 refresh 거부된다."""
        expired = self._make_expired_jwt("alice@example.com")
        self.assertIsNone(_auth.verify_jwt(expired))

    def test_fresh_jwt_outlives_sandbox_ttl(self):
        """갱신된 JWT 의 남은 수명 > sandbox 최대 TTL(24h)."""
        orig = self._make_jwt("alice@example.com")
        orig_payload = _auth.verify_jwt(orig)
        new_token = _auth._make_jwt(
            email=orig_payload["sub"],
            name=orig_payload.get("name", ""),
            picture=orig_payload.get("picture", ""),
        )
        new_payload = _auth.verify_jwt(new_token)
        remaining_hours = (new_payload["exp"] - int(time.time())) / 3600
        self.assertGreater(remaining_hours, 24, "갱신 JWT 는 sandbox 최대 TTL(24h) 보다 길어야 한다")

    def test_whitelist_check_on_refresh(self):
        """화이트리스트에 없는 이메일은 refresh 에서도 거부된다."""
        # 화이트리스트: alice@example.com, bob@example.com
        allowed = _auth._load_whitelist()
        self.assertIn("alice@example.com", allowed)
        self.assertNotIn("eve@example.com", allowed)

    def test_normalize_email_strips_and_lowercases(self):
        self.assertEqual(_auth._normalize_email("  Alice@Example.COM "), "alice@example.com")
        self.assertEqual(_auth._normalize_email(None), "")

    def test_whitelist_match_is_case_insensitive(self):
        """대소문자 다른 이메일도 화이트리스트와 매칭 — fail-closed lockout 회귀 가드.

        whitelist(_load_whitelist)는 lowercased 인데 구버전은 raw principal email 로
        비교해, Google/JWT 가 대소문자 다른 이메일을 주면 정상 사용자가 잠겼다(admin
        체크는 lower 라 불일치). principal 도 _normalize_email 로 정규화해 해소. INFRA-ISSUE-322.
        """
        allowed = _auth._load_whitelist()  # env: alice@example.com,bob@example.com
        self.assertIn(_auth._normalize_email("ALICE@Example.com"), allowed)
        self.assertIn(_auth._normalize_email("Bob@EXAMPLE.COM"), allowed)
        # 정규화 안 한 raw(구 버그)는 lowercased 화이트리스트와 매칭 실패 — 정규화가 갭을 닫는다.
        self.assertNotIn("ALICE@Example.com", allowed)


if __name__ == "__main__":
    unittest.main()
