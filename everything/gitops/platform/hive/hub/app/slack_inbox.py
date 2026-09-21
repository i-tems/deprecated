"""Slack inbox notification routing and delivery (cell-scoped).

각 cell 은 자체 bot_token + inbox_channel 을 가진다. cell repo 의 `cell.json` 이
정본이며 워커 부팅 시 PVC `/data/cells/<cell>/cell.json` 으로 미러링된다:

    "slack": {"inbox_channel": "C0...", "bot_token": "xoxb-..."}
"""

import json
import os
import threading
import urllib.parse
import urllib.request

from . import cell_config

DEFAULT_SLACK_URL = os.environ.get("SLACK_URL", "").rstrip("/")
HUB_INTERNAL_TOKEN = os.environ.get("HUB_INTERNAL_TOKEN", "").strip()
CONSOLE_BASE_URL = os.environ.get("CONSOLE_BASE_URL", "").rstrip("/")

# 어떤 inbox type을 Slack으로 라우팅할지 (전역 필터)
_DEFAULT_TYPES = "signal.emitted"
SLACK_INBOX_TYPES = {
    item.strip()
    for item in (os.environ.get("SLACK_INBOX_TYPES") or _DEFAULT_TYPES).split(",")
    if item.strip()
}

_SLACK_USER_CACHE: dict[tuple[str, str], str | None] = {}


def _cell_slack_config(cell_id: str) -> dict:
    return cell_config.get(cell_id, "slack")


def _cell_bot_token(cell_id: str) -> str | None:
    token = str(_cell_slack_config(cell_id).get("bot_token") or "").strip()
    return token or None


def _normalize_match_values(owner: str | None) -> set[str]:
    values: set[str] = set()
    text = (owner or "").strip().lower()
    if not text:
        return values
    values.add(text)
    if "@" in text:
        localpart = text.split("@", 1)[0].strip()
        if localpart:
            values.add(localpart)
    return values


def _parse_json_env(name: str, default):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _resolve_slack_mention(cell_id: str, owner: str | None) -> str:
    tags = _parse_json_env("SLACK_OWNER_TAGS", {})
    if not isinstance(tags, dict):
        tags = {}
    tags = {str(key).strip().lower(): value for key, value in tags.items()}
    for key in _normalize_match_values(owner):
        value = tags.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    slack_user_id = _lookup_slack_user_id_by_email(cell_id, owner)
    if slack_user_id:
        return f"<@{slack_user_id}>"

    fallback = (os.environ.get("SLACK_INBOX_MENTION_FALLBACK") or "").strip().lower()
    owner_text = (owner or "").strip()
    if fallback == "handle" and owner_text:
        handle = owner_text.split("@", 1)[0].strip() if "@" in owner_text else owner_text
        if handle:
            return f"@{handle}"
    if fallback == "owner" and owner_text:
        return owner_text
    return ""


def _lookup_slack_user_id_by_email(cell_id: str, owner: str | None) -> str | None:
    email = (owner or "").strip().lower()
    if not email or "@" not in email:
        return None
    bot_token = _cell_bot_token(cell_id)
    if not bot_token:
        return None
    cache_key = (cell_id, email)
    if cache_key in _SLACK_USER_CACHE:
        return _SLACK_USER_CACHE[cache_key]

    query = urllib.parse.urlencode({"email": email})
    req = urllib.request.Request(
        f"https://slack.com/api/users.lookupByEmail?{query}",
        headers={"Authorization": f"Bearer {bot_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        _SLACK_USER_CACHE[cache_key] = None
        return None

    user_id = None
    if payload.get("ok"):
        user = payload.get("user") or {}
        user_id = str(user.get("id") or "").strip() or None
    _SLACK_USER_CACHE[cache_key] = user_id
    return user_id


def _slack_entity_label(inbox_type: str) -> str:
    kind = inbox_type.lower()
    if kind.startswith("issue."):
        return "Issue"
    if kind.startswith("project."):
        return "Project"
    if kind.startswith("signal."):
        return "Signal"
    return "Item"


def _inbox_detail_target(inbox_type: str, ref: str) -> tuple[str, str]:
    """(path, query) — issue/project 은 detail 라우트, signal 은 리스트+focus.
    UI 에 `/signals/:id` detail 라우트가 없어 리스트 페이지에서 단건 강조한다."""
    kind = inbox_type.lower()
    if kind.startswith("issue."):
        return f"/issues/{ref}", ""
    if kind.startswith("project."):
        return f"/projects/{ref}", ""
    if kind.startswith("signal."):
        return "/signals", f"focus={urllib.parse.quote(ref, safe='')}"
    return "", ""


def _build_slack_inbox_links(record: dict) -> tuple[str, str]:
    """(detail_url, inbox_url) — CONSOLE_BASE_URL 또는 ref 가 없으면 빈 문자열.
    cell_id 가 있으면 두 링크 모두 `?cell=<id>` 를 포함해 클릭 시 자동 전환."""
    if not CONSOLE_BASE_URL:
        return "", ""
    inbox_type = str(record.get("type") or "").strip()
    ref = str(record.get("ref") or "").strip()
    cell_id = str(record.get("cell_id") or "").strip()
    cell_q = f"cell={urllib.parse.quote(cell_id, safe='')}" if cell_id else ""
    inbox_url = f"{CONSOLE_BASE_URL}/inbox" + (f"?{cell_q}" if cell_q else "")
    if not ref:
        return "", inbox_url
    detail_path, detail_q = _inbox_detail_target(inbox_type, ref)
    if not detail_path:
        return "", inbox_url
    query = "&".join(part for part in (cell_q, detail_q) if part)
    detail_url = f"{CONSOLE_BASE_URL}{detail_path}" + (f"?{query}" if query else "")
    return detail_url, inbox_url


def _build_slack_inbox_message(cell_id: str, record: dict) -> tuple[str, list[dict]]:
    """Slack inbox 메시지의 (fallback text, blocks) 한 번에 생성. 공통 필드 (mention,
    summary, owner, links) 는 한 번만 추출."""
    inbox_type = str(record.get("type") or "").strip()
    summary = str(record.get("summary") or "").strip()
    owner = str(record.get("owner") or "").strip()
    ref = str(record.get("ref") or "").strip()
    mention = _resolve_slack_mention(cell_id, owner)
    detail_url, inbox_url = _build_slack_inbox_links(record)

    # text fallback (notification preview / accessibility)
    text_lines = []
    if mention:
        text_lines.append(mention)
    text_lines.append(f"*:bell: {inbox_type}*")
    if summary:
        text_lines.append(f"> {summary}")
    if owner:
        text_lines.append(f"*Owner* {owner}")
    if ref:
        text_lines.append(f"*Ref* `{ref}`")
    if cell_id:
        text_lines.append(f"*Cell* `{cell_id}`")
    open_parts = []
    if detail_url:
        open_parts.append(f"<{detail_url}|Open {inbox_type}>")
    if inbox_url:
        open_parts.append(f"<{inbox_url}|Open Inbox>")
    if open_parts:
        text_lines.append(f"*Open* {' | '.join(open_parts)}")
    text = "\n".join(text_lines)

    # blocks
    context_parts = ["📡 *Signal*", f"`{inbox_type}`"]
    if mention:
        context_parts.append(mention)
    elif owner:
        context_parts.append(owner)
    blocks: list[dict] = [
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": "  ·  ".join(context_parts)}]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*{summary or inbox_type}*"}},
    ]
    elements = []
    if detail_url:
        elements.append({"type": "button",
                         "text": {"type": "plain_text",
                                  "text": _slack_entity_label(inbox_type), "emoji": True},
                         "url": detail_url})
    if inbox_url:
        elements.append({"type": "button",
                         "text": {"type": "plain_text", "text": "Inbox", "emoji": True},
                         "url": inbox_url})
    if elements:
        blocks.append({"type": "actions", "elements": elements})
    return text, blocks


def _post_slack_message(cell_id: str, channel: str, text: str, *, blocks: list[dict] | None = None):
    if not DEFAULT_SLACK_URL or not channel or not text:
        return
    body = {"channel": channel, "text": text}
    if blocks:
        body["blocks"] = blocks
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Cell-Id": cell_id,
        "X-Source": "internal",
    }
    if HUB_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = HUB_INTERNAL_TOKEN
    req = urllib.request.Request(
        f"{DEFAULT_SLACK_URL}/slack.send",
        method="POST",
        data=payload,
        headers=headers,
    )
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def _sync_emit_slack_inbox(record: dict):
    inbox_type = str(record.get("type") or "").strip()
    if SLACK_INBOX_TYPES and inbox_type not in SLACK_INBOX_TYPES:
        return
    cell_id = str(record.get("cell_id") or "").strip()
    if not cell_id:
        return
    config = _cell_slack_config(cell_id)
    channel = str(config.get("inbox_channel") or "").strip()
    if not channel:
        return
    if not _cell_bot_token(cell_id):
        return
    text, blocks = _build_slack_inbox_message(cell_id, record)
    _post_slack_message(cell_id, channel, text, blocks=blocks)


def _emit_slack_inbox(record: dict):
    if not DEFAULT_SLACK_URL:
        return
    threading.Thread(target=_sync_emit_slack_inbox, args=(record,), daemon=True).start()
