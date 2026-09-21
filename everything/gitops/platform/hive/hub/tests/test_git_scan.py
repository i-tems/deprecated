"""git_scan.scan_artifacts 단위 테스트.

Gitea API 호출 (_fetch_tree) 과 cells_repo.get 을 monkeypatch 로 대체.
prefix 필터링 / blob URL 생성 / graceful 빈 응답 검증.
"""

import importlib.util
import os
import sys
import types
import unittest


def _setup_stub_package():
    """app_stub.{gitea_mirror, storage.cells_repo} stub 주입 후 git_scan 로드."""
    pkg = types.ModuleType("app_stub2")
    pkg.__path__ = []  # mark as package
    sys.modules["app_stub2"] = pkg

    storage = types.ModuleType("app_stub2.storage")
    storage.__path__ = []
    sys.modules["app_stub2.storage"] = storage

    cells_repo = types.ModuleType("app_stub2.storage.cells_repo")
    cells_repo.get = lambda cell_id: None
    sys.modules["app_stub2.storage.cells_repo"] = cells_repo

    gitea_mirror = types.ModuleType("app_stub2.gitea_mirror")
    gitea_mirror.GITEA_INTERNAL_URL = "http://gitea.test"

    def _parse(repo_url):
        s = (repo_url or "").rstrip("/")
        if s.endswith(".git"):
            s = s[:-4]
        for marker in ("github.com/", "gitea.test/"):
            if marker in s:
                tail = s.split(marker, 1)[1]
                parts = tail.split("/")
                if len(parts) >= 2:
                    return f"{parts[0]}/{parts[1]}"
        return None

    gitea_mirror._gitea_api_owner_repo = _parse
    gitea_mirror._gitea_token = lambda: "test-token"
    sys.modules["app_stub2.gitea_mirror"] = gitea_mirror

    here = os.path.dirname(os.path.abspath(__file__))
    git_scan_path = os.path.normpath(os.path.join(here, "..", "app/git_scan.py"))
    spec = importlib.util.spec_from_file_location("app_stub2.git_scan", git_scan_path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app_stub2"
    sys.modules["app_stub2.git_scan"] = mod
    spec.loader.exec_module(mod)
    return mod, cells_repo


_git_scan, _cells_repo = _setup_stub_package()


class TestBlobUrl(unittest.TestCase):
    def test_github_blob(self):
        self.assertEqual(
            _git_scan._blob_url("https://github.com/foo/bar", "main", "data/projects/G/x.md"),
            "https://github.com/foo/bar/blob/main/data/projects/G/x.md",
        )

    def test_github_blob_strips_dot_git(self):
        self.assertEqual(
            _git_scan._blob_url("https://github.com/foo/bar.git", "main", "data/projects/G/x.md"),
            "https://github.com/foo/bar/blob/main/data/projects/G/x.md",
        )

    def test_gitea_fallback(self):
        self.assertEqual(
            _git_scan._blob_url("https://gitea.test/foo/bar", "main", "data/projects/G/x.md"),
            "https://gitea.test/foo/bar/src/branch/main/data/projects/G/x.md",
        )


class TestScanArtifacts(unittest.TestCase):
    def setUp(self):
        _cells_repo.get = lambda cell_id: None
        self._orig_fetch = _git_scan._fetch_tree

    def tearDown(self):
        _git_scan._fetch_tree = self._orig_fetch

    def test_no_cell_returns_empty(self):
        _cells_repo.get = lambda cell_id: None
        self.assertEqual(_git_scan.scan_artifacts("ghost", "project", "G1"), [])

    def test_no_repo_url_returns_empty(self):
        _cells_repo.get = lambda cell_id: {"cell_id": cell_id, "repo_url": ""}
        self.assertEqual(_git_scan.scan_artifacts("c", "project", "G1"), [])

    def test_filters_by_prefix_and_blob_only(self):
        _cells_repo.get = lambda cell_id: {
            "cell_id": cell_id, "repo_url": "https://github.com/i-tems/cell-x",
        }
        _git_scan._fetch_tree = lambda or_path, branch: [
            {"path": "data/cells/infra/projects/G1/plan.md", "type": "blob", "size": 123, "sha": "aaa"},
            {"path": "data/cells/infra/projects/G1/sub", "type": "tree", "size": 0, "sha": "bbb"},  # dir
            {"path": "data/cells/infra/projects/G1/sub/note.md", "type": "blob", "size": 50, "sha": "ccc"},
            {"path": "data/cells/infra/projects/G2/other.md", "type": "blob", "size": 1, "sha": "ddd"},  # other entity
            {"path": "data/projects/G1/legacy.md", "type": "blob", "size": 1, "sha": "fff"},  # 구 경로 — 더 이상 매칭 안 됨
            {"path": "knowledge/wiki/x.md", "type": "blob", "size": 1, "sha": "eee"},  # outside
        ]
        out = _git_scan.scan_artifacts("infra", "project", "G1")
        paths = [a["path"] for a in out]
        self.assertEqual(paths, ["data/cells/infra/projects/G1/plan.md", "data/cells/infra/projects/G1/sub/note.md"])
        self.assertEqual(
            out[0]["blob_url"],
            "https://github.com/i-tems/cell-x/blob/main/data/cells/infra/projects/G1/plan.md",
        )
        self.assertEqual(out[0]["size"], 123)
        self.assertEqual(out[0]["sha"], "aaa")

    def test_empty_tree_returns_empty(self):
        _cells_repo.get = lambda cell_id: {"cell_id": cell_id, "repo_url": "https://github.com/i-tems/cell-x"}
        _git_scan._fetch_tree = lambda or_path, branch: []
        self.assertEqual(_git_scan.scan_artifacts("infra", "project", "G1"), [])

    def test_sorted_by_path(self):
        _cells_repo.get = lambda cell_id: {"cell_id": cell_id, "repo_url": "https://github.com/i-tems/cell-x"}
        _git_scan._fetch_tree = lambda or_path, branch: [
            {"path": "data/cells/infra/issues/T1/z.md", "type": "blob", "size": 1, "sha": "z"},
            {"path": "data/cells/infra/issues/T1/a.md", "type": "blob", "size": 1, "sha": "a"},
            {"path": "data/cells/infra/issues/T1/m.md", "type": "blob", "size": 1, "sha": "m"},
        ]
        out = _git_scan.scan_artifacts("infra", "issue", "T1")
        self.assertEqual([a["path"] for a in out], [
            "data/cells/infra/issues/T1/a.md", "data/cells/infra/issues/T1/m.md", "data/cells/infra/issues/T1/z.md",
        ])


if __name__ == "__main__":
    unittest.main()
