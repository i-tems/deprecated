"""itemflow(Airflow DAG) → hub cell-notify.

한 Airflow 가 여러 cell DAG 를 돌린다. DAG(itemflow)는 cell slack
토큰을 안 들고 cell 이름만 보내고, hub 가 그 cell 의 cell.json
slack(cell_config 재사용)으로 발송한다. in-cluster 호출이며
X-Itemflow-Token(=HUB_CELL_WEBHOOK_SECRET) 으로 자체 검증
(caller-JWT 와 분리 — auth_middleware SKIP_PATHS 등록)."""
import hmac
import os

from fastapi import APIRouter, Request
from pydantic import BaseModel

from capability_framework import CapabilityResponse

from .. import slack_inbox

router = APIRouter()


class ItemflowNotifyRequest(BaseModel):
    cell: str
    kind: str = "FAILURE"
    dag_id: str = ""
    issue_id: str = ""
    run_id: str = ""
    owner: str = ""
    detail: str = ""


@router.post("/itemflow.notify")
async def itemflow_notify(req: ItemflowNotifyRequest,
                          request: Request) -> CapabilityResponse:
    secret = os.environ.get("HUB_CELL_WEBHOOK_SECRET", "").strip()
    if not secret:
        return CapabilityResponse(status="error",
                                  error_code="auth_unconfigured",
                                  message="HUB_CELL_WEBHOOK_SECRET 미설정")
    if not hmac.compare_digest(
            request.headers.get("x-itemflow-token", ""), secret):
        return CapabilityResponse(status="error", error_code="auth_invalid",
                                  message="bad token")
    cell = (req.cell or "").strip()
    if not cell:
        return CapabilityResponse(status="error",
                                  error_code="invalid_request",
                                  message="cell required")
    # itemflow 는 meta 소스 ns(예: cell-items)를 보내지만 hub cell_config
    # 키는 short(items). cell 그대로 → cell- prefix 제거 순으로 해석.
    resolved, channel = cell, ""
    for c in (cell, cell[5:] if cell.startswith("cell-") else cell):
        ch = str((slack_inbox._cell_slack_config(c) or {}).get(
            "inbox_channel") or "").strip()
        if ch:
            resolved, channel = c, ch
            break
    if not channel:
        return CapabilityResponse(status="ok", data={
            "skipped": f"cell '{cell}' slack.inbox_channel 미해석"})
    icon = ":fire:" if req.kind.upper() == "FAILURE" \
        else ":white_check_mark:"
    text = (
        f"{icon} *itemflow {req.kind}* — `{req.dag_id}`"
        + (f" / `{req.issue_id}`" if req.issue_id else "")
        + (f"\nrun: `{req.run_id}`" if req.run_id else "")
        + (f"\nowner: {req.owner}" if req.owner else "")
        + (f"\n```{req.detail[:1200]}```" if req.detail else "")
    )
    slack_inbox._post_slack_message(resolved, channel, text)
    return CapabilityResponse(status="ok", data={
        "cell": resolved, "channel": channel, "kind": req.kind})
