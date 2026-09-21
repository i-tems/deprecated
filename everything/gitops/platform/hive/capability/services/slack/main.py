"""Slack capability server.

셀별 Bot Token 을 PVC `cell.json` 의 `slack.bot_token` 에서 로드.
"""

import asyncio
import json
import os
from pathlib import Path

from fastapi import Request as FastAPIRequest
from pydantic import BaseModel, Field
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from capability_framework import create_app, CapabilityResponse


# --- Config ---

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SLACK_DEFAULT_USERNAME = os.environ.get("SLACK_DEFAULT_USERNAME", "").strip()
SLACK_DEFAULT_ICON_EMOJI = os.environ.get("SLACK_DEFAULT_ICON_EMOJI", "").strip()

app = create_app(
    service_id="slack",
    version="0.1.0",
    description="Slack 메시지 전송 capability server. Bot Token 인증 기반, 셀별 토큰.",
)


# --- Slack client ---

def _request_cell_id(request: FastAPIRequest) -> str:
    cell_id = (request.headers.get("X-Cell-Id") or "").strip()
    if not cell_id:
        raise RuntimeError("X-Cell-Id header is required.")
    return cell_id


def _cell_bot_token(cell_id: str) -> str:
    cell_json = DATA_DIR / "cells" / cell_id / "cell.json"
    if not cell_json.is_file():
        raise RuntimeError(f"cell.json not found at {cell_json}.")
    data = json.loads(cell_json.read_text(encoding="utf-8"))
    token = str(((data or {}).get("slack") or {}).get("bot_token") or "").strip()
    if not token:
        raise RuntimeError(f"slack.bot_token missing in {cell_json}.")
    return token


def _get_client(cell_id: str) -> WebClient:
    return WebClient(token=_cell_bot_token(cell_id))


# ============================================================
# slack.send
# ============================================================

class SlackSendRequest(BaseModel):
    channel: str = Field(
        description="메시지를 보낼 채널 (예: #general, C01234ABCDE).",
        examples=["#general", "#alerts", "C01234ABCDE"],
    )
    text: str = Field(
        description="전송할 메시지 텍스트. Slack mrkdwn 형식 지원.",
        examples=["Issue 완료: 데이터 파이프라인 배포"],
    )
    thread_ts: str | None = Field(
        default=None,
        description="스레드 답글로 보낼 경우 부모 메시지의 ts 값.",
    )
    username: str | None = Field(
        default=None,
        description="메시지 표시 이름 override. chat:write.customize scope 필요.",
        examples=["왈숙네"],
    )
    icon_emoji: str | None = Field(
        default=None,
        description="메시지 아이콘 emoji override. chat:write.customize scope 필요.",
        examples=[":bento:"],
    )
    blocks: list[dict] | None = Field(
        default=None,
        description="Slack Block Kit payload. text는 알림 fallback으로도 함께 보내는 것을 권장.",
    )


class SlackLookupUserByEmailRequest(BaseModel):
    email: str = Field(
        description="조회할 Slack 사용자 이메일.",
        examples=["dahuin000@gmail.com"],
    )


@app.post(
    "/slack.send",
    summary="Slack 메시지 전송",
    description="지정 채널에 텍스트 메시지를 전송한다. thread_ts 지정 시 스레드 답글로 전송.",
    openapi_extra={
        "x-side-effects": "external",
        "x-requires-approval": False,
        "x-usage": "Issue 완료 알림, 중요 이벤트 알림, Agent 실행 결과 공유",
    },
)
async def slack_send(req: SlackSendRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        client = _get_client(_request_cell_id(request))
        kwargs = {"channel": req.channel, "text": req.text}
        if req.thread_ts:
            kwargs["thread_ts"] = req.thread_ts
        username = (req.username or SLACK_DEFAULT_USERNAME or "").strip()
        if username:
            kwargs["username"] = username
        icon_emoji = (req.icon_emoji or SLACK_DEFAULT_ICON_EMOJI or "").strip()
        if icon_emoji:
            kwargs["icon_emoji"] = icon_emoji
        if req.blocks:
            kwargs["blocks"] = req.blocks

        # 블로킹 Slack SDK HTTP 호출을 스레드로 오프로드 — 이벤트 루프 직렬화 방지.
        response = await asyncio.to_thread(lambda: client.chat_postMessage(**kwargs))

        return CapabilityResponse(status="ok", data={
            "channel": response["channel"],
            "ts": response["ts"],
            "message": req.text,
            "username": kwargs.get("username"),
            "icon_emoji": kwargs.get("icon_emoji"),
            "blocks": kwargs.get("blocks"),
        })

    except SlackApiError as e:
        return CapabilityResponse(
            status="error",
            error_code="slack_api_error",
            message=f"{e.response['error']}: {e.response.get('detail', '')}".strip(": "),
        )
    except Exception as e:
        return CapabilityResponse(status="error", error_code="slack_error", message=str(e))

@app.post(
    "/slack.lookup_user_by_email",
    summary="Slack 사용자 이메일 조회",
    description="이메일로 Slack 사용자 ID와 표시명을 조회한다.",
    openapi_extra={
        "x-side-effects": "none",
        "x-requires-approval": False,
        "x-usage": "알림 mention 대상 사용자 추론",
    },
)
async def slack_lookup_user_by_email(req: SlackLookupUserByEmailRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        client = _get_client(_request_cell_id(request))
        # 블로킹 Slack SDK HTTP 호출을 스레드로 오프로드 — 이벤트 루프 직렬화 방지.
        response = await asyncio.to_thread(lambda: client.users_lookupByEmail(email=req.email))
        user = response["user"]
        profile = user.get("profile") or {}
        return CapabilityResponse(status="ok", data={
            "email": req.email,
            "user_id": user.get("id"),
            "name": user.get("name"),
            "display_name": profile.get("display_name") or profile.get("real_name") or user.get("name"),
        })
    except SlackApiError as e:
        return CapabilityResponse(
            status="error",
            error_code="slack_api_error",
            message=f"{e.response['error']}: {e.response.get('detail', '')}".strip(": "),
        )
    except Exception as e:
        return CapabilityResponse(status="error", error_code="slack_error", message=str(e))

