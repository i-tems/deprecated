"""Hub API helpers for the agent loop.

HubClient는 caller_token (Bearer) 인증을 요구한다. 첫 토큰 발급(bootstrap)은
hub_client_bootstrap 모듈의 mint_caller_token을 별도로 사용.
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request


def _new_trace_id() -> str:
    return secrets.token_hex(16)


def _new_span_id() -> str:
    return secrets.token_hex(8)


def _format_traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


def _parse_traceparent(header: str | None) -> tuple[str, str] | None:
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace_id, span_id, _flags = parts
    if version != "00" or len(trace_id) != 32 or len(span_id) != 16:
        return None
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    try:
        int(trace_id, 16)
        int(span_id, 16)
    except ValueError:
        return None
    return trace_id, span_id


class HubClient:
    def __init__(self, *, hub_url: str, cell_id: str, logger, caller_token: str | None = None, traceparent: str | None = None):
        self.hub_url = hub_url
        self.cell_id = cell_id
        self.logger = logger
        self.session_id: str | None = None
        token = (caller_token or os.environ.get("HUB_CALLER_TOKEN", "").strip()) or None
        if not token:
            raise RuntimeError(
                "HubClient requires caller_token. Bootstrap one via /auth.caller_token "
                "(see hub_client_bootstrap.mint_caller_token)."
            )
        self.caller_token = token
        # 기본 trace context — 호출자가 명시하지 않으면 env HUB_TRACEPARENT 또는 새 trace로.
        env_tp = os.environ.get("HUB_TRACEPARENT", "").strip() or None
        parsed = _parse_traceparent(traceparent or env_tp)
        if parsed is not None:
            self._default_trace_id, self._default_span_id = parsed
        else:
            self._default_trace_id = _new_trace_id()
            self._default_span_id = _new_span_id()

    def api(self, endpoint: str, data: dict | None = None, *, issue_id: str | None = None, session_id: str | None = None, timeout: int = 30, traceparent: str | None = None) -> dict:
        url = f"{self.hub_url}/{endpoint}"
        payload = json.dumps(data or {}).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Cell-Id": self.cell_id,
            "Authorization": f"Bearer {self.caller_token}",
        }
        if issue_id:
            headers["X-Issue-Id"] = issue_id
        sid = session_id or self.session_id
        if sid:
            headers["X-Session-Id"] = sid
        # trace 헤더: 명시된 traceparent → 기본 client trace_id에 새 span 부착.
        if traceparent:
            tp = traceparent
        else:
            tp = _format_traceparent(self._default_trace_id, _new_span_id())
        headers["traceparent"] = tp
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def api_safe(self, endpoint: str, data: dict, *, issue_id: str | None = None, session_id: str | None = None, label: str = "") -> dict | None:
        try:
            return self.api(endpoint, data, issue_id=issue_id, session_id=session_id)
        except urllib.error.URLError as exc:
            self.logger.error(f"{label}: {exc}")
            return None

    def get_all_goals(self) -> list:
        resp = self.api("project.list", {})
        return resp.get("data", {}).get("projects", [])

    def get_tasks(self, project_id: str) -> list:
        resp = self.api("issue.list", {"project_id": project_id, "limit": 500})
        return resp.get("data", {}).get("issues", [])

    def get_issues_without_project(self) -> list:
        resp = self.api("issue.list", {"standalone": True, "limit": 500})
        return resp.get("data", {}).get("issues", [])

    def get_all_initiatives(self) -> list:
        """모든 status 의 Initiative. work_finder 가 active 만 거르되, parent_initiative_id
        집합으로 frame(=sub-initiative 보유) 을 식별해 자동 오케스트레이션에서 제외한다
        (frame 은 영구 anchor, 사람/CEO 관리). leaf 만 자율 오케스트레이션."""
        resp = self.api("initiative.list", {"parent_initiative_id": "__all__", "limit": 500})
        return resp.get("data", {}).get("initiatives", [])

    def get_initiative_projects(self, initiative_id: str) -> list:
        """이 Initiative 에 attach 된 자식 Project (자식 완료 판단·roster 용)."""
        resp = self.api("project.list", {"initiative_id": initiative_id, "limit": 500})
        return resp.get("data", {}).get("projects", [])

    def get_events(self, entity_id: str, entity_type: str, *, kinds: list[str] | None = None, limit: int = 200) -> list:
        try:
            resp = self.api("event.list", {"entity_type": entity_type, "entity_id": entity_id, "limit": limit})
        except urllib.error.URLError as exc:
            self.logger.warning(f"이벤트 조회 실패: {exc}")
            return []
        feed = resp.get("data", {}).get("feed", [])
        if kinds is not None:
            feed = [item for item in feed if item.get("kind") in kinds]
        return feed

    def get_signals(self, issue_id: str, *, limit: int = 50) -> list:
        try:
            resp = self.api("signal.list", {"issue_id": issue_id, "limit": limit})
        except urllib.error.URLError as exc:
            self.logger.warning(f"시그널 조회 실패: {exc}")
            return []
        return resp.get("data", {}).get("signals", [])

    def get_sibling_tasks(self, project_id: str, exclude_issue_id: str) -> list:
        try:
            siblings = self.get_tasks(project_id)
        except urllib.error.URLError as exc:
            self.logger.warning(f"sibling issue 조회 실패: {exc}")
            return []
        return [t for t in siblings if t.get("issue_id") != exclude_issue_id]

