"""sandbox.create / sandbox.ws 의 cell 인가 게이트(_authorize_cell_access).

회귀: 컨테이너 서비스는 hub 인가 경계 밖(nginx /container/ 직결)이라 cell 권한을
스스로 검사하지 않았다. 그 결과 권한 없는 사용자도 임의 cell 의 sandbox 세션을
띄울 수 있었다 (하류 MCP 게이트만 데이터 접근을 막음 — 방어 한 겹). 이제
hub /cell.get 을 X-Source=console 강제로 호출해 admin/allowed_emails 판정을
권위로 삼고, fail-closed 로 게이트한다.

container 테스트 규약(test_named_sandbox)대로 stub 으로 main.py 를 로드하고,
httpx 를 모킹해 _authorize_cell_access 의 분기를 직접 검증한다.
"""

import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_named_sandbox import _load_container_main  # noqa: E402


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeAsyncClient:
    captured: dict = {}

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.captured = {"url": url, "json": json, "headers": headers}
        if self._exc:
            raise self._exc
        return self._response


def _httpx_stub(response=None, exc=None):
    m = types.SimpleNamespace()
    m.AsyncClient = lambda *a, **k: _FakeAsyncClient(response=response, exc=exc)
    return m


class CellAuthzTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_container_main()

    def _run(self, cell, *, hub_url, jwt, response=None, exc=None):
        self.mod.HUB_URL = hub_url
        self.mod.httpx = _httpx_stub(response=response, exc=exc)
        return asyncio.run(self.mod._authorize_cell_access(cell, jwt))

    def test_forbidden_is_denied(self):
        # hub 가 권한 없음(forbidden)을 주면 거부 — 핵심 회귀.
        self.assertFalse(self._run(
            "pen", hub_url="http://hub", jwt="t",
            response=_Resp(200, {"status": "error", "error_code": "forbidden"}),
        ))

    def test_ok_is_allowed(self):
        self.assertTrue(self._run(
            "items", hub_url="http://hub", jwt="t",
            response=_Resp(200, {"status": "ok", "data": {}}),
        ))

    def test_forces_console_source_and_bearer(self):
        # 기존 _fetch_cell_repo_url 가 게이트를 안 탄 이유가 X-Source 미강제였음 —
        # 인가 호출은 반드시 console source + 사용자 Bearer 로 /cell.get 을 친다.
        self._run("pen", hub_url="http://hub", jwt="tok123",
                  response=_Resp(200, {"status": "ok"}))
        cap = _FakeAsyncClient.captured
        self.assertEqual(cap["headers"].get("X-Source"), "console")
        self.assertEqual(cap["headers"].get("Authorization"), "Bearer tok123")
        self.assertTrue(cap["url"].endswith("/cell.get"))
        self.assertEqual(cap["json"], {"cell_id": "pen"})

    def test_no_token_is_denied(self):
        self.assertFalse(self._run(
            "pen", hub_url="http://hub", jwt=None,
            response=_Resp(200, {"status": "ok"}),
        ))

    def test_hub_unreachable_is_denied_fail_closed(self):
        self.assertFalse(self._run(
            "pen", hub_url="http://hub", jwt="t", exc=RuntimeError("boom"),
        ))

    def test_non_200_is_denied(self):
        self.assertFalse(self._run(
            "pen", hub_url="http://hub", jwt="t",
            response=_Resp(403, {"status": "error"}),
        ))

    def test_no_hub_url_allows_dev(self):
        # HUB_URL 미설정(로컬/dev): 물어볼 hub 가 없으니 게이트 불가 → 허용.
        self.assertTrue(self._run(
            "pen", hub_url="", jwt="t",
            response=_Resp(200, {"status": "ok"}),
        ))


class _FakeReq:
    """헤더만 가진 최소 request/websocket 스텁 — _request_console_jwt 가
    request.headers.get('authorization'|'cookie') 만 본다."""

    def __init__(self, headers):
        self.headers = headers


class FetchHelperAuthTest(unittest.TestCase):
    """_fetch_cell_repo_url / _fetch_user_git_identity 가 console JWT 를 명시적
    Bearer + X-Source: console 로 싣는지 — 회귀: 브라우저 WebSocket attach 는
    핸드셰이크에 X-Source/Authorization 을 못 실어 Cookie 만 도착하는데, 옛
    헤더-forward 방식은 그 경우 X-Source 누락으로 hub 가 401 → repo_url=None →
    bootstrap(clone·.mcp.json·settings) 전체 스킵으로 sandbox 가 빈 껍데기였다.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_container_main()

    def _setup(self, *, response=None, exc=None):
        self.mod.HUB_URL = "http://hub"
        self.mod.httpx = _httpx_stub(response=response, exc=exc)

    def test_repo_url_cookie_only_forces_console_bearer(self):
        # WS 시나리오: auth_token 쿠키만 있음(Authorization/X-Source 헤더 없음).
        self._setup(response=_Resp(200, {"status": "ok", "data": {"repo_url": "https://git/x"}}))
        req = _FakeReq({"cookie": "auth_token=tok123"})
        out = asyncio.run(self.mod._fetch_cell_repo_url("items", req))
        cap = _FakeAsyncClient.captured
        self.assertEqual(out, "https://git/x")
        self.assertEqual(cap["headers"].get("X-Source"), "console")
        self.assertEqual(cap["headers"].get("Authorization"), "Bearer tok123")
        self.assertTrue(cap["url"].endswith("/cell.get"))

    def test_repo_url_no_token_returns_none(self):
        # 토큰 없으면 hub 호출 없이 None (인증 불가 → 레거시 fallback).
        self._setup(response=_Resp(200, {"status": "ok", "data": {"repo_url": "https://git/x"}}))
        out = asyncio.run(self.mod._fetch_cell_repo_url("items", _FakeReq({})))
        self.assertIsNone(out)

    def test_git_identity_cookie_only_forces_console_bearer(self):
        self._setup(response=_Resp(200, {"status": "ok", "data": {
            "effective_git_name": "n", "effective_git_email": "n@x"}}))
        req = _FakeReq({"cookie": "auth_token=tok123"})
        name, email = asyncio.run(self.mod._fetch_user_git_identity(req))
        cap = _FakeAsyncClient.captured
        self.assertEqual((name, email), ("n", "n@x"))
        self.assertEqual(cap["headers"].get("X-Source"), "console")
        self.assertEqual(cap["headers"].get("Authorization"), "Bearer tok123")
        self.assertTrue(cap["url"].endswith("/user.settings.get"))


if __name__ == "__main__":
    unittest.main()
