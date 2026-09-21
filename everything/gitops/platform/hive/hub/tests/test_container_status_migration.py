"""Unit tests for the container status unify migration's pure mapping logic.

The migration module name begins with a digit (``2026_...``) so it cannot be a
normal ``import`` target; we load it by file path via importlib. Only the PURE
functions (``map_project_status`` / ``map_initiative_record``) are exercised —
they have no app/DB dependency, so this runs without a live backend.

Every mapping branch is covered, plus the two tricky cases (waiting+suggestion vs
waiting-plain, archived-flag-wins) and idempotency (applying the map twice is a
no-op).
"""

import importlib.util
import unittest
from pathlib import Path

_MIG_PATH = Path(__file__).resolve().parents[1] / "migrations" / "2026_container_status_unify.py"
_spec = importlib.util.spec_from_file_location("container_status_unify", _MIG_PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

SUG = {"lab_suggestion"}  # pretend this label_id is the cell's "suggestion" label


def apply_project(record, *, suggestion=SUG):
    """Emulate the runner's apply step for a project so we can re-feed the result."""
    new = mig.map_project_status(record, suggestion_label_ids=suggestion)
    out = dict(record)
    if new is not None:
        out["status"] = new
    return out


def apply_initiative(record):
    """Emulate the runner's apply step for an initiative."""
    changes = mig.map_initiative_record(record)
    out = dict(record)
    if "status" in changes:
        out["status"] = changes["status"]
    for k in changes.get("remove_keys", []):
        out.pop(k, None)
    return out


class ProjectMappingTests(unittest.TestCase):
    def test_backlog_unchanged(self):
        self.assertIsNone(mig.map_project_status({"status": "backlog"}))

    def test_todo_to_active(self):
        self.assertEqual(mig.map_project_status({"status": "todo"}), "active")

    def test_running_to_active(self):
        self.assertEqual(mig.map_project_status({"status": "running"}), "active")

    def test_cleanup_to_active(self):
        self.assertEqual(mig.map_project_status({"status": "cleanup"}), "active")

    def test_done_unchanged(self):
        self.assertIsNone(mig.map_project_status({"status": "done"}))

    def test_cancelled_to_archive(self):
        self.assertEqual(mig.map_project_status({"status": "cancelled"}), "archive")

    def test_error_to_backlog(self):
        self.assertEqual(mig.map_project_status({"status": "error"}), "backlog")

    def test_waiting_with_suggestion_to_backlog(self):
        rec = {"status": "waiting", "labels": ["lab_x", "lab_suggestion"]}
        self.assertEqual(mig.map_project_status(rec, suggestion_label_ids=SUG), "backlog")

    def test_waiting_without_suggestion_kept(self):
        # plain waiting (blocked on human) is retained in the container model -> no change
        rec = {"status": "waiting", "labels": ["lab_x"]}
        self.assertIsNone(mig.map_project_status(rec, suggestion_label_ids=SUG))

    def test_waiting_no_labels_kept(self):
        rec = {"status": "waiting"}
        self.assertIsNone(mig.map_project_status(rec, suggestion_label_ids=SUG))

    def test_waiting_no_suggestion_set_treated_as_plain_kept(self):
        # suggestion_label_ids=None -> waiting treated as plain -> kept (None)
        rec = {"status": "waiting", "labels": ["lab_suggestion"]}
        self.assertIsNone(mig.map_project_status(rec))

    def test_already_active_unchanged(self):
        self.assertIsNone(mig.map_project_status({"status": "active"}))

    def test_already_archive_unchanged(self):
        self.assertIsNone(mig.map_project_status({"status": "archive"}))

    def test_unknown_status_untouched(self):
        self.assertIsNone(mig.map_project_status({"status": "weird"}))

    def test_idempotent_all_branches(self):
        for status, labels in [
            ("todo", []), ("running", []), ("cleanup", []),
            ("cancelled", []), ("error", []),
            ("waiting", ["lab_suggestion"]), ("waiting", ["lab_x"]),
            ("backlog", []), ("done", []),
        ]:
            rec = {"status": status, "labels": labels}
            once = apply_project(rec)
            twice = apply_project(once)
            self.assertEqual(once["status"], twice["status"], f"not idempotent for {status}/{labels}")
            # second pass must report no change
            self.assertIsNone(mig.map_project_status(once, suggestion_label_ids=SUG),
                              f"second pass should be no-op for {status}/{labels}")


class InitiativeMappingTests(unittest.TestCase):
    def test_planned_to_backlog(self):
        self.assertEqual(mig.map_initiative_record({"status": "planned"}), {"status": "backlog"})

    def test_active_unchanged(self):
        self.assertEqual(mig.map_initiative_record({"status": "active"}), {})

    def test_completed_to_done(self):
        self.assertEqual(mig.map_initiative_record({"status": "completed"}), {"status": "done"})

    def test_archived_flag_wins_over_status(self):
        rec = {"status": "active", "archived": True, "archived_at": "2026-01-01T00:00:00Z"}
        changes = mig.map_initiative_record(rec)
        self.assertEqual(changes["status"], "archive")
        self.assertEqual(set(changes["remove_keys"]), {"archived", "archived_at"})

    def test_archived_flag_wins_over_completed(self):
        rec = {"status": "completed", "archived": True}
        changes = mig.map_initiative_record(rec)
        self.assertEqual(changes["status"], "archive")
        self.assertEqual(changes["remove_keys"], ["archived"])

    def test_archived_flag_already_archive_status_just_drops_keys(self):
        rec = {"status": "archive", "archived": True, "archived_at": "x"}
        changes = mig.map_initiative_record(rec)
        self.assertNotIn("status", changes)  # status already archive
        self.assertEqual(set(changes["remove_keys"]), {"archived", "archived_at"})

    def test_deleted_flag_untouched(self):
        # deleted is orthogonal — never appears in remove_keys, never blocks mapping.
        rec = {"status": "planned", "deleted": True, "deleted_at": "x"}
        changes = mig.map_initiative_record(rec)
        self.assertEqual(changes, {"status": "backlog"})
        out = apply_initiative(rec)
        self.assertTrue(out["deleted"])
        self.assertEqual(out["deleted_at"], "x")

    def test_already_new_unchanged(self):
        for s in ("backlog", "done", "archive"):
            self.assertEqual(mig.map_initiative_record({"status": s}), {})

    def test_unknown_status_untouched(self):
        self.assertEqual(mig.map_initiative_record({"status": "weird"}), {})

    def test_idempotent_all_branches(self):
        cases = [
            {"status": "planned"},
            {"status": "active"},
            {"status": "completed"},
            {"status": "active", "archived": True, "archived_at": "x"},
            {"status": "completed", "archived": True},
            {"status": "backlog"},
            {"status": "done"},
            {"status": "archive"},
        ]
        for rec in cases:
            once = apply_initiative(rec)
            twice = apply_initiative(once)
            self.assertEqual(once, twice, f"not idempotent for {rec}")
            self.assertEqual(mig.map_initiative_record(once), {}, f"second pass not no-op for {rec}")
            # archived flag must be gone after one pass when it was set
            if rec.get("archived"):
                self.assertNotIn("archived", once)
                self.assertNotIn("archived_at", once)
                self.assertEqual(once["status"], "archive")


if __name__ == "__main__":
    unittest.main()
