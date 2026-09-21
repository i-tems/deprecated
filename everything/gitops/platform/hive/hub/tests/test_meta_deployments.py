"""meta_deployments.scan_deployments 단위 테스트.

cells_repo.get 와 _fetch_apps 를 monkeypatch 로 대체.
repo/app/branch 필터링 + reachable host(prd=host, 비운영=tunnelHost, 없으면 skip) 검증.
"""

import importlib.util
import os
import sys
import types
import unittest


def _setup():
    pkg = types.ModuleType("app_stubmd")
    pkg.__path__ = []
    sys.modules["app_stubmd"] = pkg
    storage = types.ModuleType("app_stubmd.storage")
    storage.__path__ = []
    sys.modules["app_stubmd.storage"] = storage
    cells_repo = types.ModuleType("app_stubmd.storage.cells_repo")
    cells_repo.get = lambda cell_id: None
    sys.modules["app_stubmd.storage.cells_repo"] = cells_repo

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(here, "..", "app/meta_deployments.py"))
    spec = importlib.util.spec_from_file_location("app_stubmd.meta_deployments", path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app_stubmd"
    sys.modules["app_stubmd.meta_deployments"] = mod
    spec.loader.exec_module(mod)
    return mod, cells_repo


_md, _cells = _setup()


def _app(app, env, repo, branch, host=None, tunnel=None, phase="Ready"):
    spec = {}
    if host:
        spec["host"] = host
    if tunnel:
        spec["tunnelHost"] = tunnel
    return {
        "metadata": {"labels": {
            "meta.i-tems.com/app": app,
            "meta.i-tems.com/env": env,
            "meta.i-tems.com/source-repo": repo,
            "meta.i-tems.com/source-branch": branch,
        }},
        "spec": spec,
        "status": {"phase": phase},
    }


class TestScanDeployments(unittest.TestCase):
    def setUp(self):
        _cells.get = lambda cell_id: {"cell_id": cell_id, "repo_url": "https://github.com/i-tems/cell-items"}
        self._orig = _md._fetch_apps

    def tearDown(self):
        _md._fetch_apps = self._orig

    def test_no_selector_returns_empty_without_fetch(self):
        def boom():
            raise AssertionError("should not fetch")
        _md._fetch_apps = boom
        self.assertEqual(_md.scan_deployments("items"), [])

    def test_no_cell_returns_empty(self):
        _cells.get = lambda cell_id: None
        _md._fetch_apps = lambda: [_app("x", "prd", "i-tems/cell-items", "main", host="x.i-tems.com")]
        self.assertEqual(_md.scan_deployments("items", app_names=["x"]), [])

    def test_project_apps_prd_uses_host_dev_uses_tunnel(self):
        _md._fetch_apps = lambda: [
            _app("sts2-wiki", "prd", "i-tems/cell-items", "main",
                 host="sts2-wiki.i-tems.com"),
            _app("sts2-wiki", "dev", "i-tems/cell-items", "main",
                 host="sts2-wiki-dev.lab.i-tems.com", tunnel="sts2-wiki-dev.tunnel.i-tems.com"),
        ]
        out = _md.scan_deployments("items", app_names=["sts2-wiki"])
        self.assertEqual(out, [
            {"app": "sts2-wiki", "env": "dev", "url": "https://sts2-wiki-dev.tunnel.i-tems.com", "phase": "Ready"},
            {"app": "sts2-wiki", "env": "prd", "url": "https://sts2-wiki.i-tems.com", "phase": "Ready"},
        ])

    def test_non_prd_without_tunnel_skipped(self):
        _md._fetch_apps = lambda: [
            _app("a", "dev", "i-tems/cell-items", "main", host="a-dev.lab.i-tems.com"),  # tunnel 없음
        ]
        self.assertEqual(_md.scan_deployments("items", app_names=["a"]), [])

    def test_repo_mismatch_excluded(self):
        _md._fetch_apps = lambda: [
            _app("a", "prd", "i-tems/cell-beauty", "main", host="a.i-tems.com"),
        ]
        self.assertEqual(_md.scan_deployments("items", app_names=["a"]), [])

    def test_issue_branch_match(self):
        _md._fetch_apps = lambda: [
            _app("sts2-wiki", "preview", "i-tems/cell-items", "issue/ITEMS-ISSUE-9",
                 host="sts2-wiki-issue-9.lab.i-tems.com", tunnel="sts2-wiki-issue-9.tunnel.i-tems.com"),
            _app("sts2-wiki", "preview", "i-tems/cell-items", "issue/ITEMS-ISSUE-7",
                 host="x.lab.i-tems.com", tunnel="x.tunnel.i-tems.com"),
        ]
        out = _md.scan_deployments("items", issue_branch="issue/ITEMS-ISSUE-9")
        self.assertEqual([d["url"] for d in out], ["https://sts2-wiki-issue-9.tunnel.i-tems.com"])


class TestPreviewReadiness(unittest.TestCase):
    def setUp(self):
        _cells.get = lambda cell_id: {"cell_id": cell_id, "repo_url": "https://github.com/i-tems/cell-items"}
        self._orig = _md._fetch_apps_checked

    def tearDown(self):
        _md._fetch_apps_checked = self._orig

    def test_ready_when_matching_app_phase_ready(self):
        _md._fetch_apps_checked = lambda: (True, [
            _app("lucky-defense", "preview", "i-tems/cell-items", "issue/ITEMS-ISSUE-48",
                 host="x.lab.i-tems.com", tunnel="x.tunnel.i-tems.com", phase="Ready"),
        ])
        state, matched = _md.preview_readiness("items", "issue/ITEMS-ISSUE-48")
        self.assertEqual(state, "ready")
        self.assertEqual(len(matched), 1)

    def test_absent_when_no_matching_app(self):
        # 빌드 실패로 App 미생성 — 다른 브랜치 App 만 존재
        _md._fetch_apps_checked = lambda: (True, [
            _app("lucky-defense", "preview", "i-tems/cell-items", "issue/ITEMS-ISSUE-7",
                 tunnel="x.tunnel.i-tems.com"),
        ])
        state, matched = _md.preview_readiness("items", "issue/ITEMS-ISSUE-48")
        self.assertEqual(state, "absent")
        self.assertEqual(matched, [])

    def test_not_ready_when_phase_not_ready(self):
        _md._fetch_apps_checked = lambda: (True, [
            _app("lucky-defense", "preview", "i-tems/cell-items", "issue/ITEMS-ISSUE-48",
                 tunnel="x.tunnel.i-tems.com", phase="Progressing"),
        ])
        state, matched = _md.preview_readiness("items", "issue/ITEMS-ISSUE-48")
        self.assertEqual(state, "not_ready")
        self.assertEqual(matched[0]["phase"], "Progressing")

    def test_not_ready_counts_app_without_tunnel(self):
        # 배포 중이라 tunnelHost 아직 없는 변형도 phase 판정에 포함 (scan 의 url 필터 미적용)
        _md._fetch_apps_checked = lambda: (True, [
            _app("lucky-defense", "preview", "i-tems/cell-items", "issue/ITEMS-ISSUE-48",
                 phase="Progressing"),
        ])
        state, matched = _md.preview_readiness("items", "issue/ITEMS-ISSUE-48")
        self.assertEqual(state, "not_ready")
        self.assertEqual(len(matched), 1)

    def test_meta_unreachable_distinguished_from_absent(self):
        _md._fetch_apps_checked = lambda: (False, [])
        state, matched = _md.preview_readiness("items", "issue/ITEMS-ISSUE-48")
        self.assertEqual(state, "meta_unreachable")
        self.assertEqual(matched, [])

    def test_repo_mismatch_is_absent(self):
        _md._fetch_apps_checked = lambda: (True, [
            _app("lucky-defense", "preview", "i-tems/cell-beauty", "issue/ITEMS-ISSUE-48",
                 tunnel="x.tunnel.i-tems.com"),
        ])
        state, _ = _md.preview_readiness("items", "issue/ITEMS-ISSUE-48")
        self.assertEqual(state, "absent")


if __name__ == "__main__":
    unittest.main()
