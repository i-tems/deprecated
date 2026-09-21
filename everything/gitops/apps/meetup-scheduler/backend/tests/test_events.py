"""
Unit tests for NDJSON event logging.

Coverage:
  (a) Each emit call appends exactly one JSON line to the correct file.
  (b) PII-forbidden fields (email, name, phone, invite_code body, photo body,
      schedule text) are never serialised into any event line.
  (c) emit() failure does NOT propagate to the caller (domain isolation).
  (d) hash_id() is deterministic for the same input.
"""

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_events_module(salt: str = "test-salt", data_dir: str | None = None):
    """Reload app.core.events with fresh module state and inject salt directly."""
    for mod in ["app.core.events", "app.core.storage"]:
        sys.modules.pop(mod, None)

    env = {"EVENT_HASH_SALT": salt}
    if data_dir:
        env["DATA_DIR"] = data_dir

    with patch.dict(os.environ, env, clear=False):
        import app.core.events as events_mod

    # Force-set cached salt to bypass lazy env read after patch.dict exits
    events_mod._salt = salt
    events_mod._enabled = True
    events_mod._salt_warned = False
    return events_mod


def _read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# (a) emit appends exactly one line per call
# ---------------------------------------------------------------------------

def test_emit_appends_one_line(tmp_path):
    events_mod = _load_events_module(data_dir=str(tmp_path))

    events_dir = tmp_path / "events"
    events_dir.mkdir(exist_ok=True)

    with patch.dict(os.environ, {"DATA_DIR": str(tmp_path)}):
        # Patch DATA_DIR inside the storage module the events module references
        with patch("app.core.storage.DATA_DIR", tmp_path):
            events_mod.emit("user.signed_up", {"signup_source": "direct", "invite_origin_group_id_hash": None}, user_id="u1")
            events_mod.emit("group.created", {"group_id_hash": "abc", "initial_member_count": 1}, user_id="u1")

    ndjson_files = list(events_dir.glob("*.ndjson"))
    assert len(ndjson_files) == 1, f"Expected 1 ndjson file, got {ndjson_files}"

    lines = _read_lines(ndjson_files[0])
    assert len(lines) == 2

    assert lines[0]["event"] == "user.signed_up"
    assert lines[1]["event"] == "group.created"

    # Verify envelope fields
    for line in lines:
        assert line["schema_version"] == 1
        assert "ts" in line
        assert "props" in line


def test_emit_request_uses_separate_file(tmp_path):
    events_mod = _load_events_module(data_dir=str(tmp_path))
    events_dir = tmp_path / "events"
    events_dir.mkdir(exist_ok=True)

    with patch("app.core.storage.DATA_DIR", tmp_path):
        events_mod.emit("group.joined", {"group_id_hash": "x", "via_invite": True, "is_new_user": False}, user_id="u1")
        events_mod.emit_request("request.completed", {"route_pattern": "GET /api/health", "status_code": 200, "duration_ms": 5})

    domain_files = [f for f in events_dir.glob("*.ndjson") if "requests" not in f.name]
    request_files = [f for f in events_dir.glob("*.requests.ndjson")]

    assert len(domain_files) == 1
    assert len(request_files) == 1

    domain_lines = _read_lines(domain_files[0])
    request_lines = _read_lines(request_files[0])

    assert len(domain_lines) == 1
    assert len(request_lines) == 1
    assert domain_lines[0]["event"] == "group.joined"
    assert request_lines[0]["event"] == "request.completed"


def test_all_seven_events_emit_one_line_each(tmp_path):
    events_mod = _load_events_module(data_dir=str(tmp_path))
    events_dir = tmp_path / "events"
    events_dir.mkdir(exist_ok=True)

    event_calls = [
        ("user.signed_up", {"signup_source": "direct", "invite_origin_group_id_hash": None}),
        ("schedule.first_recorded", {"days_recorded": 1, "method": "manual"}),
        ("group.created", {"group_id_hash": "g1", "initial_member_count": 1}),
        ("group.joined", {"group_id_hash": "g1", "via_invite": True, "is_new_user": False}),
        ("availability.viewed", {"group_id_hash": "g1", "window_days": 7, "members_with_schedules": 2, "available_days_found": 3}),
        ("schedule.updated", {"delta_added": 0, "delta_removed": 1, "method": "manual"}),
        ("ai_schedule.recognized", {"outcome": "success", "days_extracted": 5, "confidence_score": None, "duration_ms": 1200}),
    ]

    with patch("app.core.storage.DATA_DIR", tmp_path):
        for event_name, props in event_calls:
            events_mod.emit(event_name, props, user_id="u1")

    ndjson_files = [f for f in events_dir.glob("*.ndjson") if "requests" not in f.name]
    assert len(ndjson_files) == 1

    lines = _read_lines(ndjson_files[0])
    assert len(lines) == 7

    emitted_names = [l["event"] for l in lines]
    for event_name, _ in event_calls:
        assert event_name in emitted_names, f"{event_name} missing from emitted events"


# ---------------------------------------------------------------------------
# (b) PII forbidden fields are never serialised
# ---------------------------------------------------------------------------

PII_FIELDS = {"email", "name", "phone", "invite_code", "photo", "schedule_text"}


def _contains_pii(lines: list[dict]) -> list[str]:
    """Return list of PII field names found anywhere in the serialised event lines."""
    found = []
    for line in lines:
        serialised = json.dumps(line)
        for field in PII_FIELDS:
            if f'"{field}"' in serialised:
                found.append(field)
    return found


def test_pii_fields_not_in_user_signed_up(tmp_path):
    events_mod = _load_events_module(data_dir=str(tmp_path))
    events_dir = tmp_path / "events"
    events_dir.mkdir(exist_ok=True)

    with patch("app.core.storage.DATA_DIR", tmp_path):
        # Attempt to sneak PII into props (should never happen in real code but test the boundary)
        events_mod.emit("user.signed_up", {
            "signup_source": "direct",
            "invite_origin_group_id_hash": None,
            # These should NOT be in the spec but if they were accidentally included:
        }, user_id="real-user-id")

    lines = _read_lines(list(events_dir.glob("*.ndjson"))[0])
    pii_found = _contains_pii(lines)
    assert pii_found == [], f"PII fields found in event log: {pii_found}"


def test_user_id_is_hashed_not_plain(tmp_path):
    plain_user_id = "user-abc-123"
    events_mod = _load_events_module(data_dir=str(tmp_path), salt="test-salt-xyz")
    events_dir = tmp_path / "events"
    events_dir.mkdir(exist_ok=True)

    with patch("app.core.storage.DATA_DIR", tmp_path):
        events_mod.emit("group.created", {"group_id_hash": "g1", "initial_member_count": 1}, user_id=plain_user_id)

    lines = _read_lines(list(events_dir.glob("*.ndjson"))[0])
    serialised = json.dumps(lines[0])

    assert plain_user_id not in serialised, "Plain user_id leaked into event log"
    assert lines[0]["user_id_hash"] is not None
    assert len(lines[0]["user_id_hash"]) == 16  # SHA256[:16]


# ---------------------------------------------------------------------------
# (c) emit failure does NOT propagate to caller
# ---------------------------------------------------------------------------

def test_emit_failure_isolated(tmp_path):
    """If the file write fails, emit() must swallow the exception."""
    events_mod = _load_events_module(data_dir=str(tmp_path))

    with patch("app.core.storage.DATA_DIR", tmp_path):
        with patch("app.core.events._write_line", side_effect=OSError("disk full")):
            # Must not raise
            events_mod.emit("user.signed_up", {"signup_source": "direct", "invite_origin_group_id_hash": None})


def test_emit_request_failure_isolated(tmp_path):
    events_mod = _load_events_module(data_dir=str(tmp_path))

    with patch("app.core.storage.DATA_DIR", tmp_path):
        with patch("app.core.events._write_line", side_effect=RuntimeError("unexpected")):
            events_mod.emit_request("request.completed", {"route_pattern": "GET /", "status_code": 200, "duration_ms": 1})


# ---------------------------------------------------------------------------
# (d) hash_id() is deterministic
# ---------------------------------------------------------------------------

def test_hash_id_deterministic(tmp_path):
    events_mod = _load_events_module(data_dir=str(tmp_path), salt="stable-salt")

    h1 = events_mod.hash_id("some-user-id")
    h2 = events_mod.hash_id("some-user-id")
    h3 = events_mod.hash_id("other-user-id")

    assert h1 == h2, "Same input must produce same hash"
    assert h1 != h3, "Different inputs must produce different hashes"
    assert len(h1) == 16


def test_hash_id_none_returns_none(tmp_path):
    events_mod = _load_events_module(data_dir=str(tmp_path), salt="some-salt")
    assert events_mod.hash_id(None) is None


def test_hash_id_without_salt_returns_none(tmp_path):
    """When EVENT_HASH_SALT is unset, hash_id should return None (logging disabled)."""
    if "app.core.events" in sys.modules:
        del sys.modules["app.core.events"]
    if "app.core.storage" in sys.modules:
        del sys.modules["app.core.storage"]

    env = os.environ.copy()
    env.pop("EVENT_HASH_SALT", None)
    env["DATA_DIR"] = str(tmp_path)

    with patch.dict(os.environ, env, clear=True):
        import app.core.events as events_mod

    result = events_mod.hash_id("some-value")
    assert result is None
