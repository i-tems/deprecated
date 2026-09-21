"""hive-repo NFS sync 의 _sync_tree — mirror(prune)·copy·codex 경로 회귀.

근거(INFRA-ISSUE-285): ruler 단일 SSOT 이관으로 `.claude/rules/` 가 사라지고 CLAUDE.md
로 inline 됐다. sync 가 prune 하지 않으면 NFS 의 옛 rules/ 가 남아 이중 로드된다. 또
codex worker 용 `.codex/skills` + 루트 `AGENTS.md` 를 ~/.codex 로 실어나르는 경로를 추가.
"""

import os
import sys
import types as _types
import tempfile
import unittest
from pathlib import Path

# app.startup 은 `from . import db` 를 끌어온다 — sync 로직 테스트엔 불필요하므로 stub.
if "app.db" not in sys.modules:
    sys.modules["app.db"] = _types.ModuleType("app.db")

from app.startup import _sync_tree  # noqa: E402


def _w(p: Path, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


class SyncTreeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.clone = root / "clone"
        self.target = root / "target"

    def tearDown(self):
        self._tmp.cleanup()

    def test_claude_dirs_and_file_copied(self):
        _w(self.clone / ".claude" / "skills" / "s" / "SKILL.md", "skill")
        _w(self.clone / ".claude" / "CLAUDE.md", "contract")
        _sync_tree(clone=self.clone, target=self.target, dir_src=".claude",
                   dirs=("skills",), file_src=".claude", files=("CLAUDE.md",))
        self.assertEqual((self.target / "skills" / "s" / "SKILL.md").read_text(), "skill")
        self.assertEqual((self.target / "CLAUDE.md").read_text(), "contract")

    def test_prune_removes_stale_dir_absent_in_source(self):
        # 핵심 회귀: target 에 옛 rules 가 있는데 소스엔 없다 → 제거돼야 (이중 로드 방지).
        _w(self.target / "rules" / "old_rule.md", "stale")
        _w(self.clone / ".claude" / "skills" / "s" / "SKILL.md", "skill")
        _sync_tree(clone=self.clone, target=self.target, dir_src=".claude",
                   dirs=("skills", "rules"), file_src=".claude", files=())
        self.assertFalse((self.target / "rules").exists())
        self.assertTrue((self.target / "skills").exists())

    def test_dir_replaced_not_merged(self):
        _w(self.target / "skills" / "gone.md", "old")
        _w(self.clone / ".claude" / "skills" / "new.md", "new")
        _sync_tree(clone=self.clone, target=self.target, dir_src=".claude",
                   dirs=("skills",), file_src=".claude", files=())
        self.assertFalse((self.target / "skills" / "gone.md").exists())
        self.assertTrue((self.target / "skills" / "new.md").exists())

    def test_codex_root_file_and_skills(self):
        # codex 경로: dir_src=.codex, file_src="" (루트 AGENTS.md → ~/.codex/AGENTS.md).
        _w(self.clone / ".codex" / "skills" / "s" / "SKILL.md", "cskill")
        _w(self.clone / "AGENTS.md", "agents")
        _sync_tree(clone=self.clone, target=self.target, dir_src=".codex",
                   dirs=("skills",), file_src="", files=("AGENTS.md",))
        self.assertEqual((self.target / "skills" / "s" / "SKILL.md").read_text(), "cskill")
        self.assertEqual((self.target / "AGENTS.md").read_text(), "agents")

    def test_neutral_root_dirs_copied(self):
        # 중립 계약(specs/schemas): dir_src="" → repo-root 의 dir 를 target 직하로.
        _w(self.clone / "specs" / "model" / "m.md", "spec")
        _w(self.clone / "schemas" / "s.json", "schema")
        _sync_tree(clone=self.clone, target=self.target, dir_src="",
                   dirs=("specs", "schemas"), file_src="", files=())
        self.assertEqual((self.target / "specs" / "model" / "m.md").read_text(), "spec")
        self.assertEqual((self.target / "schemas" / "s.json").read_text(), "schema")

    def test_missing_source_file_skipped(self):
        _sync_tree(clone=self.clone, target=self.target, dir_src=".codex",
                   dirs=(), file_src="", files=("AGENTS.md",))
        self.assertFalse((self.target / "AGENTS.md").exists())

    def test_synced_copy_readonly_and_resyncable(self):
        # INFRA-ISSUE-298: sync 사본은 a-w — 워커가 NFS 런타임 사본을 고쳐 "정본 반영"
        # 으로 위장하는 가짜 done 차단. 재-sync 는 read-only 사본을 스스로 교체해야 한다.
        _w(self.clone / ".claude" / "skills" / "s" / "SKILL.md", "v1")
        _w(self.clone / ".claude" / "CLAUDE.md", "c1")
        _sync_tree(clone=self.clone, target=self.target, dir_src=".claude",
                   dirs=("skills",), file_src=".claude", files=("CLAUDE.md",))
        skill = self.target / "skills" / "s" / "SKILL.md"
        if os.geteuid() != 0:  # root 는 perm 무시 — 차단 단언은 비-root 에서만 유효
            with self.assertRaises(PermissionError):
                skill.write_text("tampered")
            with self.assertRaises(PermissionError):
                (self.target / "CLAUDE.md").write_text("tampered")
            with self.assertRaises(PermissionError):  # 새 파일 주입도 차단 (dir a-w)
                (self.target / "skills" / "inject.md").write_text("inject")
        # 재-sync 가 read-only 사본을 교체 (swap·prune·file replace 전부).
        _w(self.clone / ".claude" / "skills" / "s" / "SKILL.md", "v2")
        _w(self.clone / ".claude" / "CLAUDE.md", "c2")
        _sync_tree(clone=self.clone, target=self.target, dir_src=".claude",
                   dirs=("skills",), file_src=".claude", files=("CLAUDE.md",))
        self.assertEqual(skill.read_text(), "v2")
        self.assertEqual((self.target / "CLAUDE.md").read_text(), "c2")
        # prune 도 read-only 사본에서 동작.
        _sync_tree(clone=self.clone, target=self.target, dir_src=".claude",
                   dirs=("skills", "gone"), file_src=".claude", files=())
        _w(self.target / "probe" / "f.md", "p")  # target 자체는 여전히 쓰기 가능
        self.assertTrue((self.target / "probe" / "f.md").exists())


if __name__ == "__main__":
    unittest.main()
