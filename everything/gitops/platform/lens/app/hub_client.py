"""hive hub 호출 클라이언트 — caller_token 부트스트랩 + query.sql.

airflow Schedule pod 와 동일 패턴: hive-caller-creds Secret(HUB_URL,
HUB_INTERNAL_TOKEN)을 envFrom 으로 받아 /auth.caller_token 으로 단명 caller
JWT 를 얻고, 그 JWT(Authorization: Bearer) + X-Cell-Id 로 hub capability
(POST /{name})를 호출한다. lens 는 query.sql 만 쓴다 (read-only).
"""
import asyncio
import os
import time

import httpx


class HubError(Exception):
    pass


def _normalize(data: dict) -> dict:
    """Kyuubi/Thrift 스타일(rows[].fields[].value + schema[].columnName)을
    SPA 가 그리기 쉬운 {columns, rows} 로 평탄화한다."""
    schema = data.get("schema") or []
    columns = [c.get("columnName") for c in schema]
    rows = [[f.get("value") for f in r.get("fields", [])]
            for r in data.get("rows", [])]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": data.get("row_count", len(rows)),
        "ms": data.get("ms"),
    }


class HubClient:
    def __init__(self) -> None:
        self.hub_url = os.environ.get("HUB_URL", "").rstrip("/")
        self.internal_token = os.environ.get("HUB_INTERNAL_TOKEN", "")
        self.cell = os.environ.get("LENS_CELL", "infra")
        self.default_limit = int(os.environ.get("LENS_ROW_LIMIT", "2000"))
        self.cache_ttl = float(os.environ.get("LENS_CACHE_TTL", "3600"))
        self._token: str | None = None
        self._token_exp = 0.0
        self._cache: dict[tuple[str, int], tuple[float, dict]] = {}

    async def _caller_token(self, client: httpx.AsyncClient) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 30:
            return self._token
        if not self.hub_url or not self.internal_token:
            raise HubError("HUB_URL / HUB_INTERNAL_TOKEN not configured")
        resp = await client.post(
            f"{self.hub_url}/auth.caller_token",
            headers={"X-Internal-Token": self.internal_token},
            json={"principal_type": "system", "principal_id": "lens",
                  "cell_id": self.cell},
        )
        if resp.status_code >= 400:
            raise HubError(f"caller_token {resp.status_code}: {resp.text}")
        env = resp.json()
        if env.get("status") != "ok":
            raise HubError(f"caller_token: {env.get('message') or env}")
        d = env["data"]
        self._token = d["token"]
        self._token_exp = now + int(d.get("expires_in", 600))
        return self._token

    async def run_sql(self, sql: str, limit: int | None = None) -> dict:
        eff_limit = min(limit or self.default_limit, 10000)
        key = (sql, eff_limit)
        now = time.time()
        hit = self._cache.get(key)
        if hit and now < hit[0]:
            return hit[1]
        # Kyuubi 세션이 간헐적으로 만료/404 (kyuubi_unreachable) → 1회 재시도로 흡수.
        last: Exception | None = None
        for attempt in range(2):
            try:
                result = await self._run_once(sql, eff_limit)
                self._cache[key] = (now + self.cache_ttl, result)
                return result
            except HubError as e:
                last = e
                if attempt == 0:
                    await asyncio.sleep(1.0)
        raise last  # type: ignore[misc]

    async def _run_once(self, sql: str, limit: int) -> dict:
        # httpx 연결/타임아웃 예외도 HubError 로 감싼다 — 미감싸면 run_sql 재시도도,
        # main.run() 의 502 변환도 통과 못 해 FastAPI 미처리 500 으로 샌다.
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                token = await self._caller_token(client)
                resp = await client.post(
                    f"{self.hub_url}/query.sql",
                    headers={"Authorization": f"Bearer {token}",
                             "X-Cell-Id": self.cell},
                    json={"sql": sql, "limit": limit},
                )
        except httpx.HTTPError as e:
            raise HubError(f"hub request failed: {e}") from e
        if resp.status_code >= 400:
            raise HubError(f"query.sql {resp.status_code}: {resp.text}")
        env = resp.json()
        if env.get("status") != "ok":
            raise HubError(env.get("message") or str(env))
        return _normalize(env.get("data") or {})
