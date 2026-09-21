"""Google capability server.

Google Calendar·Sheets API를 HTTP 엔드포인트로 제공.
Calendar 는 OAuth 2.0 토큰(token.json), Sheets 는 cell별 service-account
키(service_account.json) 기반. 키는 모두 per-cell 디렉토리에서 X-Cell-Id 로 선택.
"""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

import gspread
from fastapi import Request as FastAPIRequest
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from capability_framework import create_app, CapabilityResponse


# --- Config ---

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SCOPES = ["https://www.googleapis.com/auth/calendar"]
# open_by_key 만 쓰므로 drive scope 불요 — spreadsheets 만으로 read/write 가능.
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _cell_keys_dir(cell_id: str) -> Path:
    return DATA_DIR / "cells" / cell_id / "capability_keys" / "google"


def _request_cell_id(request: FastAPIRequest) -> str:
    cell_id = (request.headers.get("X-Cell-Id") or "").strip()
    if not cell_id:
        raise RuntimeError("X-Cell-Id header is required.")
    return cell_id

app = create_app(
    service_id="google",
    version="0.1.0",
    description="Google Calendar·Sheets capability server. Calendar=OAuth 2.0, Sheets=service-account, cell별 키 격리.",
)


# --- Google Calendar client ---

def _normalize_dt(s: str) -> str:
    """YYYY-MM-DDTHH:MM → YYYY-MM-DDTHH:MM:00 (seconds 보정)."""
    if "+" in s or s.endswith("Z"):
        return s
    parts = s.split("T")
    if len(parts) == 2 and parts[1].count(":") == 1:
        return s + ":00"
    return s


def _get_calendar_service(cell_id: str):
    """Build and return an authorized Calendar API service for the given cell."""
    keys_dir = _cell_keys_dir(cell_id)
    token_file = keys_dir / "token.json"

    if not token_file.exists():
        raise RuntimeError(
            f"OAuth token not found at {token_file}. "
            "Initialize cell credentials before calling Google Calendar."
        )

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_file.write_text(creds.to_json())
        else:
            raise RuntimeError(
                f"OAuth token at {token_file} is invalid and cannot be refreshed."
            )

    return build("calendar", "v3", credentials=creds)


# ============================================================
# calendar.fetch
# ============================================================

class CalendarFetchRequest(BaseModel):
    date: str = Field(description="시작 날짜 (YYYY-MM-DD)", examples=["2026-04-21"])
    range: int = Field(default=1, description="가져올 일수", examples=[1, 7])
    calendar_id: str = Field(default="primary", description="캘린더 ID")


@app.post(
    "/calendar.fetch",
    summary="캘린더 이벤트 조회",
    description="특정 날짜부터 range일간의 캘린더 이벤트를 가��온다. 최대 100개.",
    openapi_extra={
        "x-side-effects": "read-only",
        "x-requires-approval": False,
        "x-usage": "Daily 생성 시 오늘 일정 반영, 주간 리뷰 시 실제 시간 사용 확인",
    },
)
async def calendar_fetch(req: CalendarFetchRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        cell_id = _request_cell_id(request)
        # 블로킹 SDK(토큰 refresh·discovery build·HTTP execute)를 스레드로 오프로드 —
        # async 핸들러가 직렬화돼 이벤트 루프를 막지 않게 한다.
        service = await asyncio.to_thread(_get_calendar_service, cell_id)

        start_dt = datetime.strptime(req.date, "%Y-%m-%d")
        end_dt = start_dt + timedelta(days=req.range)

        time_min = start_dt.strftime("%Y-%m-%dT00:00:00+09:00")
        time_max = end_dt.strftime("%Y-%m-%dT00:00:00+09:00")

        result = await asyncio.to_thread(
            lambda: service.events()
            .list(
                calendarId=req.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=100,
            )
            .execute()
        )

        events = []
        for item in result.get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            events.append({
                "id": item["id"],
                "summary": item.get("summary", ""),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "all_day": "date" in start,
                "location": item.get("location"),
                "description": item.get("description"),
                "status": item.get("status"),
                "calendar_id": req.calendar_id,
            })

        return CapabilityResponse(status="ok", data={"events": events, "count": len(events)})

    except Exception as e:
        return CapabilityResponse(status="error", error_code="calendar_error", message=str(e))


# ============================================================
# calendar.create
# ============================================================

class CalendarCreateRequest(BaseModel):
    title: str = Field(description="이벤트 제목", examples=["팀 미팅"])
    start: str = Field(description="시작 시각 (YYYY-MM-DDTHH:MM 또는 종일이면 YYYY-MM-DD)", examples=["2026-04-21T14:00"])
    end: str = Field(description="종료 시각", examples=["2026-04-21T15:00"])
    all_day: bool = Field(default=False, description="종일 이벤트 여부")
    location: str | None = Field(default=None, description="장소")
    description: str | None = Field(default=None, description="설명")
    calendar_id: str = Field(default="primary", description="캘린더 ID")


@app.post(
    "/calendar.create",
    summary="캘린더 이벤트 생성",
    description="Google Calendar에 새 이벤트를 생성한다. 시각은 Asia/Seoul 기준.",
    openapi_extra={
        "x-side-effects": "external",
        "x-requires-approval": False,
        "x-usage": "딥워크 블록 동기화, 미팅/약속 생성",
    },
)
async def calendar_create(req: CalendarCreateRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        cell_id = _request_cell_id(request)
        service = await asyncio.to_thread(_get_calendar_service, cell_id)

        body = {"summary": req.title}

        if req.all_day:
            body["start"] = {"date": req.start}
            body["end"] = {"date": req.end}
        else:
            body["start"] = {"dateTime": _normalize_dt(req.start), "timeZone": "Asia/Seoul"}
            body["end"] = {"dateTime": _normalize_dt(req.end), "timeZone": "Asia/Seoul"}

        if req.location:
            body["location"] = req.location
        if req.description:
            body["description"] = req.description

        event = await asyncio.to_thread(
            lambda: service.events().insert(calendarId=req.calendar_id, body=body).execute()
        )

        return CapabilityResponse(status="ok", data={
            "id": event["id"],
            "summary": event.get("summary"),
            "start": event["start"].get("dateTime") or event["start"].get("date"),
            "end": event["end"].get("dateTime") or event["end"].get("date"),
            "link": event.get("htmlLink"),
        })

    except Exception as e:
        return CapabilityResponse(status="error", error_code="calendar_error", message=str(e))


# ============================================================
# calendar.delete
# ============================================================

class CalendarDeleteRequest(BaseModel):
    event_id: str = Field(description="삭제할 이벤트 ID")
    calendar_id: str = Field(default="primary", description="캘린더 ID")


@app.post(
    "/calendar.delete",
    summary="캘린더 이벤트 삭제",
    description="이벤트를 소프트 삭제한다. 약 30일간 복구 가능 (calendar.list_deleted → calendar.restore).",
    openapi_extra={
        "x-side-effects": "external",
        "x-requires-approval": False,
        "x-recovery": "calendar.list_deleted로 조회 후 calendar.restore로 복원 (30일 이내)",
    },
)
async def calendar_delete(req: CalendarDeleteRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        cell_id = _request_cell_id(request)
        service = await asyncio.to_thread(_get_calendar_service, cell_id)
        await asyncio.to_thread(
            lambda: service.events().delete(calendarId=req.calendar_id, eventId=req.event_id).execute()
        )
        return CapabilityResponse(status="ok", data={"deleted": req.event_id})

    except Exception as e:
        return CapabilityResponse(status="error", error_code="calendar_error", message=str(e))


# ============================================================
# calendar.list_deleted
# ============================================================

class CalendarListDeletedRequest(BaseModel):
    days_back: int = Field(default=30, description="며칠 전까지 조회할지", examples=[7, 30])
    calendar_id: str = Field(default="primary", description="캘린더 ID")


@app.post(
    "/calendar.list_deleted",
    summary="삭제된 이벤트 조회",
    description="최근 삭제된 이벤트 목록을 조회한다. Google은 삭제 후 약 30일간 cancelled 상태로 보존.",
    openapi_extra={
        "x-side-effects": "read-only",
        "x-requires-approval": False,
        "x-usage": "실수로 삭제된 이벤트 확인. calendar.restore와 함께 복구 워크플로우 구성.",
    },
)
async def calendar_list_deleted(req: CalendarListDeletedRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        cell_id = _request_cell_id(request)
        service = await asyncio.to_thread(_get_calendar_service, cell_id)

        since = datetime.now() - timedelta(days=req.days_back)
        time_min = since.strftime("%Y-%m-%dT00:00:00+09:00")

        result = await asyncio.to_thread(
            lambda: service.events()
            .list(
                calendarId=req.calendar_id,
                updatedMin=time_min,
                showDeleted=True,
                singleEvents=True,
                orderBy="updated",
                maxResults=50,
            )
            .execute()
        )

        deleted = []
        for item in result.get("items", []):
            if item.get("status") != "cancelled":
                continue
            start = item.get("start", {})
            end = item.get("end", {})
            deleted.append({
                "id": item["id"],
                "summary": item.get("summary", "(제목 없음)"),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "updated": item.get("updated"),
            })

        return CapabilityResponse(status="ok", data={"events": deleted, "count": len(deleted)})

    except Exception as e:
        return CapabilityResponse(status="error", error_code="calendar_error", message=str(e))


# ============================================================
# calendar.restore
# ============================================================

class CalendarRestoreRequest(BaseModel):
    event_id: str = Field(description="복원할 이벤트 ID (calendar.list_deleted에서 확인)")
    calendar_id: str = Field(default="primary", description="캘린더 ID")


@app.post(
    "/calendar.restore",
    summary="삭제된 이벤트 복원",
    description="소프트 삭제된 이벤트를 confirmed 상태로 복원한다. 삭제 후 약 30일 이내만 가능.",
    openapi_extra={
        "x-side-effects": "external",
        "x-requires-approval": False,
        "x-usage": "실수 삭제 복구. calendar.list_deleted로 ID 확인 후 호출.",
    },
)
async def calendar_restore(req: CalendarRestoreRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        cell_id = _request_cell_id(request)
        service = await asyncio.to_thread(_get_calendar_service, cell_id)

        event = await asyncio.to_thread(
            lambda: service.events()
            .patch(
                calendarId=req.calendar_id,
                eventId=req.event_id,
                body={"status": "confirmed"},
            )
            .execute()
        )

        start = event.get("start", {})
        end = event.get("end", {})
        return CapabilityResponse(status="ok", data={
            "id": event["id"],
            "summary": event.get("summary"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "link": event.get("htmlLink"),
        })

    except Exception as e:
        return CapabilityResponse(status="error", error_code="calendar_error", message=str(e))


# ============================================================
# Google Sheets client (service-account, per-cell)
# ============================================================

def _get_sheets_client(cell_id: str):
    """Build an authorized gspread client from the cell's service-account key.

    키 부재 = 해당 cell 이 Sheets 접근 권한 없음(격리). 타 cell 키는 다른
    service-account 라 그 SA 와 공유되지 않은 시트는 Google ACL 이 거부한다.
    """
    sa_file = _cell_keys_dir(cell_id) / "service_account.json"
    if not sa_file.exists():
        raise RuntimeError(
            f"Service-account key not found at {sa_file}. "
            "Place the cell's Google service-account JSON before calling Sheets."
        )
    creds = ServiceAccountCredentials.from_service_account_file(
        str(sa_file), scopes=SHEETS_SCOPES
    )
    return gspread.authorize(creds)


def _open_worksheet(client, sheet_id: str, worksheet: str | None):
    """worksheet 가 None 이면 첫 시트, 숫자 문자열이면 index, 아니면 title 로 연다."""
    spreadsheet = client.open_by_key(sheet_id)
    if worksheet is None or worksheet == "":
        return spreadsheet.sheet1
    if worksheet.isdigit():
        return spreadsheet.get_worksheet(int(worksheet))
    return spreadsheet.worksheet(worksheet)


# ============================================================
# sheets.read
# ============================================================

class SheetsReadRequest(BaseModel):
    sheet_id: str = Field(description="스프레드시트 ID (URL 의 /d/<ID>/ 부분)", examples=["1AbC...xyz"])
    worksheet: str | None = Field(
        default=None,
        description="워크시트 title 또는 0-based index. 생략 시 첫 시트.",
        examples=["Sheet1", "0"],
    )
    range: str | None = Field(
        default=None,
        description="A1 표기 범위 (예: A1:C10). 생략 시 시트 전체.",
        examples=["A1:C10"],
    )


@app.post(
    "/sheets.read",
    summary="구글 시트 값 읽기",
    description="cell 의 service-account 키로 스프레드시트 값을 읽는다. range 생략 시 시트 전체.",
    openapi_extra={
        "x-side-effects": "read-only",
        "x-requires-approval": False,
        "x-usage": "시트 데이터 조회, write 후 왕복 검증",
    },
)
async def sheets_read(req: SheetsReadRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        cell_id = _request_cell_id(request)
        client = await asyncio.to_thread(_get_sheets_client, cell_id)

        def _read():
            ws = _open_worksheet(client, req.sheet_id, req.worksheet)
            values = ws.get(req.range) if req.range else ws.get_all_values()
            return ws.title, values

        title, values = await asyncio.to_thread(_read)
        return CapabilityResponse(status="ok", data={
            "worksheet": title,
            "range": req.range,
            "values": values,
            "rows": len(values),
        })

    except Exception as e:
        return CapabilityResponse(status="error", error_code="sheets_error", message=str(e))


# ============================================================
# sheets.write
# ============================================================

class SheetsWriteRequest(BaseModel):
    sheet_id: str = Field(description="스프레드시트 ID (URL 의 /d/<ID>/ 부분)", examples=["1AbC...xyz"])
    range: str = Field(description="A1 표기 시작 범위 (예: A1). values 크기만큼 채운다.", examples=["A1", "B2:D4"])
    values: list[list] = Field(description="2차원 값 배열 (행 × 열)", examples=[[["name", "score"], ["a", 1]]])
    worksheet: str | None = Field(
        default=None,
        description="워크시트 title 또는 0-based index. 생략 시 첫 시트.",
        examples=["Sheet1", "0"],
    )
    value_input_option: str = Field(
        default="USER_ENTERED",
        description="USER_ENTERED(수식·형식 해석) 또는 RAW(원시 문자열)",
        examples=["USER_ENTERED", "RAW"],
    )


@app.post(
    "/sheets.write",
    summary="구글 시트 값 쓰기",
    description="cell 의 service-account 키로 지정 범위에 값을 쓴다. 기존 값 덮어쓰기.",
    openapi_extra={
        "x-side-effects": "external",
        "x-requires-approval": False,
        "x-usage": "템플릿·계산 결과를 사용자 시트에 기록",
    },
)
async def sheets_write(req: SheetsWriteRequest, request: FastAPIRequest) -> CapabilityResponse:
    try:
        cell_id = _request_cell_id(request)
        client = await asyncio.to_thread(_get_sheets_client, cell_id)

        def _write():
            ws = _open_worksheet(client, req.sheet_id, req.worksheet)
            # keyword 호출 — gspread 5.x/6.x 에서 update 의 positional 순서가 다르다.
            result = ws.update(
                range_name=req.range,
                values=req.values,
                value_input_option=req.value_input_option,
            )
            return ws.title, result

        title, result = await asyncio.to_thread(_write)
        return CapabilityResponse(status="ok", data={
            "worksheet": title,
            "range": req.range,
            "updated_cells": result.get("updatedCells"),
            "updated_range": result.get("updatedRange"),
        })

    except Exception as e:
        return CapabilityResponse(status="error", error_code="sheets_error", message=str(e))
