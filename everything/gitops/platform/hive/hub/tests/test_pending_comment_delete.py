"""comment 삭제 시 pending_user_comment_event_ids 정합성 회귀 가드 (INFRA-ISSUE-213).

버그: comment 를 삭제해도 entity 의 pending_user_comment_event_ids 에서 빠지지 않아
done/archive entity 가 "답변 대기 사용자 댓글 있음"으로 잘못 잡혀 워커가 헛픽업했다.
근본 원인 둘 — (1) find_pending_user_comments 가 raw events 만 보고 comment_delete
마커를 적용 안 함, (2) event.delete_comment 가 _recompute_pending_and_wake 미호출.

hub 테스트 규약상 app 패키지를 직접 import 하지 않는다 (fastapi·capability_framework
런타임 의존 부재). event.py 를 stub 의존성과 함께 단독 로드해 순수 함수를 검증하고,
삭제 핸들러의 재계산 호출은 소스 가드로 확인한다 (test_cursor_and_me_alias 패턴).
"""

import ast
import importlib.util
import os
import sys
import types
import unittest


# ── 의존성 stub: event.py top-level import 를 런타임 없이 만족시킨다 ──

_CREATED_KEYS: list[str] = []


def _module(name, *, is_pkg=False):
    """sys.modules 에 모듈을 보장한다 — 이미 있으면(실제 모듈 또는 다른 테스트 stub)
    그대로 재사용하고, 내가 새로 만든 키만 _CREATED_KEYS 에 기록한다 (로드 후 정리용).
    """
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        if is_pkg:
            mod.__path__ = []
        sys.modules[name] = mod
        _CREATED_KEYS.append(name)
    return mod


def _stub_deps():
    """event.py top-level import 만족용 최소 stub.

    실제 fastapi·pydantic 은 설치돼 있으므로 절대 교체하지 않고 누락 속성만 보탠다
    (alphabet 순 선행 테스트가 fastapi 를 APIRouter 없이 stub 했을 수 있음 —
    test_user_settings_profile 과 동일 방어). capability_framework·app.* 는
    런타임 부재라 stub 으로 채우되, 로드 직후 _restore() 가 내가 만든 키만 지워
    후행 테스트(실제 app.* 로드)를 오염시키지 않는다.
    """
    cf = _module("capability_framework")
    if not hasattr(cf, "CapabilityResponse"):
        cf.CapabilityResponse = type("CapabilityResponse", (), {})

    fastapi_stub = _module("fastapi")
    if not hasattr(fastapi_stub, "APIRouter"):
        class _Router:
            def post(self, *a, **k):
                return lambda fn: fn

        fastapi_stub.APIRouter = _Router
    if not hasattr(fastapi_stub, "Request"):
        fastapi_stub.Request = type("Request", (), {})

    pyd = _module("pydantic")
    if not hasattr(pyd, "BaseModel"):
        pyd.BaseModel = type("BaseModel", (), {})
    if not hasattr(pyd, "Field"):
        pyd.Field = lambda *a, **k: None

    # app 패키지 + event.py 의 relative import 대상 stub.
    _module("app", is_pkg=True)
    _module("app.entities", is_pkg=True)

    config = _module("app.config")
    if not hasattr(config, "get_cell_paths"):
        config.get_cell_paths = lambda *a, **k: None

    cursor = _module("app.cursor")
    if not hasattr(cursor, "offset_page"):
        cursor.offset_page = lambda *a, **k: ([], None)
    if not hasattr(cursor, "resolve_offset"):
        cursor.resolve_offset = lambda *a, **k: 0

    helpers = _module("app.helpers")
    for name in ("read_jsonl", "iter_partitions_for_query", "emit_event",
                 "find_entity", "write_entity_file", "entity_lock"):
        if not hasattr(helpers, name):
            setattr(helpers, name, lambda *a, **k: None)


def _load_event():
    here = os.path.dirname(os.path.abspath(__file__))
    full = os.path.normpath(os.path.join(here, "..", "app", "entities", "event.py"))
    spec = importlib.util.spec_from_file_location("app.entities.event", full)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app.entities.event"] = mod
    _CREATED_KEYS.append("app.entities.event")
    spec.loader.exec_module(mod)
    return mod


def _restore():
    """내가 새로 만든 sys.modules 키만 제거 — find_pending_user_comments 는 순수 함수라
    로드 뒤 이 stub 들이 불필요하다. 실제 모듈(fastapi·pydantic)이나 다른 테스트가
    이미 만든 키(app 등)는 _CREATED_KEYS 에 없어 건드리지 않는다.
    """
    for key in _CREATED_KEYS:
        sys.modules.pop(key, None)


_stub_deps()
_EVENT = _load_event()
_restore()


# ── 이벤트 fixture (raw event 형태 — `type` 필드 사용) ──

def _comment(event_id, *, actor, ts, parent_event_id=None):
    data = {"text": "", "subtype": "discussion"}
    if parent_event_id is not None:
        data["parent_event_id"] = parent_event_id
    ptype = "user" if actor == "user" else "agent"
    pid = "user:dahuin" if actor == "user" else "agent:worker"
    return {
        "type": "comment", "event_id": event_id, "ts": ts,
        "principal_type": ptype, "principal_id": pid, "data": data,
    }


def _delete(target_event_id, *, ts):
    return {
        "type": "comment_delete", "event_id": f"del-{target_event_id}", "ts": ts,
        "principal_type": "user", "principal_id": "user:dahuin",
        "data": {"target_event_id": target_event_id},
    }


def _heads(events):
    return [h["event_id"] for h in _EVENT.find_pending_user_comments(events)]


class FindPendingExcludesDeletedTest(unittest.TestCase):
    def test_unreplied_user_comment_is_pending_baseline(self):
        # 회귀 기준선: 삭제 없으면 답 안 된 user 댓글은 pending.
        events = [_comment("c1", actor="user", ts="2026-06-03T00:00:00Z")]
        self.assertEqual(_heads(events), ["c1"])

    def test_deleted_user_comment_drops_from_pending(self):
        # 핵심 버그: 삭제된 user 댓글은 pending head 에서 빠져야 한다.
        events = [
            _comment("c1", actor="user", ts="2026-06-03T00:00:00Z"),
            _delete("c1", ts="2026-06-03T00:01:00Z"),
        ]
        self.assertEqual(_heads(events), [])

    def test_only_deleted_one_drops_others_remain(self):
        events = [
            _comment("c1", actor="user", ts="2026-06-03T00:00:00Z"),
            _comment("c2", actor="user", ts="2026-06-03T00:02:00Z"),
            _delete("c1", ts="2026-06-03T00:03:00Z"),
        ]
        self.assertEqual(_heads(events), ["c2"])

    def test_ai_reply_makes_parent_not_pending(self):
        # 회귀 기준선: AI reply 가 달린 user 댓글은 pending 아님.
        events = [
            _comment("c1", actor="user", ts="2026-06-03T00:00:00Z"),
            _comment("r1", actor="agent", ts="2026-06-03T00:01:00Z", parent_event_id="c1"),
        ]
        self.assertEqual(_heads(events), [])

    def test_deleted_ai_reply_revives_parent_pending(self):
        # 삭제된 AI reply 는 부모를 replied 로 마킹하면 안 된다 — 부모는 다시 pending.
        events = [
            _comment("c1", actor="user", ts="2026-06-03T00:00:00Z"),
            _comment("r1", actor="agent", ts="2026-06-03T00:01:00Z", parent_event_id="c1"),
            _delete("r1", ts="2026-06-03T00:02:00Z"),
        ]
        self.assertEqual(_heads(events), ["c1"])


class DeleteHandlerRecomputesTest(unittest.TestCase):
    """event.delete_comment 가 emit 후 _recompute_pending_and_wake 를 호출하는지 소스 가드.

    함수 단위 호출은 cell paths·파일 IO stub 비용이 커, AST 로 핸들러 본문에 재계산
    호출이 있는지만 확인한다 (find_pending 정합성은 위 functional 테스트가 담보).
    """

    @classmethod
    def setUpClass(cls):
        here = os.path.dirname(os.path.abspath(__file__))
        full = os.path.normpath(os.path.join(here, "..", "app", "entities", "event.py"))
        cls.tree = ast.parse(open(full, encoding="utf-8").read())

    def _fn_body(self, name):
        fn = next(
            n for n in ast.walk(self.tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
        )
        return ast.unparse(fn)

    def test_delete_comment_calls_recompute(self):
        body = self._fn_body("event_delete_comment")
        self.assertIn("_recompute_pending_and_wake", body)

    def test_add_comment_still_calls_recompute(self):
        # 기존 경로 회귀 안 났는지.
        body = self._fn_body("event_add")
        self.assertIn("_recompute_pending_and_wake", body)


if __name__ == "__main__":
    unittest.main()
