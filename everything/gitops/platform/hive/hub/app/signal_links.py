"""Signal linkage helpers for Project/Issue lifecycle integration."""

from datetime import datetime, timezone
from pathlib import Path

from .storage import all_partition_paths, read_jsonl, write_jsonl


def transition_linked_signals(
    signal_dir: Path,
    *,
    entity_type: str,
    entity_id: str,
    source_signal_ids: list[str] | None,
    entity_status: str,
    by: str = "system",
) -> int:
    """Move consumed Signals when their linked entity reaches a terminal outcome.

    Project/Issue: done → consumed (no-op for already-consumed), 폐기 → emitted
    (reopen for re-triage). 폐기 = Issue 의 cancelled/error 또는 Project(container) 의
    archive. 양방향 링크 (entity.source_signal_ids ↔ signal.project_id/issue_id).
    """
    if entity_type in {"project", "issue"}:
        if entity_status == "done":
            next_status = "consumed"
        elif entity_status in {"cancelled", "error", "archive"}:
            next_status = "emitted"
        else:
            return 0
        link_field = "project_id" if entity_type == "project" else "issue_id"
    else:
        return 0

    source_ids = set(source_signal_ids or [])
    now = datetime.now(timezone.utc).isoformat()
    updated = 0

    for path in all_partition_paths(signal_dir):
        entries = read_jsonl(path)
        changed = False
        for signal in entries:
            # Only consumed signals (absorbed into this entity) react to its
            # terminal outcome — done keeps consumed (no-op), cancelled/error reopens.
            if signal.get("deleted") or signal.get("status") != "consumed":
                continue
            linked_by_entity = signal.get(link_field) == entity_id
            linked_by_source = signal.get("signal_id") in source_ids
            if not (linked_by_entity or linked_by_source):
                continue
            if signal.get("status") == next_status:
                continue
            signal["status"] = next_status
            signal.setdefault("history", []).append({
                "ts": now,
                "status": next_status,
                "by": by,
                "note": f"linked {entity_type} {entity_id} {entity_status}",
            })
            changed = True
            updated += 1
        if changed:
            write_jsonl(path, entries)

    return updated
