"""hub_client 회귀 테스트 — 결과 TTL 캐시 + httpx 예외의 HubError 변환."""
import asyncio
import pathlib
import sys

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app.hub_client import HubClient, HubError  # noqa: E402


def test_cache_hit_avoids_second_call(monkeypatch):
    c = HubClient()
    calls = {"n": 0}

    async def fake_once(sql, limit):
        calls["n"] += 1
        return {"columns": ["x"], "rows": [[calls["n"]]]}

    monkeypatch.setattr(c, "_run_once", fake_once)
    r1 = asyncio.run(c.run_sql("SELECT 1"))
    r2 = asyncio.run(c.run_sql("SELECT 1"))
    assert calls["n"] == 1          # 두 번째는 캐시
    assert r1 == r2
    asyncio.run(c.run_sql("SELECT 2"))
    assert calls["n"] == 2          # 다른 SQL 은 새 호출


def test_cache_key_distinguishes_limit(monkeypatch):
    c = HubClient()
    calls = {"n": 0}

    async def fake_once(sql, limit):
        calls["n"] += 1
        return {"limit": limit}

    monkeypatch.setattr(c, "_run_once", fake_once)
    asyncio.run(c.run_sql("SELECT 1", limit=10))
    asyncio.run(c.run_sql("SELECT 1", limit=20))
    assert calls["n"] == 2          # limit 다르면 별개 키


def test_cache_expires(monkeypatch):
    c = HubClient()
    c.cache_ttl = 100
    clock = {"now": 1000.0}
    monkeypatch.setattr("app.hub_client.time.time", lambda: clock["now"])
    calls = {"n": 0}

    async def fake_once(sql, limit):
        calls["n"] += 1
        return {"n": calls["n"]}

    monkeypatch.setattr(c, "_run_once", fake_once)
    asyncio.run(c.run_sql("SELECT 1"))
    assert calls["n"] == 1
    clock["now"] = 1050.0           # TTL 내 → 캐시
    asyncio.run(c.run_sql("SELECT 1"))
    assert calls["n"] == 1
    clock["now"] = 1200.0           # TTL 경과(1000+100) → 재실행
    asyncio.run(c.run_sql("SELECT 1"))
    assert calls["n"] == 2


class _TimeoutClient:
    """httpx.AsyncClient 대역 — post 가 연결 타임아웃을 던진다."""
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        raise httpx.ReadTimeout("boom")


def test_httpx_error_becomes_huberror(monkeypatch):
    """500 회귀: httpx 예외가 HubError 로 감싸져야 main.run() 이 502 로 변환."""
    c = HubClient()
    c.hub_url = "http://hub"
    c.internal_token = "t"

    async def fake_token(client):
        return "tok"

    async def no_sleep(*_):
        return None

    monkeypatch.setattr(c, "_caller_token", fake_token)
    monkeypatch.setattr("app.hub_client.httpx.AsyncClient", _TimeoutClient)
    monkeypatch.setattr("app.hub_client.asyncio.sleep", no_sleep)  # 재시도 대기 제거
    with pytest.raises(HubError):
        asyncio.run(c.run_sql("SELECT 1"))
