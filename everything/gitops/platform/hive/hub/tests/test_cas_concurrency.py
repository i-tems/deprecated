"""INFRA-ISSUE-284 — entity 쓰기 optimistic CAS 동시성 회귀 테스트.

cas_update_entity 가 cross-pod(여기선 cross-thread, 같은 엔진/DB) 동시 read-modify-write
에서 lost-update 를 막는지 실제 MySQL 로 검증한다. 두 스레드가 같은 엔티티의 counter 를
각각 N 회 증가 → CAS 가 맞으면 최종 counter==2N (충돌은 재read+재apply 로 흡수), 틀리면
(무조건 덮어쓰기면) 2N 미만.

실 DB 필요 — `CAS_DB_TEST=1` + DB_* 환경에서만 실행, 그 외엔 skip (격리/CI 런 비파괴).
실행: mysql 컨테이너 + hub 이미지에서
  CAS_DB_TEST=1 DB_HOST=... python3 -m pytest tests/test_cas_concurrency.py -q
"""

import os
import threading
import unittest

_ENABLED = os.environ.get("CAS_DB_TEST") == "1"


@unittest.skipUnless(_ENABLED, "needs MySQL (set CAS_DB_TEST=1 + DB_* env)")
class CASConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.db import get_engine
        from sqlalchemy import text
        cls.eng = get_engine()
        with cls.eng.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS issues"))
            conn.execute(text(
                "CREATE TABLE issues ("
                "  cell_id VARCHAR(64) NOT NULL,"
                "  issue_id VARCHAR(64) NOT NULL,"
                "  seq BIGINT NULL,"
                "  data JSON NOT NULL,"
                "  status VARCHAR(32) AS (JSON_UNQUOTE(JSON_EXTRACT(data,'$.status'))) STORED,"
                "  deleted TINYINT(1) AS (CASE WHEN JSON_EXTRACT(data,'$.deleted') IS NULL THEN 0"
                "    WHEN JSON_EXTRACT(data,'$.deleted')=CAST('false' AS JSON) THEN 0 ELSE 1 END) STORED,"
                "  updated_at VARCHAR(64) AS (JSON_UNQUOTE(JSON_EXTRACT(data,'$.updated_at'))) STORED,"
                "  PRIMARY KEY (cell_id, issue_id)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            ))

    def _seed(self, eid):
        from app.storage.sql import upsert_entity
        upsert_entity("issues", "issue_id", "t", {"issue_id": eid, "status": "todo", "counter": 0})

    def test_concurrent_same_entity_no_lost_update(self):
        from app.storage.sql import cas_update_entity, get_entity
        eid = "T-ISSUE-1"
        self._seed(eid)
        N, THREADS = 50, 2

        from app.storage.sql import CASConflict

        def bump_n():
            for _ in range(N):
                def apply(fresh):
                    fresh = dict(fresh)
                    fresh["counter"] = int(fresh.get("counter", 0)) + 1
                    return (True, fresh)
                # 병적 경합(2스레드 tight loop)으로 retry budget 초과 시 CASConflict —
                # production 계약대로 caller 가 재시도(concurrent_modification → re-fetch).
                # CAS 정합성(lost-update 0)은 결국 모든 증가가 반영됨으로 증명된다.
                while True:
                    try:
                        cas_update_entity("issues", "issue_id", "t", eid, apply)
                        break
                    except CASConflict:
                        continue

        ts = [threading.Thread(target=bump_n) for _ in range(THREADS)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=60)

        final = get_entity("issues", "issue_id", "t", eid)
        self.assertEqual(
            int(final["counter"]), N * THREADS,
            f"lost update: counter={final.get('counter')} != {N*THREADS} (rev={final.get('rev')})",
        )
        # rev 는 성공한 쓰기 수만큼 증가 (충돌 재시도 포함하지 않은 순 성공 수 == 2N).
        self.assertEqual(int(final["rev"]), N * THREADS)

    def test_conflict_detection_rowcount(self):
        """stale rev 로 쓰면 0 row (충돌), 정확한 rev 면 1 row."""
        from app.storage.sql import cas_write_entity, get_entity, upsert_entity
        eid = "T-ISSUE-2"
        upsert_entity("issues", "issue_id", "t", {"issue_id": eid, "status": "todo", "rev": 5})
        cur = get_entity("issues", "issue_id", "t", eid)
        self.assertEqual(int(cur["rev"]), 5)
        # 맞는 rev → 성공
        self.assertTrue(cas_write_entity("issues", "issue_id", "t", eid, {**cur, "status": "running", "rev": 6}, 5))
        # 옛 rev(5) 재시도 → 충돌(이미 6)
        self.assertFalse(cas_write_entity("issues", "issue_id", "t", eid, {**cur, "status": "x", "rev": 6}, 5))


@unittest.skipUnless(_ENABLED, "needs MySQL (set CAS_DB_TEST=1 + DB_* env)")
class ConvertedHandlerE2ETest(unittest.TestCase):
    """변환된 issue.update 경로(apply_entity_fields_and_persist)를 실 MySQL 로 end-to-end 검증.

    route handler 의 entity_lock 없이 apply_entity_fields_and_persist 를 직접 두 스레드로
    호출 = cross-pod(락 없는 동시 쓰기) 시나리오. CAS 가 맞으면 서로 다른 필드를 쓰는 두
    writer 가 둘 다 반영되고(lost-update 0) rev==총쓰기수.
    """
    @classmethod
    def setUpClass(cls):
        from app.db import init_schema
        init_schema()

    def _req(self, **over):
        import types
        base = dict(
            issue_id=None, status=None, title=None, description=None,
            plan=None, owner=None, capability=None, model=None, priority=None,
            clear_priority=False, resources=None, apps=None, gates=None, metadata=None,
            hold=None, source_signal_ids=None, initiative_id=None, labels=None,
            dependencies=None, remove_dependencies=None,
            comment=None, comment_subtype="transition", comment_payload=None,
        )
        base.update(over)
        return types.SimpleNamespace(**base)

    def _request(self):
        import types
        return types.SimpleNamespace(state=types.SimpleNamespace(session_id=None, principal=None))

    def test_single_update_runs_and_bumps_rev(self):
        from app.storage.sql import upsert_entity, get_entity
        from app.entities import apply_entity_fields_and_persist
        from app.config import CellPaths
        eid = "T-ISSUE-E1"
        upsert_entity("issues", "issue_id", "t", {"issue_id": eid, "status": "todo", "title": "orig"})
        resp = apply_entity_fields_and_persist(
            req=self._req(issue_id=eid, status="running", title="updated", comment="go"),
            request=self._request(), cp=CellPaths("t"), entity_type="issue",
            validate_status=lambda *a: None,
        )
        self.assertEqual(resp.status, "ok")
        row = get_entity("issues", "issue_id", "t", eid)
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["title"], "updated")
        # rev 는 apply(1) + emit→_touch_entity_activity(comment·status_change 각 1) 로
        # 1회 update 당 여러 번 증가(touch 도 이제 per-entity CAS). >=1 이면 CAS 활성.
        self.assertGreaterEqual(int(row["rev"]), 1)

    def test_concurrent_distinct_fields_no_clobber(self):
        import threading
        from app.storage.sql import upsert_entity, get_entity
        from app.entities import apply_entity_fields_and_persist
        from app.config import CellPaths
        eid = "T-ISSUE-E2"
        upsert_entity("issues", "issue_id", "t", {"issue_id": eid, "status": "todo"})
        N = 30
        cp = CellPaths("t")

        def writer(field):
            for i in range(N):
                apply_entity_fields_and_persist(
                    req=self._req(issue_id=eid, **{field: f"{field}{i}"}),
                    request=self._request(), cp=cp, entity_type="issue",
                    validate_status=lambda *a: None,
                )

        ta = threading.Thread(target=writer, args=("title",))
        tb = threading.Thread(target=writer, args=("description",))
        ta.start(); tb.start(); ta.join(timeout=90); tb.join(timeout=90)

        row = get_entity("issues", "issue_id", "t", eid)
        # 두 writer 의 마지막 값이 모두 살아있어야 (CAS 가 clobber 막음).
        self.assertEqual(row.get("title"), f"title{N-1}", f"title clobbered: {row.get('title')}")
        self.assertEqual(row.get("description"), f"description{N-1}", f"desc clobbered: {row.get('description')}")
        self.assertEqual(int(row["rev"]), 2 * N, "rev != 총 성공 쓰기 수 (lost update)")


@unittest.skipUnless(_ENABLED, "needs MySQL (set CAS_DB_TEST=1 + DB_* env)")
class CasEntityHelperTest(unittest.TestCase):
    """cas_entity 헬퍼 — 변환된 모든 writer(set_session/add_pr/delete/restore/_cascade/
    initiative.*) 가 funnel 하는 단일-entity CAS 경로를 실 MySQL 로 검증."""
    @classmethod
    def setUpClass(cls):
        from app.db import init_schema
        init_schema()

    def test_not_found_returns_none(self):
        from app.entities import cas_entity
        from app.config import CellPaths
        self.assertIsNone(cas_entity(CellPaths("t"), "issue", "NOPE-1", lambda f: None))

    def test_abort_returns_response_no_write(self):
        from app.entities import cas_entity
        from app.config import CellPaths
        from app.storage.sql import upsert_entity, get_entity
        from capability_framework import CapabilityResponse
        eid = "T-ISSUE-H1"
        upsert_entity("issues", "issue_id", "t", {"issue_id": eid, "status": "todo"})
        res = cas_entity(CellPaths("t"), "issue", eid,
                         lambda f: CapabilityResponse(status="error", error_code="nope"))
        self.assertIsInstance(res, CapabilityResponse)
        self.assertEqual(res.error_code, "nope")
        self.assertIsNone(get_entity("issues", "issue_id", "t", eid).get("rev"))  # 쓰기 안 함

    def test_label_table_routing(self):
        """cas_entity 가 entity_type='label' 에서 labels 테이블로 라우팅되는지 (_entity_file 확장)."""
        from app.entities import cas_entity
        from app.config import CellPaths
        from app.storage.sql import upsert_entity, get_entity
        lid = "T-LABEL-1"
        upsert_entity("labels", "label_id", "t", {"label_id": lid, "name": "x", "color": "#fff"})
        res = cas_entity(CellPaths("t"), "label", lid, lambda f: f.__setitem__("color", "#000"))
        self.assertIsInstance(res, dict)
        row = get_entity("labels", "label_id", "t", lid)
        self.assertEqual(row["color"], "#000")
        self.assertGreaterEqual(int(row["rev"]), 1)

    def test_concurrent_distinct_fields_no_clobber(self):
        import threading
        from app.entities import cas_entity
        from app.config import CellPaths
        from app.storage.sql import upsert_entity, get_entity
        eid = "T-ISSUE-H2"
        upsert_entity("issues", "issue_id", "t", {"issue_id": eid, "status": "todo"})
        cp = CellPaths("t"); N = 30

        from app.storage.sql import CASConflict

        def writer(field):
            for i in range(N):
                # 병적 경합(락 없는 순수 cross-pod 시뮬레이션) 시 retry budget 초과 →
                # caller 계약대로 재시도. CAS 정합성: 모든 쓰기가 결국 반영(clobber 0).
                while True:
                    try:
                        cas_entity(cp, "issue", eid, lambda f, v=f"{field}{i}", k=field: f.__setitem__(k, v))
                        break
                    except CASConflict:
                        continue

        ta = threading.Thread(target=writer, args=("title",))
        tb = threading.Thread(target=writer, args=("description",))
        ta.start(); tb.start(); ta.join(60); tb.join(60)
        row = get_entity("issues", "issue_id", "t", eid)
        self.assertEqual(row.get("title"), f"title{N-1}")
        self.assertEqual(row.get("description"), f"description{N-1}")
        self.assertEqual(int(row["rev"]), 2 * N)


@unittest.skipUnless(_ENABLED, "needs MySQL (set CAS_DB_TEST=1 + DB_* env)")
class HeartbeatStoreTest(unittest.TestCase):
    """worker heartbeat SQL 공유 저장 (INFRA-ISSUE-284) — upsert/list/prune/delete."""
    @classmethod
    def setUpClass(cls):
        from app.db import init_schema
        init_schema()

    def test_upsert_list_prune_delete(self):
        from datetime import datetime, timezone, timedelta
        from app.storage.sql import (
            upsert_heartbeat, get_heartbeat, list_heartbeats, prune_heartbeats, delete_heartbeat,
        )
        now = datetime.now(timezone.utc)
        fresh = now.isoformat()
        stale = (now - timedelta(seconds=120)).isoformat()
        cutoff = (now - timedelta(seconds=30)).isoformat()

        upsert_heartbeat("w-alive", {"worker_id": "w-alive", "cell_id": "t", "started_at": fresh, "last_seen": fresh})
        upsert_heartbeat("w-stale", {"worker_id": "w-stale", "cell_id": "t", "started_at": stale, "last_seen": stale})
        # upsert 재호출 = 갱신 (중복 row 안 생김)
        upsert_heartbeat("w-alive", {"worker_id": "w-alive", "cell_id": "t", "started_at": fresh, "last_seen": fresh, "phase": "run"})

        self.assertEqual(get_heartbeat("w-alive")["phase"], "run")
        alive_ids = {r["worker_id"] for r in list_heartbeats(cutoff)}
        self.assertIn("w-alive", alive_ids)
        self.assertNotIn("w-stale", alive_ids)  # last_seen < cutoff → list 제외

        prune_heartbeats(cutoff)
        self.assertIsNone(get_heartbeat("w-stale"))   # TTL prune
        self.assertIsNotNone(get_heartbeat("w-alive"))

        delete_heartbeat("w-alive")
        self.assertIsNone(get_heartbeat("w-alive"))   # 정상종료 clear


@unittest.skipUnless(_ENABLED, "needs MySQL (set CAS_DB_TEST=1 + DB_* env)")
class RecomputePendingCASTest(unittest.TestCase):
    """INFRA-ISSUE-319 — event._recompute_pending_and_wake 가 셀 전체 재기록이 아니라
    per-entity CAS 로 pending 필드를 갱신해, 같은 셀 형제 엔티티의 동시 쓰기를 덮지 않음.

    옛 경로(write_entity_file=셀 통째 DELETE+INSERT)는 rev 관리를 안 하고 stale 스냅샷으로
    형제 행을 덮었다. 새 경로는 대상 행만 rev-guard UPDATE → rev bump(단일 row) + 형제 무영향.
    """
    @classmethod
    def setUpClass(cls):
        from app.db import init_schema
        init_schema()

    def test_recompute_is_single_entity_cas(self):
        # 결정론: 이벤트 없는(=head_ids 빈) 엔티티의 stale pending 을 recompute 하면 []로
        # 단일 CAS 쓰기 → rev==1. 옛 write_entity_file 은 rev 미관리(=0)라 red.
        from app.storage.sql import upsert_entity, get_entity
        from app.config import CellPaths
        from app.entities.event import _recompute_pending_and_wake
        eid, sib = "T-ISSUE-RC1", "T-ISSUE-RC1-SIB"
        upsert_entity("issues", "issue_id", "t",
                      {"issue_id": eid, "status": "todo", "pending_user_comment_event_ids": ["STALE"]})
        upsert_entity("issues", "issue_id", "t", {"issue_id": sib, "status": "todo", "title": "keep"})
        _recompute_pending_and_wake(CellPaths("t"), "issue", eid, None)
        row = get_entity("issues", "issue_id", "t", eid)
        self.assertEqual(row.get("pending_user_comment_event_ids"), [])
        self.assertEqual(int(row.get("rev") or 0), 1, "단일 entity CAS 쓰기가 아님 (rev 미bump)")
        # 형제는 손대지 않음 — 셀 통째 재기록이면 sib 도 DELETE+INSERT 됐을 것.
        sib_row = get_entity("issues", "issue_id", "t", sib)
        self.assertEqual(sib_row.get("title"), "keep")
        self.assertIsNone(sib_row.get("rev"))

    def test_recompute_no_clobber_concurrent_sibling(self):
        # recompute(eid) 를 반복하며 동시에 sib 를 N회 CAS 갱신. CAS 면 sib 의 모든 쓰기가
        # 살아 rev==N·title==마지막값. 옛 셀-통째 재기록이면 recompute 가 stale 스냅샷으로
        # sib 를 덮어 lost update.
        import threading
        from app.storage.sql import upsert_entity, get_entity, CASConflict
        from app.config import CellPaths
        from app.entities import cas_entity
        from app.entities.event import _recompute_pending_and_wake
        eid, sib = "T-ISSUE-RC2", "T-ISSUE-RC2-SIB"
        upsert_entity("issues", "issue_id", "t", {"issue_id": sib, "status": "todo"})
        cp = CellPaths("t")
        N = 40
        errors: list = []

        def recompute_writer():
            try:
                for _ in range(N):
                    # 매 iter 재무장: pending 을 stale 로 되돌려 recompute 가 실제로 쓰게 한다.
                    upsert_entity("issues", "issue_id", "t",
                                  {"issue_id": eid, "status": "todo",
                                   "pending_user_comment_event_ids": ["STALE"]})
                    _recompute_pending_and_wake(cp, "issue", eid, None)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def sibling_writer():
            try:
                for i in range(N):
                    while True:
                        try:
                            cas_entity(cp, "issue", sib,
                                       lambda f, v=f"title{i}": f.__setitem__("title", v))
                            break
                        except CASConflict:
                            continue
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        ta = threading.Thread(target=recompute_writer)
        tb = threading.Thread(target=sibling_writer)
        ta.start(); tb.start(); ta.join(90); tb.join(90)
        self.assertEqual(errors, [], f"writer 예외: {errors}")
        row = get_entity("issues", "issue_id", "t", sib)
        self.assertEqual(row.get("title"), f"title{N-1}", "형제 마지막 쓰기가 clobber 됨")
        self.assertEqual(int(row.get("rev") or 0), N, "형제 CAS 쓰기 수 != N (lost update)")


class EntityLayerCASGuardTest(unittest.TestCase):
    """런타임 entity 레이어는 셀 전체 재기록(write_entity_file)을 호출하지 않는다 (INFRA-ISSUE-319).

    MySQL 불필요한 구조 가드 — per-entity CAS 우회 경로가 재유입되면 즉시 red.
    (offline 단일-writer migration 스크립트는 app/entities 밖이라 대상 아님.)
    """
    def test_no_whole_cell_writer_in_entity_layer(self):
        import ast
        import pathlib
        entities_dir = pathlib.Path(__file__).resolve().parent.parent / "app" / "entities"
        offenders: list[str] = []
        for py in sorted(entities_dir.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                if name == "write_entity_file":
                    offenders.append(f"{py.name}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            f"entity 레이어가 whole-cell write_entity_file 호출 — per-entity CAS 우회: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
