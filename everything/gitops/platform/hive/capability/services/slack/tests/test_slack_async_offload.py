"""slack capability 핸들러가 블로킹 Slack SDK HTTP 호출을 이벤트 루프에서 직렬 실행하지
않고 asyncio.to_thread 로 워커 스레드에 오프로드하는지 고정 (INFRA-ISSUE-322 ①).

검증 방식: WebClient 의 chat_postMessage / users_lookupByEmail 을 thread-id 기록 fake 로
치환하고, 핸들러를 이벤트 루프에서 await 했을 때 그 호출이 메인(루프) 스레드가 아닌 다른
스레드에서 돌았는지 본다. slack_sdk 는 로컬 미설치라 스텁; capability_framework·fastapi 는
실제 모듈.
"""

import asyncio
import importlib.util
import os
import sys
import threading
import types
import unittest

_HERE = os.path.dirname(__file__)
_SERVICE_DIR = os.path.dirname(_HERE)
_CAP_ROOT = os.path.dirname(os.path.dirname(_SERVICE_DIR))   # .../capability
sys.path.insert(0, os.path.join(_CAP_ROOT, "framework"))     # capability_framework


def _stub_slack_sdk():
    sdk = sys.modules.get("slack_sdk") or types.ModuleType("slack_sdk")
    sdk.WebClient = type("WebClient", (), {})
    sys.modules["slack_sdk"] = sdk
    errs = sys.modules.get("slack_sdk.errors") or types.ModuleType("slack_sdk.errors")
    errs.SlackApiError = type("SlackApiError", (Exception,), {})
    sys.modules["slack_sdk.errors"] = errs
    sdk.errors = errs


def _load_main():
    _stub_slack_sdk()
    path = os.path.join(_SERVICE_DIR, "main.py")
    spec = importlib.util.spec_from_file_location("slack_cap_main", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Req:
    def __init__(self, cell_id="infra"):
        self.headers = {"X-Cell-Id": cell_id}


class _FakeClient:
    def __init__(self, rec, response):
        self._rec = rec
        self._response = response

    def chat_postMessage(self, **kw):
        self._rec["tid"] = threading.get_ident()
        return self._response

    def users_lookupByEmail(self, **kw):
        self._rec["tid"] = threading.get_ident()
        return self._response


class SlackOffloadTest(unittest.TestCase):
    def setUp(self):
        self.mod = _load_main()
        self.main_tid = threading.get_ident()
        self.rec = {}

    def _patch_client(self, response):
        fake = _FakeClient(self.rec, response)
        self.mod._get_client = lambda cell_id: fake

    def test_slack_send_offloads(self):
        self._patch_client({"channel": "C1", "ts": "123.45"})
        req = self.mod.SlackSendRequest(channel="#x", text="hi")
        resp = asyncio.run(self.mod.slack_send(req, _Req()))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["ts"], "123.45")
        self.assertNotEqual(self.rec.get("tid"), self.main_tid,
                            "chat_postMessage 가 이벤트 루프 스레드에서 실행됨 (미오프로드)")

    def test_lookup_user_offloads(self):
        self._patch_client({"user": {"id": "U1", "name": "n", "profile": {"display_name": "d"}}})
        req = self.mod.SlackLookupUserByEmailRequest(email="a@b.com")
        resp = asyncio.run(self.mod.slack_lookup_user_by_email(req, _Req()))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["user_id"], "U1")
        self.assertNotEqual(self.rec.get("tid"), self.main_tid,
                            "users_lookupByEmail 가 이벤트 루프 스레드에서 실행됨 (미오프로드)")


if __name__ == "__main__":
    unittest.main()
