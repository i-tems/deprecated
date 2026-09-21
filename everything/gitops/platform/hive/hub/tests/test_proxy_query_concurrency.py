"""proxy query.sql 동시성 가드 — query prefix 만 HUB_QUERY_CONCURRENCY 로 제한.

proxy.py 만 격리 로드한다 (config 의 fastapi/DB 의존 회피, sibling 은 stub).
"""
import asyncio
import importlib.util
import os
import sys
import types

from starlette.requests import Request

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.abspath(os.path.join(_HERE, "..", "app"))


def _load_proxy():
    # config 의 fastapi/DB 의존을 피해 sibling 을 stub 한 뒤 proxy.py 만 로드한다.
    # exec 후 sys.modules 를 원복 — proxy 의 import 는 이미 해소돼 다른 테스트를 오염시키지 않는다.
    names = ["app", "app.auth", "app.config", "app.registry", "app.proxy"]
    saved = {n: sys.modules.get(n) for n in names}
    try:
        pkg = types.ModuleType("app"); pkg.__path__ = [_APP]
        sys.modules["app"] = pkg
        auth = types.ModuleType("app.auth"); auth._request_token = lambda r: None
        sys.modules["app.auth"] = auth
        config = types.ModuleType("app.config"); config.ensure_cell_access = lambda r: None
        sys.modules["app.config"] = config
        registry = types.ModuleType("app.registry"); registry.REGISTRY = {}
        sys.modules["app.registry"] = registry
        spec = importlib.util.spec_from_file_location("app.proxy", os.path.join(_APP, "proxy.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["app.proxy"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m


proxy = _load_proxy()


class _Svc:
    def __init__(self, prefixes):
        self.prefixes = set(prefixes)
        self.base_url = "http://svc"
        self.timeout = 30


class _Resp:
    content = b"{}"
    status_code = 200


def _fake_httpx(tracker):
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, content=None, headers=None):
            tracker["cur"] += 1
            tracker["max"] = max(tracker["max"], tracker["cur"])
            await asyncio.sleep(0.05)
            tracker["cur"] -= 1
            return _Resp()
    return types.SimpleNamespace(AsyncClient=_Client)


def _make_request(path):
    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST",
        "path": "/" + path, "raw_path": ("/" + path).encode(),
        "headers": [], "query_string": b"", "scheme": "http",
        "server": ("h", 8000), "client": ("1.2.3.4", 1), "state": {},
    }
    return Request(scope, receive)


def _run_burst(prefix, n, limit):
    tracker = {"cur": 0, "max": 0}
    proxy.REGISTRY.clear()
    proxy.REGISTRY[prefix] = _Svc([prefix])
    proxy.httpx = _fake_httpx(tracker)
    proxy._QUERY_CONCURRENCY = limit
    proxy._query_sem = None

    async def go():
        await asyncio.gather(*[proxy._proxy_handler(_make_request(f"{prefix}.run")) for _ in range(n)])
    asyncio.run(go())
    return tracker["max"]


def test_query_prefix_bounded():
    assert _run_burst("query", 8, 3) <= 3      # query 는 동시 3 이하


def test_non_query_prefix_unbounded():
    assert _run_burst("other", 8, 3) == 8       # query 외엔 가드 미적용


def test_guard_disabled_when_zero():
    proxy._QUERY_CONCURRENCY = 0
    proxy._query_sem = None
    assert proxy._query_guard() is None
    proxy._QUERY_CONCURRENCY = 3
    proxy._query_sem = None
    g1 = proxy._query_guard()
    assert g1 is proxy._query_guard()           # 싱글톤
