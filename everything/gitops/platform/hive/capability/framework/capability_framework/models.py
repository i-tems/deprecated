from pydantic import BaseModel
from typing import Any


class CapabilityResponse(BaseModel):
    """Capability 호출의 표준 응답.

    status:
      ok - 성공. data에 결과
      error - 실패. error_code + message
      approval_required - 사람 승인 필요. Issue가 waiting으로 전환
    """

    status: str  # "ok" | "error" | "approval_required"
    data: Any | None = None
    error_code: str | None = None
    message: str | None = None
