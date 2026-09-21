"""Signal bus — publish + cell 별 fan-out.

publisher 가 `bus.publish(topic, payload)` 를 호출하면 hub 가 모든 cell 의
`config.subscriptions` 패턴(fnmatch glob)을 매칭해, 매칭된 cell 마다 자기
scope 로 `signal.emit` 한다.

설계 의도:
- 변환 코드 중복 제거: cell 마다 source → signal 변환 코드 작성 X. publisher
  (예: cell-infra/data-product/news/*) 가 한 번 publish 하면 매칭 cell 들이
  자동으로 받음.
- cell 격리 유지: 각 signal 은 cell scope storage 에 저장되고 그 cell 의
  triaging-signals·worker 만 본다. bus 는 fan-out 의 단일 진입점.
- cell.subscriptions 의 정본은 cell repo 의 `cell.json` — `cell.github_push`
  webhook 이 cell repo push 시점에 hub cell record 의 subscriptions 를 동기화.

호출 계약:
- 누구나 publish 가능 (admin/cell scope 제한 X) — bus 는 broadcast 모델.
- payload 는 signal-like dict (type, title, description, raw, priority).
- topic 은 dotted hierarchical string (news.hada, market.kospi.daily, metric.k8s.netpol 등).
"""

import fnmatch
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from capability_framework import CapabilityResponse

from ..storage import cells_repo
from .signal import emit_signal_to_cell


router = APIRouter()


SignalType = Literal[
    "capability.insufficient",
    "capability.failed",
    "capability.unauthorized",
    "improvement.harness",
    "opportunity.detected",
    "observation.notable",
    "infra.pod_failed",
]


class BusPublishRequest(BaseModel):
    topic: str = Field(
        description="dotted hierarchical topic. cell.subscriptions 패턴과 fnmatch glob 으로 매칭. 예: news.hada, market.kospi.daily"
    )
    type: SignalType = Field(
        description="signal type — 매칭 cell 에 emit 될 signal record 의 type"
    )
    title: str | None = None
    description: str | None = None
    priority: int | None = Field(
        default=None,
        ge=1, le=5,
        description="1=Backlog, 2=Low(기본), 3=Medium, 4=High, 5=Urgent",
    )
    raw: dict | None = Field(
        default=None,
        description="구조화 evidence — signal-types.schema 가 detail.raw 로 보존",
    )
    issue_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None


def _matches(topic: str, patterns: list[str]) -> bool:
    """fnmatch glob — `news.*` 가 `news.hada`/`news.gn` 매칭."""
    return any(fnmatch.fnmatchcase(topic, p) for p in patterns)


@router.post("/bus.publish")
async def bus_publish(req: BusPublishRequest, request: Request) -> CapabilityResponse:
    """topic 을 받아 매칭된 cell 마다 signal.emit. 매칭 0건이면 빈 fanout 반환.

    매칭 알고리즘은 fnmatch glob — cell.json 의 subscriptions 가
    `["news.*", "market.kospi.*"]` 이면 topic=`news.hada` 매칭, topic=`metric.k8s` 미매칭.

    publisher 의 cell 여부와 무관 (broadcast). 호출자 principal 은 by 필드로 보존.
    """
    principal = getattr(request.state, "principal", None)
    by = principal.id if principal else None

    all_cells = cells_repo.list_all()
    fanout = []
    for cell in all_cells:
        if cell.get("status") != "active":
            continue
        config = cell.get("config") or {}
        subscriptions = config.get("subscriptions") or []
        if not subscriptions:
            continue
        if not _matches(req.topic, subscriptions):
            continue
        record = emit_signal_to_cell(
            cell_id=cell["cell_id"],
            type=req.type,
            title=req.title,
            description=req.description or "",
            priority=req.priority,
            issue_id=req.issue_id,
            project_id=req.project_id,
            session_id=req.session_id,
            raw=req.raw,
            by=by,
        )
        fanout.append({
            "cell_id": cell["cell_id"],
            "signal_id": record["signal_id"],
        })

    return CapabilityResponse(status="ok", data={
        "topic": req.topic,
        "fanout": fanout,
        "count": len(fanout),
    })
