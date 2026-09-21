"""사용자 설정 조회/수정 + 프로필 디렉토리.

저장소는 볼륨에 놓인 단일 JSON 파일(email→설정 dict). 오브젝트 스토리지가 없으므로
아바타는 브라우저에서 128px 로 리사이즈한 data URI 문자열을 그대로 담는다(작아서 무방).
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse
from ..auth import request_auth_payload

router = APIRouter()

USER_SETTINGS_PATH = Path(os.environ.get("USER_SETTINGS_PATH", "/var/data/user_settings.json"))

DISPLAY_NAME_MAX = 64
# 아바타 data URI 문자열 상한. 128px webp 는 보통 5~15KB — 넉넉히 잡아도 JSON 파일이 가볍다.
AVATAR_MAX_CHARS = 300_000


def _load_settings() -> dict[str, dict]:
    if not USER_SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(USER_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_settings(data: dict[str, dict]):
    USER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _auth_payload(request: Request) -> dict | None:
    return request_auth_payload(request)


def _default_git_identity(payload: dict) -> dict[str, str]:
    email = str(payload.get("sub", "")).strip()
    name = str(payload.get("name", "")).strip() or email.split("@", 1)[0]
    return {
        "name": name,
        "email": email,
    }


def _stored_str(stored: dict | None, key: str) -> str | None:
    return str((stored or {}).get(key, "")).strip() or None


def profile_override(email: str) -> dict[str, str | None]:
    """email 사용자의 표시용 override (display_name/avatar). auth 응답·디렉토리 공용."""
    stored = _load_settings().get(email.lower())
    return {
        "display_name": _stored_str(stored, "display_name"),
        "avatar": (stored or {}).get("avatar") or None,
    }


def _response_body(email: str, payload: dict, stored: dict | None) -> dict:
    defaults = _default_git_identity(payload)
    git_name = _stored_str(stored, "git_name")
    git_email = _stored_str(stored, "git_email")
    display_name = _stored_str(stored, "display_name")
    avatar = (stored or {}).get("avatar") or None
    # 닉네임 기본값 = OAuth name(=git default name 과 동일 소스).
    default_display_name = defaults["name"]
    return {
        "email": email,
        "git_name": git_name,
        "git_email": git_email,
        "default_git_name": defaults["name"],
        "default_git_email": defaults["email"],
        "effective_git_name": git_name or defaults["name"],
        "effective_git_email": git_email or defaults["email"],
        "display_name": display_name,
        "avatar": avatar,
        "default_display_name": default_display_name,
        "effective_display_name": display_name or default_display_name,
    }


class UserSettingsGetRequest(BaseModel):
    pass


class UserSettingsUpdateRequest(BaseModel):
    # None = 변경 안 함, 빈 문자열 = override 해제. 섹션별 부분 저장을 허용한다.
    git_name: str | None = Field(default=None, description="Git author name override. Empty clears override.")
    git_email: str | None = Field(default=None, description="Git author email override. Empty clears override.")
    display_name: str | None = Field(default=None, description="표시 닉네임 override. Empty clears override.")
    avatar: str | None = Field(default=None, description="아바타 data URI(이미지). Empty clears override.")


class UserDirectoryListRequest(BaseModel):
    pass


@router.post("/user.settings.get")
def user_settings_get(_: UserSettingsGetRequest, request: Request) -> CapabilityResponse:
    payload = _auth_payload(request)
    if not payload:
        return CapabilityResponse(status="error", error_code="unauthorized", message="인증이 필요합니다.")

    email = str(payload.get("sub", "")).strip()
    if not email:
        return CapabilityResponse(status="error", error_code="invalid_token", message="사용자 이메일이 없습니다.")

    stored = _load_settings().get(email.lower())
    return CapabilityResponse(status="ok", data=_response_body(email, payload, stored))


def _apply_field(entry: dict, key: str, value: str | None):
    """None=유지, 그 외=설정(빈 문자열이면 키 제거)."""
    if value is None:
        return
    v = value.strip()
    if v:
        entry[key] = v
    else:
        entry.pop(key, None)


@router.post("/user.settings.update")
async def user_settings_update(body: UserSettingsUpdateRequest, request: Request) -> CapabilityResponse:
    payload = _auth_payload(request)
    if not payload:
        return CapabilityResponse(status="error", error_code="unauthorized", message="인증이 필요합니다.")

    email = str(payload.get("sub", "")).strip()
    if not email:
        return CapabilityResponse(status="error", error_code="invalid_token", message="사용자 이메일이 없습니다.")

    if body.git_email is not None and body.git_email.strip() and "@" not in body.git_email:
        return CapabilityResponse(status="error", error_code="invalid_input", message="유효한 Git 이메일이 필요합니다.")
    if body.display_name is not None and len(body.display_name.strip()) > DISPLAY_NAME_MAX:
        return CapabilityResponse(status="error", error_code="invalid_input", message=f"닉네임은 {DISPLAY_NAME_MAX}자 이하여야 합니다.")
    if body.avatar is not None and body.avatar.strip():
        av = body.avatar.strip()
        if not av.startswith("data:image/"):
            return CapabilityResponse(status="error", error_code="invalid_input", message="아바타는 이미지여야 합니다.")
        if len(av) > AVATAR_MAX_CHARS:
            return CapabilityResponse(status="error", error_code="invalid_input", message="아바타 이미지가 너무 큽니다.")

    all_settings = _load_settings()
    key = email.lower()
    entry = dict(all_settings.get(key) or {})
    _apply_field(entry, "git_name", body.git_name)
    _apply_field(entry, "git_email", body.git_email)
    _apply_field(entry, "display_name", body.display_name)
    _apply_field(entry, "avatar", body.avatar)

    if entry:
        all_settings[key] = entry
    else:
        all_settings.pop(key, None)
    _save_settings(all_settings)

    return CapabilityResponse(status="ok", data=_response_body(email, payload, all_settings.get(key)))


@router.post("/user.directory.list")
def user_directory_list(_: UserDirectoryListRequest, request: Request) -> CapabilityResponse:
    """override(닉네임/아바타)를 설정한 사용자 목록. OwnerAvatar 가 타 사용자 표시에 쓴다."""
    payload = _auth_payload(request)
    if not payload:
        return CapabilityResponse(status="error", error_code="unauthorized", message="인증이 필요합니다.")

    users = []
    for email, stored in _load_settings().items():
        display_name = _stored_str(stored, "display_name")
        avatar = (stored or {}).get("avatar") or None
        if display_name or avatar:
            users.append({"email": email, "display_name": display_name, "avatar": avatar})
    return CapabilityResponse(status="ok", data={"users": users})
