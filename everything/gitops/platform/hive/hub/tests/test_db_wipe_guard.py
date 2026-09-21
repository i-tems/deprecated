"""INFRA-ISSUE-321 — id-scheme wipe 가드 회귀 테스트.

`_maybe_wipe_for_id_scheme` 는 entity_seq 부재를 "신 ID 체계 최초 적용" sentinel 로
보고 엔티티 테이블 7개를 DROP 한다. entity_seq 만 비정상 유실되고 엔티티 테이블은
살아있는 상태에선 live 데이터를 비가역 소실시키는 footgun이었다.

DROP 판단을 순수 함수 `_should_wipe_for_id_scheme` 로 분리했으므로 MySQL 없이
판단 매트릭스를 검증한다 (실 DROP 실행 경로는 배포 시 검증).
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


_db = _load("db_under_test", "app/db.py")
_should = _db._should_wipe_for_id_scheme


class WipeGuardTest(unittest.TestCase):
    def test_entity_seq_present_never_wipes(self):
        # 평시 — sentinel 존재면 populated/force 무관하게 no-op.
        self.assertFalse(_should(entity_seq_exists=True, populated_tables=[], force=False))
        self.assertFalse(_should(entity_seq_exists=True, populated_tables=["issues"], force=True))

    def test_fresh_install_wipes(self):
        # 신규 설치 — sentinel 부재 + 빈 테이블 → DROP IF EXISTS no-op 라 무해, 진행.
        self.assertTrue(_should(entity_seq_exists=False, populated_tables=[], force=False))

    def test_populated_without_force_is_preserved(self):
        # 버그 재현 — entity_seq 만 유실, 엔티티 테이블엔 데이터. wipe 차단(보존)되어야.
        self.assertFalse(
            _should(entity_seq_exists=False, populated_tables=["issues", "events"], force=False)
        )

    def test_populated_with_force_wipes(self):
        # 의도된 ID 체계 재전환 — 명시 override 면 populated 여도 진행.
        self.assertTrue(
            _should(entity_seq_exists=False, populated_tables=["issues"], force=True)
        )

    def test_empty_with_force_wipes(self):
        self.assertTrue(_should(entity_seq_exists=False, populated_tables=[], force=True))


if __name__ == "__main__":
    unittest.main()
