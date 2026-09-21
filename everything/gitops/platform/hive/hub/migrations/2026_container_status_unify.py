"""Data migration: remap Project / Initiative status to the 4-status container model.

Container (Project + Initiative) status model is now
``{backlog, active, done, archive}`` (see ``app/config.py``
``VALID_CONTAINER_STATUSES``). Stored records may still carry legacy worker-style
statuses (``todo``/``running``/``cleanup``/``waiting``/``cancelled``/``error``/
``planned``/``completed``) and, for Initiatives, a legacy ``archived`` flag.
This script folds those onto the new model.

Issue records are an entirely separate 8-status worker model and are NEVER touched.

Storage: entities are stored in the SQL backend (MySQL) as a JSON ``data`` column
per row (``app/storage/sql.py``). The app reads/writes them through the path-shim
``read_entity_file(cp.project_file)`` / ``write_entity_file(...)`` which dispatch to
``list_entities`` / ``replace_all_entities`` on the ``projects`` / ``initiatives``
tables. This script uses those same helpers, so it stays consistent with the app's
own read/write path (and mirrors the app's ``updated_at`` bump on mutation).

The mapping functions ``map_project_status`` and ``map_initiative_record`` are PURE
(no I/O, no app imports) so they are unit-testable in isolation and idempotent.

Usage:
    python -m migrations.2026_container_status_unify            # DRY RUN (default)
    python -m migrations.2026_container_status_unify --apply    # perform writes
    python -m migrations.2026_container_status_unify --cell infra [--apply]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Pure mapping logic — NO app / DB imports here. Unit-testable, side-effect free.
# ---------------------------------------------------------------------------

# Project legacy status -> new container status.
# waiting is handled specially (depends on suggestion label) and is NOT in this table.
_PROJECT_STATUS_MAP = {
    "backlog": "backlog",
    "todo": "active",
    "running": "active",
    "cleanup": "active",
    "done": "done",
    "cancelled": "archive",
    "error": "backlog",
}

# Initiative legacy status -> new container status.
_INITIATIVE_STATUS_MAP = {
    "planned": "backlog",
    "active": "active",
    "completed": "done",
}

# Already-new container statuses are left unchanged (idempotency).
NEW_CONTAINER_STATUSES = {"backlog", "active", "waiting", "done", "archive"}


def map_project_status(record: dict, *, suggestion_label_ids: set | None = None) -> str | None:
    """Compute the new Project status for ``record``, or ``None`` if unchanged.

    Pure: reads only ``record['status']`` and ``record['labels']``. Returns the
    *target* status string when a change is needed, else ``None`` (already in the
    new model, or an unknown status we refuse to touch).

    ``suggestion_label_ids`` is the set of label_ids in this cell whose name is
    "suggestion" (resolved by the runner from the labels table). A ``waiting``
    project carrying any of them is a parked suggestion and maps to ``backlog``;
    a plain ``waiting`` (human-review / blocked-on-human) is KEPT as ``waiting``
    (the container model retains ``waiting``). When ``suggestion_label_ids`` is
    ``None`` (caller could not resolve labels), ``waiting`` is treated as plain -> kept.
    """
    status = record.get("status")

    # `waiting` is retained in the container model. A suggestion-labelled waiting
    # project is a parked proposal -> backlog (launch gate); a plain waiting
    # (blocked on human) stays waiting. Handle before the idempotent check so a
    # suggestion-waiting is re-homed even though `waiting` is itself a new value.
    if status == "waiting":
        labels = record.get("labels") or []
        sug = suggestion_label_ids or set()
        has_suggestion = any(lid in sug for lid in labels)
        return "backlog" if has_suggestion else None

    # Idempotent: already a valid new-model value -> no change.
    if status in NEW_CONTAINER_STATUSES:
        return None

    new = _PROJECT_STATUS_MAP.get(status)
    if new is None:
        # Unknown / unmapped status — be defensive, do not touch.
        return None
    return new if new != status else None


def map_initiative_record(record: dict) -> dict:
    """Compute the changes for an Initiative ``record``.

    Pure: returns a dict describing the mutation, WITHOUT mutating ``record``::

        {
            "status": "<new status>",       # present only if status changes
            "remove_keys": ["archived", "archived_at"],  # keys to delete (archived fold)
        }

    An empty dict means "no change". The ``archived`` flag (if truthy) wins over the
    status mapping: it forces ``status='archive'`` and removal of ``archived`` /
    ``archived_at``. The ``deleted`` flag is orthogonal retention and is NEVER touched.
    Already-new statuses with no ``archived`` flag yield no change (idempotency).
    """
    changes: dict = {}
    status = record.get("status")

    if record.get("archived"):
        # archived flag wins regardless of prior status; fold into status='archive'
        # and drop the legacy flag keys.
        if status != "archive":
            changes["status"] = "archive"
        remove = [k for k in ("archived", "archived_at") if k in record]
        if remove:
            changes["remove_keys"] = remove
        return changes

    # No archived flag — plain status remap.
    if status in NEW_CONTAINER_STATUSES:
        return {}  # already new model, idempotent no-op
    new = _INITIATIVE_STATUS_MAP.get(status)
    if new is None:
        return {}  # unknown / unmapped — defensive, do not touch
    if new != status:
        changes["status"] = new
    return changes


# ---------------------------------------------------------------------------
# Runner — uses the hub's own storage helpers (deferred imports to keep the
# pure functions above importable without app/DB runtime deps).
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _list_cells():
    """All non-deleted cell ids (matches app's cell enumeration)."""
    from app.storage import cells_repo
    out = []
    for c in cells_repo.list_all():
        cid = c.get("cell_id")
        if cid:
            out.append(cid)
    return out


def _suggestion_label_ids(cp) -> set:
    """label_ids in this cell whose name == 'suggestion' (case-insensitive)."""
    from app.storage import read_entity_file
    ids = set()
    for lab in read_entity_file(cp.label_file):
        if lab.get("deleted"):
            continue
        if (lab.get("name") or "").strip().lower() == "suggestion":
            lid = lab.get("label_id")
            if lid:
                ids.add(lid)
    return ids


def _migrate_cell(cell_id: str, *, apply: bool) -> dict:
    """Compute (and optionally apply) transitions for one cell.

    Returns {"projects": Counter[(old,new)], "initiatives": Counter[(old,new)]}.
    Initiative archived-fold transitions are recorded as old -> 'archive'.
    """
    from app.config import CellPaths
    from app.storage import read_entity_file, write_entity_file

    cp = CellPaths(cell_id)
    result = {"projects": Counter(), "initiatives": Counter()}

    # ---- Projects ----
    sug_ids = _suggestion_label_ids(cp)
    proj_entries = read_entity_file(cp.project_file)
    proj_dirty = False
    for rec in proj_entries:
        new = map_project_status(rec, suggestion_label_ids=sug_ids)
        if new is None:
            continue
        old = rec.get("status")
        result["projects"][(old, new)] += 1
        if apply:
            rec["status"] = new
            rec["updated_at"] = _now_iso()
            proj_dirty = True
    if apply and proj_dirty:
        write_entity_file(cp.project_file, proj_entries)

    # ---- Initiatives ----
    init_entries = read_entity_file(cp.initiative_file)
    init_dirty = False
    for rec in init_entries:
        changes = map_initiative_record(rec)
        if not changes:
            continue
        old = rec.get("status")
        new = changes.get("status", old)
        result["initiatives"][(old, new)] += 1
        if apply:
            if "status" in changes:
                rec["status"] = changes["status"]
            for k in changes.get("remove_keys", []):
                rec.pop(k, None)
            rec["updated_at"] = _now_iso()
            init_dirty = True
    if apply and init_dirty:
        write_entity_file(cp.initiative_file, init_entries)

    return result


def _print_table(cell_id: str, kind: str, counter: Counter) -> int:
    total = sum(counter.values())
    if total == 0:
        print(f"  [{cell_id}] {kind}: no transitions")
        return 0
    print(f"  [{cell_id}] {kind}: {total} transition(s)")
    for (old, new), n in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"      {str(old):>10} -> {str(new):<8}  x{n}")
    return total


def run(cells: list[str], *, apply: bool) -> int:
    grand_total = 0
    grand_proj = Counter()
    grand_init = Counter()

    mode = "APPLY" if apply else "DRY RUN"
    print(f"=== container status unify migration ({mode}) ===")
    for cell_id in cells:
        res = _migrate_cell(cell_id, apply=apply)
        grand_total += _print_table(cell_id, "projects", res["projects"])
        grand_total += _print_table(cell_id, "initiatives", res["initiatives"])
        grand_proj.update(res["projects"])
        grand_init.update(res["initiatives"])

    print("--- totals across all cells ---")
    p_total = sum(grand_proj.values())
    i_total = sum(grand_init.values())
    print(f"  projects:    {p_total} transition(s)")
    for (old, new), n in sorted(grand_proj.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"      {str(old):>10} -> {str(new):<8}  x{n}")
    print(f"  initiatives: {i_total} transition(s)")
    for (old, new), n in sorted(grand_init.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"      {str(old):>10} -> {str(new):<8}  x{n}")
    print(f"  GRAND TOTAL: {grand_total} record(s) to change")

    if not apply:
        print()
        print("DRY RUN — no changes written. Re-run with --apply to execute.")
    else:
        print()
        print(f"APPLIED — {grand_total} record(s) updated.")
    return grand_total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remap Project/Initiative status to the 4-status container model.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="perform writes (default is dry-run, writes nothing)")
    parser.add_argument("--cell", default=None,
                        help="limit migration to a single cell id")
    args = parser.parse_args(argv)

    if args.cell:
        cells = [args.cell]
    else:
        cells = _list_cells()
    if not cells:
        print("no cells found — nothing to do.")
        return 0

    run(cells, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
