"""google capability 핸들러가 블로킹 Google SDK 호출을 이벤트 루프에서 직렬 실행하지
않고 asyncio.to_thread 로 워커 스레드에 오프로드하는지 고정 (INFRA-ISSUE-322 ①).

검증 방식: _get_calendar_service 와 service.events()....execute() 를 thread-id 를
기록하는 fake 로 치환하고, 핸들러를 이벤트 루프에서 await 했을 때 그 호출들이 메인
(루프) 스레드가 아닌 다른 스레드에서 돌았는지 본다. 같은 스레드면(=오프로드 안 됨)
실패한다. googleapiclient·google.* 는 로컬 미설치라 스텁; capability_framework·
fastapi 는 실제 모듈을 쓴다.
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


def _stub_google_sdks():
    """googleapiclient·google.auth·google.oauth2 를 import 가능하게 최소 스텁."""
    def _mod(name):
        m = sys.modules.get(name)
        if m is None:
            m = types.ModuleType(name)
            sys.modules[name] = m
        return m

    disc = _mod("googleapiclient.discovery")
    disc.build = lambda *a, **k: None
    _mod("googleapiclient").discovery = disc

    greq = _mod("google.auth.transport.requests")
    greq.Request = lambda *a, **k: None
    _mod("google.auth.transport").requests = greq
    _mod("google.auth").transport = sys.modules["google.auth.transport"]

    gcred = _mod("google.oauth2.credentials")
    gcred.Credentials = type("Credentials", (), {})
    _mod("google.oauth2").credentials = gcred

    gsa = _mod("google.oauth2.service_account")
    gsa.Credentials = type(
        "Credentials", (), {"from_service_account_file": staticmethod(lambda *a, **k: None)}
    )
    _mod("google.oauth2").service_account = gsa

    gs = _mod("gspread")
    gs.authorize = lambda *a, **k: None

    g = _mod("google")
    g.auth = sys.modules["google.auth"]
    g.oauth2 = sys.modules["google.oauth2"]


def _load_main():
    _stub_google_sdks()
    path = os.path.join(_SERVICE_DIR, "main.py")
    spec = importlib.util.spec_from_file_location("google_cap_main", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Req:
    def __init__(self, cell_id="infra"):
        self.headers = {"X-Cell-Id": cell_id}


class _FakeExec:
    """service.events().<op>(...).execute() 체인 흉내 — execute 의 thread 기록."""

    def __init__(self, rec, result):
        self._rec = rec
        self._result = result

    def events(self):
        return self

    def list(self, **kw):
        return self

    def insert(self, **kw):
        return self

    def delete(self, **kw):
        return self

    def patch(self, **kw):
        return self

    def execute(self):
        self._rec["execute_tid"] = threading.get_ident()
        return self._result


class GoogleOffloadTest(unittest.TestCase):
    def setUp(self):
        self.mod = _load_main()
        self.main_tid = threading.get_ident()
        self.rec = {}

    def _patch_service(self, result):
        fake = _FakeExec(self.rec, result)

        def _fake_get_service(cell_id):
            self.rec["service_tid"] = threading.get_ident()
            return fake

        self.mod._get_calendar_service = _fake_get_service

    def _assert_offloaded(self):
        # 블로킹 호출(service build·execute)이 메인(루프) 스레드 밖에서 돌았어야 한다.
        self.assertNotEqual(self.rec.get("service_tid"), self.main_tid,
                            "_get_calendar_service 가 이벤트 루프 스레드에서 실행됨 (미오프로드)")
        self.assertNotEqual(self.rec.get("execute_tid"), self.main_tid,
                            "events().execute() 가 이벤트 루프 스레드에서 실행됨 (미오프로드)")

    def test_calendar_fetch_offloads(self):
        self._patch_service({"items": []})
        req = self.mod.CalendarFetchRequest(date="2026-06-16", range=1)
        resp = asyncio.run(self.mod.calendar_fetch(req, _Req()))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["count"], 0)
        self._assert_offloaded()

    def test_calendar_create_offloads(self):
        self._patch_service({
            "id": "evt1", "summary": "t",
            "start": {"dateTime": "2026-06-16T14:00:00+09:00"},
            "end": {"dateTime": "2026-06-16T15:00:00+09:00"},
            "htmlLink": "http://x",
        })
        req = self.mod.CalendarCreateRequest(title="t", start="2026-06-16T14:00", end="2026-06-16T15:00")
        resp = asyncio.run(self.mod.calendar_create(req, _Req()))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["id"], "evt1")
        self._assert_offloaded()

    def test_calendar_delete_offloads(self):
        self._patch_service({})
        req = self.mod.CalendarDeleteRequest(event_id="evt1")
        resp = asyncio.run(self.mod.calendar_delete(req, _Req()))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["deleted"], "evt1")
        self._assert_offloaded()


class _FakeWorksheet:
    """gspread Worksheet 흉내 — blocking 시트 op 의 thread 기록."""

    def __init__(self, rec, values):
        self._rec = rec
        self._values = values
        self.title = "Sheet1"

    def get_all_values(self):
        self._rec["op_tid"] = threading.get_ident()
        return self._values

    def get(self, range_name):
        self._rec["op_tid"] = threading.get_ident()
        return self._values

    def update(self, range_name=None, values=None, value_input_option=None):
        self._rec["op_tid"] = threading.get_ident()
        self._rec["update_args"] = (range_name, values, value_input_option)
        return {"updatedCells": 4, "updatedRange": "Sheet1!A1:B2"}


class _FakeSpreadsheet:
    def __init__(self, ws):
        self.sheet1 = ws

    def get_worksheet(self, idx):
        return self.sheet1

    def worksheet(self, name):
        return self.sheet1


class _FakeSheetsClient:
    def __init__(self, rec, ws):
        self._rec = rec
        self._ss = _FakeSpreadsheet(ws)

    def open_by_key(self, sheet_id):
        self._rec["open_tid"] = threading.get_ident()
        return self._ss


class SheetsOffloadTest(unittest.TestCase):
    def setUp(self):
        self.mod = _load_main()
        self.main_tid = threading.get_ident()
        self.rec = {}

    def _patch_client(self, values):
        ws = _FakeWorksheet(self.rec, values)
        client = _FakeSheetsClient(self.rec, ws)

        def _fake_get_client(cell_id):
            self.rec["client_tid"] = threading.get_ident()
            return client

        self.mod._get_sheets_client = _fake_get_client

    def _assert_offloaded(self):
        self.assertNotEqual(self.rec.get("client_tid"), self.main_tid,
                            "_get_sheets_client 가 이벤트 루프 스레드에서 실행됨 (미오프로드)")
        self.assertNotEqual(self.rec.get("op_tid"), self.main_tid,
                            "시트 op 가 이벤트 루프 스레드에서 실행됨 (미오프로드)")

    def test_sheets_read_offloads(self):
        self._patch_client([["name", "score"], ["a", "1"]])
        req = self.mod.SheetsReadRequest(sheet_id="sid")
        resp = asyncio.run(self.mod.sheets_read(req, _Req()))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["rows"], 2)
        self.assertEqual(resp.data["values"][0], ["name", "score"])
        self._assert_offloaded()

    def test_sheets_write_roundtrip_and_offloads(self):
        self._patch_client([])
        req = self.mod.SheetsWriteRequest(
            sheet_id="sid", range="A1", values=[["name", "score"], ["a", 1]]
        )
        resp = asyncio.run(self.mod.sheets_write(req, _Req()))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["updated_cells"], 4)
        # keyword 호출이 그대로 전달됐는지 — gspread 버전 무관 호출 계약 고정.
        self.assertEqual(self.rec["update_args"], ("A1", [["name", "score"], ["a", 1]], "USER_ENTERED"))
        self._assert_offloaded()

    def test_sheets_missing_key_is_isolated_error(self):
        # 키 부재 = 격리. 실제 _get_sheets_client 로 없는 cell 키 경로를 친다.
        req = self.mod.SheetsReadRequest(sheet_id="sid")
        resp = asyncio.run(self.mod.sheets_read(req, _Req(cell_id="no-such-cell")))
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.error_code, "sheets_error")
        self.assertIn("Service-account key not found", resp.message)


if __name__ == "__main__":
    unittest.main()
