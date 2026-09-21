"""normalize_resources dedup + space-uri 경고 검증.

uri.py 만 importlib 로 로드 (DATA_DIR env 만 세팅, config 의 fastapi 의존 회피).
"""

import importlib.util
import logging
import logging.handlers
import os
import sys
import unittest


def _load(name: str, rel_path: str):
    here = os.path.dirname(os.path.abspath(__file__))
    full = os.path.normpath(os.path.join(here, "..", rel_path))
    spec = importlib.util.spec_from_file_location(name, full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


os.environ.setdefault("DATA_DIR", "/tmp/test-data")
# config import 부담 회피: config 의 일부만 패키지 컨텍스트 없이 로드 불가하므로
# uri.py 의 의존을 직접 만족하는 stub 패키지를 sys.modules 에 주입한다.
_stub = type(sys)("app_stub")
_stub_config = type(sys)("app_stub.config")
import pathlib
_stub_config.DATA_DIR = pathlib.Path(os.environ["DATA_DIR"])
sys.modules["app_stub"] = _stub
sys.modules["app_stub.config"] = _stub_config

_uri_spec = importlib.util.spec_from_file_location(
    "app_stub.uri",
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app/uri.py")),
)
_uri = importlib.util.module_from_spec(_uri_spec)
sys.modules["app_stub.uri"] = _uri
# uri.py 의 `from .config import DATA_DIR` → app_stub.config 로 해석되도록 package 지정
_uri.__package__ = "app_stub"
_uri_spec.loader.exec_module(_uri)


class TestNormalizeResourceUri(unittest.TestCase):
    def test_strips_data_dir_prefix(self):
        self.assertEqual(
            _uri.normalize_resource_uri("/tmp/test-data/cells/infra/foo.md"),
            "data/cells/infra/foo.md",
        )

    def test_external_url_unchanged(self):
        url = "https://example.com/page"
        self.assertEqual(_uri.normalize_resource_uri(url), url)


class TestNormalizeResourcesDedup(unittest.TestCase):
    def test_keeps_first_drops_duplicate(self):
        items = [
            {"uri": "https://a.com", "label": "first"},
            {"uri": "https://b.com", "label": "b"},
            {"uri": "https://a.com", "label": "second-same-uri"},
        ]
        out = _uri.normalize_resources(items)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["label"], "first")
        self.assertEqual(out[1]["label"], "b")

    def test_keeps_unique(self):
        items = [
            {"uri": "https://a.com", "label": "a"},
            {"uri": "https://b.com", "label": "b"},
        ]
        out = _uri.normalize_resources(items)
        self.assertEqual(len(out), 2)

    def test_assigns_created_at_when_missing(self):
        items = [{"uri": "https://a.com", "label": "a"}]
        out = _uri.normalize_resources(items)
        self.assertIn("created_at", out[0])
        self.assertTrue(out[0]["created_at"])

    def test_preserves_created_at_when_present(self):
        items = [{"uri": "https://a.com", "label": "a", "created_at": "2020-01-01T00:00:00+00:00"}]
        out = _uri.normalize_resources(items)
        self.assertEqual(out[0]["created_at"], "2020-01-01T00:00:00+00:00")

    def test_item_without_uri_kept(self):
        items = [{"label": "no-uri"}]
        out = _uri.normalize_resources(items)
        self.assertEqual(len(out), 1)


class TestSpaceUriWarning(unittest.TestCase):
    def test_warns_on_space_path(self):
        with self.assertLogs("hub.uri", level="WARNING") as cm:
            _uri.normalize_resources([{"uri": "data/cells/infra/projects/X/plan.md", "label": "x"}])
        self.assertTrue(any("space-internal path" in msg for msg in cm.output))

    def test_warns_on_entity_branch_blob(self):
        with self.assertLogs("hub.uri", level="WARNING") as cm:
            _uri.normalize_resources([
                {"uri": "https://github.com/owner/repo/blob/issue/X/data/issues/X/p.md", "label": "x"},
            ])
        self.assertTrue(any("entity-branch blob URL" in msg for msg in cm.output))

    def test_no_warning_on_external_url(self):
        # Capturing absence: setLevel WARNING, expect no record from hub.uri
        logger = logging.getLogger("hub.uri")
        handler = logging.handlers.MemoryHandler(capacity=100)
        logger.addHandler(handler)
        try:
            _uri.normalize_resources([{"uri": "https://example.com/page", "label": "x"}])
            self.assertFalse(any(
                ("space-internal" in r.getMessage()) or ("entity-branch" in r.getMessage())
                for r in handler.buffer
            ))
        finally:
            logger.removeHandler(handler)


if __name__ == "__main__":
    # logging.handlers import (MemoryHandler) 는 모듈 명시 로드 필요
    import logging.handlers  # noqa: F401
    unittest.main()
