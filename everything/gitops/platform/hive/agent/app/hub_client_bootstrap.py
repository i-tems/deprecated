"""Caller token bootstrap — agent-loop이 자기 첫 token을 발급받는 별도 경로.

HubClient는 Bearer 강제이므로 bootstrap은 별도 helper로 분리. X-Internal-Token
으로 hub `/auth.caller_token`을 호출해 system principal 토큰을 받는다. Hub의
AuthMiddleware는 이 path 한정으로 X-Internal-Token을 허용한다.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request


def mint_caller_token(
    *,
    hub_url: str,
    principal_type: str,
    principal_id: str,
    cell_id: str | None = None,
    issue_id: str | None = None,
    session_type: str | None = None,
    expiry_seconds: int | None = None,
    timeout: int = 10,
    logger: logging.Logger | None = None,
) -> str | None:
    """Hub /auth.caller_token에 X-Internal-Token으로 호출해 caller token 발급.

    bootstrap 전용 entry point. 발급 실패 시 None을 반환 (agent-loop은 fail-fast).
    """
    internal_token = os.environ.get("HUB_INTERNAL_TOKEN", "").strip()
    if not internal_token:
        if logger:
            logger.error("[bootstrap] HUB_INTERNAL_TOKEN env가 비어 있어 caller token 발급 불가")
        return None

    body: dict = {"principal_type": principal_type, "principal_id": principal_id}
    if cell_id:
        body["cell_id"] = cell_id
    if issue_id:
        body["issue_id"] = issue_id
    if session_type:
        body["session_type"] = session_type
    if expiry_seconds:
        body["expiry_seconds"] = expiry_seconds

    req = urllib.request.Request(
        f"{hub_url}/auth.caller_token",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Internal-Token": internal_token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as exc:
        if logger:
            logger.error(f"[bootstrap] caller_token 발급 실패: {exc}")
        return None
    if data.get("status") != "ok":
        if logger:
            logger.error(f"[bootstrap] caller_token 응답 비정상: {data}")
        return None
    return (data.get("data") or {}).get("token")
