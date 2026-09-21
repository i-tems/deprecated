import base64
import json
import time
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.day_off import is_day_off_title
from app.core.events import emit
from app.core.storage import storage
from app.schemas.ai_schedule import AiScheduleAction, AiScheduleApplyRequest, AiScheduleResponse

router = APIRouter(prefix="/api/ai-schedule", tags=["ai-schedule"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 10 * 1024 * 1024  # 10MB per file
MAX_FILES = 5


# Design spec → §2: ai_schedule.recognized
# Route: POST /api/ai-schedule/analyze (emits on both success and failure after API attempt)
@router.post("/analyze", response_model=AiScheduleResponse)
async def analyze_schedule(
    message: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    if not message.strip() and not files:
        raise HTTPException(status_code=400, detail="메시지 또는 사진을 하나 이상 입력해주세요")

    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"사진은 최대 {MAX_FILES}장까지 가능합니다")

    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="AI 분석 기능이 설정되지 않았습니다")

    # Read and validate uploaded files
    image_contents = []
    for f in files:
        if f.content_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 이미지 형식: {f.filename}")
        data = await f.read()
        if len(data) > MAX_SIZE:
            raise HTTPException(status_code=400, detail=f"파일이 너무 큽니다: {f.filename} (최대 10MB)")
        image_contents.append((data, f.content_type))

    # Fetch existing schedules for context (next 90 days)
    today = date.today()
    start = (today - timedelta(days=7)).isoformat()
    end = (today + timedelta(days=365)).isoformat()
    existing_blocks = await storage.get_schedule_blocks(user["id"], start, end)

    existing_schedule_text = ""
    if existing_blocks:
        lines = []
        for b in existing_blocks:
            storage._ensure_date_field(b)
            is_pattern = "🔁" if b.get("pattern_id") else ""
            lines.append(f"- {b.get('date', 'N/A')}: {b.get('title') or '(제목 없음)'} {is_pattern}")
        existing_schedule_text = "\n".join(lines)

    # Build Claude API messages
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    content_blocks = []

    # Add images
    for data, media_type in image_contents:
        b64 = base64.standard_b64encode(data).decode("utf-8")
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })

    # Build prompt
    today_str = today.isoformat()
    prompt_parts = [
        f"오늘 날짜: {today_str}",
        "",
        "당신은 일정 관리 AI입니다. 사용자의 요청을 분석하여 일정 추가/수정/삭제 액션을 JSON으로 반환하세요.",
    ]

    if existing_schedule_text:
        prompt_parts.extend([
            "",
            "[현재 등록된 일정]",
            existing_schedule_text,
        ])

    if message.strip():
        prompt_parts.extend([
            "",
            "[사용자 메시지]",
            message.strip(),
        ])

    if image_contents:
        prompt_parts.extend([
            "",
            f"[첨부 이미지: {len(image_contents)}장]",
            "이미지에서 근무표/스케줄 정보를 읽어주세요. 사용자 메시지에 해석 힌트가 있으면 참고하세요.",
        ])

    prompt_parts.extend([
        "",
        """반환 형식 (JSON만, 다른 텍스트 없이):
{
  "actions": [
    {"type": "add", "date": "2025-01-15", "title": "주간근무"},
    {"type": "update", "date": "2025-01-16", "title": "야간근무"},
    {"type": "delete", "date": "2025-01-20", "title": null}
  ],
  "summary": "변경 내용 요약 (한국어, 1~2문장)",
  "pattern_detected": null
}

규칙:
- type: "add"(새 일정), "update"(기존 일정 수정), "delete"(기존 일정 삭제)
- date: YYYY-MM-DD 형식
- title: 일정 제목 (delete 시 null 가능)
- 기존 일정과 같은 날짜에 추가 요청 → "update"로 처리
- 이미지에서 여러 사람이 보이면, 사용자 메시지에서 힌트를 찾거나, 첫 번째/가장 눈에 띄는 사람 기준
- pattern_detected: 반복 패턴 감지 시 포함, 없으면 null
- ⚠️ 중요: 휴무/비번/OFF/오프 등 "쉬는 날"은 절대 actions에 포함하지 마세요. 이 앱에서 일정 블록 = 근무(바쁜 날)입니다. 쉬는 날은 블록이 없는 상태가 정상이며, 블록을 만들면 "바쁨"으로 잘못 표시됩니다. 근무표에서 근무하는 날(주간, 야간, 당직 등)만 추가하세요.
- 🔁 표시가 있는 일정은 교대근무 패턴으로 자동 생성된 것임. 이 일정은 수정/삭제할 수 없음 (삭제해도 패턴에 의해 다시 생성됨). 패턴 일정에 대한 수정/삭제 요청이 오면 actions에 포함하지 말고, summary에 "패턴 일정은 [패턴 관리]에서 변경해주세요"라고 안내
- JSON만 반환""",
    ])

    content_blocks.append({"type": "text", "text": "\n".join(prompt_parts)})

    # Track start time; emit ai_schedule.recognized in finally (success and failure both)
    start_ms = int(time.monotonic() * 1000)
    ai_outcome = "failure"
    days_extracted: int | None = None

    try:
        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": content_blocks}],
            )
        except anthropic.AuthenticationError:
            raise HTTPException(status_code=503, detail="AI API 키가 유효하지 않습니다")
        except anthropic.APIError as e:
            raise HTTPException(status_code=502, detail=f"AI API 호출 실패: {e.message}")

        response_text = response.content[0].text.strip()

        # Parse JSON
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_text = "\n".join(lines[1:-1])
        else:
            json_text = response_text

        try:
            result = json.loads(json_text)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="AI 응답을 파싱할 수 없습니다. 다시 시도해주세요.")

        # pattern_detected가 dict가 아니면 null 처리
        if not isinstance(result.get("pattern_detected"), dict):
            result["pattern_detected"] = None

        try:
            parsed = AiScheduleResponse(**result)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"AI 응답 형식 오류: {str(e)}")

        ai_outcome = "success"
        days_extracted = sum(1 for a in result.get("actions", []) if a.get("type") == "add")
        return parsed

    finally:
        duration_ms = int(time.monotonic() * 1000 - start_ms)
        emit("ai_schedule.recognized", {
            "outcome": ai_outcome,
            "days_extracted": days_extracted,
            "confidence_score": None,
            "duration_ms": duration_ms,
        }, user_id=user["id"])


@router.post("/apply")
async def apply_schedule_actions(
    body: AiScheduleApplyRequest,
    user: dict = Depends(get_current_user),
):
    results = {"added": 0, "updated": 0, "deleted": 0, "errors": []}

    for action in body.actions:
        date_str = action.date.isoformat()
        try:
            # Defensive: AI may slip a day-off in despite the prompt. Skip silently for delete,
            # report for add/update so the user notices the model misclassified.
            if action.type in ("add", "update") and is_day_off_title(getattr(action, "title", None)):
                results["errors"].append(f"{date_str}: '{action.title}'은 휴무 키워드라 추가하지 않았습니다 (빈 칸 = 휴무)")
                continue
            existing = await storage.get_schedule_block_by_date(user["id"], date_str)

            if action.type == "add":
                if existing:
                    if existing.get("pattern_id"):
                        results["errors"].append(f"{date_str}: 패턴 일정은 수정할 수 없습니다 (패턴 관리에서 변경)")
                        continue
                    await storage.update_schedule_block(existing["id"], user["id"], title=action.title)
                    results["updated"] += 1
                else:
                    await storage.create_schedule_block(
                        user_id=user["id"], title=action.title, date=date_str,
                    )
                    results["added"] += 1

            elif action.type == "update":
                if existing:
                    if existing.get("pattern_id"):
                        results["errors"].append(f"{date_str}: 패턴 일정은 수정할 수 없습니다 (패턴 관리에서 변경)")
                        continue
                    await storage.update_schedule_block(existing["id"], user["id"], title=action.title)
                    results["updated"] += 1
                else:
                    await storage.create_schedule_block(
                        user_id=user["id"], title=action.title, date=date_str,
                    )
                    results["added"] += 1

            elif action.type == "delete":
                if existing:
                    if existing.get("pattern_id"):
                        results["errors"].append(f"{date_str}: 패턴 일정은 삭제할 수 없습니다 (삭제해도 패턴에 의해 다시 생성됩니다)")
                        continue
                    await storage.delete_schedule_block(existing["id"], user["id"])
                    results["deleted"] += 1

        except Exception as e:
            results["errors"].append(f"{date_str}: {str(e)}")

    return results
