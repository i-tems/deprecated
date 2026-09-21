"""idgen 순수 로직 검증 (DB 의존 없는 부분).

canonical id `<CELL>-<TYPE>-<SEQ>` 합성 규칙·cell 정규화·미지 타입 거부.
alloc_seq/new_entity_id 는 MySQL 의존이라 여기서 다루지 않는다 (배포 시 검증).
"""

import importlib.util
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


_idgen = _load("idgen_under_test", "app/storage/idgen.py")


class TestMakeEntityId(unittest.TestCase):
    def test_basic_format(self):
        self.assertEqual(_idgen.make_entity_id("items", "issue", 302), "ITEMS-ISSUE-302")

    def test_cell_uppercased_kebab_preserved(self):
        self.assertEqual(
            _idgen.make_entity_id("acme-corp", "project", 1), "ACME-CORP-PROJECT-1"
        )

    def test_all_entity_types_have_tag(self):
        for et in ("project", "issue", "signal", "label", "event", "action", "inbox", "initiative"):
            self.assertRegex(
                _idgen.make_entity_id("c", et, 5), rf"^C-[A-Z_]+-5$"
            )

    def test_initiative_tag_format(self):
        self.assertEqual(_idgen.make_entity_id("items", "initiative", 1), "ITEMS-INITIATIVE-1")

    def test_none_cell_is_global_scope(self):
        self.assertEqual(_idgen.make_entity_id(None, "event", 9), "GLOBAL-EVENT-9")

    def test_empty_cell_is_global_scope(self):
        self.assertEqual(_idgen.make_entity_id("  ", "inbox", 2), "GLOBAL-INBOX-2")


class TestUnknownType(unittest.TestCase):
    def test_alloc_seq_rejects_unknown_type_before_db(self):
        # 미지 타입은 DB 접근 전에 ValueError — get_engine import 도 안 탄다.
        with self.assertRaises(ValueError):
            _idgen.alloc_seq("items", "widget")


if __name__ == "__main__":
    unittest.main()
