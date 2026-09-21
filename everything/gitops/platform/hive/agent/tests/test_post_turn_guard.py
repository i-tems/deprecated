"""post_turn_guard 의 (카테고리 × fresh_status) 정책 매트릭스 검증.

회귀 맥락:
- INFRA-ISSUE-116 / PR #433: max_turns × passive(waiting/cleanup/done/cancelled) →
  status 유지 + halt event (false positive 차단). 본 통합 함수에서 보존.
- silent deadlock 가드: 비에러 cycle 인데 running/cleanup 으로 남으면 force_error.
  본 통합 함수의 no_progress=True 분기로 흡수.

새 정책 (i-tems/everything INFRA-ISSUE-129):
- runtime_error / timeout / api_error / rate_limit × active → status 유지 + event.add.
- input_too_long × active → waiting + comment_subtype=handoff (사람 인계).
- max_turns / uncategorized × active → force_error (안전측).
- no_progress × active → force_error (silent deadlock).
- 모든 카테고리 × passive → status 유지 + halt event.
"""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.config import POLL_INTERVAL
from app.phase_handlers import post_dispatch
from app.phase_handlers.post import (
    post_turn_guard,
    rate_limit_backoff_seconds,
    _CATEGORY_POLICY,
    _RATE_LIMIT_FALLBACK_BACKOFF_S,
    _RATE_LIMIT_MAX_BACKOFF_S,
)


class _FakeClient:
    """LoopContext.client stub — api()/api_safe() 호출 기록."""

    def __init__(self, status):
        self._status = status  # 'fail' 이면 api() 에서 예외 — fetch 실패 시뮬레이션
        self.api_calls = []
        self.api_safe_calls = []

    def api(self, name, params):
        self.api_calls.append((name, params))
        if self._status == "fail":
            raise RuntimeError("hub down")
        return {"data": {"issue_id": params.get("issue_id"),
                         "project_id": params.get("project_id"),
                         "status": self._status}}

    def api_safe(self, name, data, *, issue_id=None, label=""):
        self.api_safe_calls.append((name, data))
        return {}


def _ctx(status):
    reset_calls = []
    ctx = SimpleNamespace(
        client=_FakeClient(status),
        session_store=SimpleNamespace(reset=lambda eid: reset_calls.append(eid)),
        log=SimpleNamespace(error=lambda *_a, **_k: None,
                            warning=lambda *_a, **_k: None,
                            info=lambda *_a, **_k: None),
    )
    ctx.reset_calls = reset_calls
    return ctx


def _result(subtype="error_max_turns", message="Maximum number of turns reached"):
    return {"is_error": True, "subtype": subtype, "result": message}


def _issue():
    return {"issue_id": "T-1", "title": "t"}


def _project():
    return {"project_id": "G-1", "title": "g"}


def _endpoints(ctx):
    return [c[0] for c in ctx.client.api_safe_calls]


def _find(ctx, endpoint):
    return next(c for c in ctx.client.api_safe_calls if c[0] == endpoint)


# ---------------------------------------------------------------------------
# 카테고리 1: max_turns — ISSUE-116 회귀 보호 + active 면 force_error.


class MaxTurnsPassiveSkipTest(unittest.TestCase):
    """max_turns × passive (waiting/cleanup/done/cancelled) — ISSUE-116 정책 보존.

    fresh status 가 passive 면 모든 카테고리 공통 = halt event 만, status 유지.
    """

    def test_waiting_task_skips_force_update(self):
        ctx = _ctx("waiting")
        post_turn_guard(ctx, _issue(), "issue", _result())
        endpoints = _endpoints(ctx)
        self.assertNotIn("issue.force_update", endpoints,
                         f"passive status 인데 force_update 호출됨: {endpoints}")
        self.assertIn("event.add", endpoints)
        payload = _find(ctx, "event.add")[1]["payload"]
        self.assertEqual(payload["category"], "max_turns")
        self.assertEqual(payload["current_status"], "waiting")
        self.assertTrue(payload["force_error_skipped"])

    def test_cleanup_task_skips_force_update(self):
        ctx = _ctx("cleanup")
        post_turn_guard(ctx, _issue(), "issue", _result())
        self.assertNotIn("issue.force_update", _endpoints(ctx))
        self.assertIn("event.add", _endpoints(ctx))

    def test_done_task_skips_force_update(self):
        ctx = _ctx("done")
        post_turn_guard(ctx, _issue(), "issue", _result())
        self.assertNotIn("issue.force_update", _endpoints(ctx))

    def test_cancelled_task_skips_force_update(self):
        ctx = _ctx("cancelled")
        post_turn_guard(ctx, _issue(), "issue", _result())
        self.assertNotIn("issue.force_update", _endpoints(ctx))

    def test_waiting_goal_skips_force_update(self):
        ctx = _ctx("waiting")
        post_turn_guard(ctx, _project(), "project", _result())
        endpoints = _endpoints(ctx)
        self.assertNotIn("project.force_update", endpoints)
        self.assertIn("event.add", endpoints)
        self.assertEqual(_find(ctx, "event.add")[1]["entity_type"], "project")


class MaxTurnsActiveForceErrorTest(unittest.TestCase):
    """max_turns × running — 기존 silent deadlock 가드 동작 보존."""

    def test_running_task_forces_error(self):
        ctx = _ctx("running")
        post_turn_guard(ctx, _issue(), "issue", _result())
        endpoints = _endpoints(ctx)
        self.assertIn("issue.force_update", endpoints,
                      f"running 인데 force_update 안 됨: {endpoints}")
        force_call = _find(ctx, "issue.force_update")
        self.assertEqual(force_call[1]["status"], "error")
        self.assertEqual(force_call[1]["comment_subtype"], "halt")
        payload = force_call[1]["comment_payload"]
        self.assertEqual(payload["category"], "max_turns")
        # HandoffCallout 원클릭 옵션: todo 재시도 + cleanup 취소.
        options = payload["options"]
        self.assertEqual(len(options), 2, options)
        self.assertEqual(options[0]["action"]["type"], "transition")
        self.assertEqual(options[0]["action"]["status"], "todo")
        self.assertEqual(options[1]["action"]["status"], "cleanup")

    def test_max_turns_goal_holds_no_force_update(self):
        # 통합 컨테이너 모델: Project 는 error/force_update 가 없다 (active 한정, active idle-ok).
        # max_turns(hard 카테고리) → halt event + hold=true 로 re-spawn 루프 차단, status 는 유지.
        ctx = _ctx("active")
        post_turn_guard(ctx, _project(), "project", _result())
        endpoints = _endpoints(ctx)
        self.assertNotIn("project.force_update", endpoints,
                         f"컨테이너인데 force_update 발동: {endpoints}")
        self.assertIn("event.add", endpoints)  # halt event
        hold_call = _find(ctx, "project.update")
        self.assertIs(hold_call[1]["hold"], True)

    def test_fetch_failure_falls_back_to_force(self):
        # hub 일시 장애 → fresh_status=None. max_turns 는 force_error 카테고리라
        # active 분기로 떨어져 force_update 가 발동된다 (안전측 폴백).
        ctx = _ctx("fail")
        post_turn_guard(ctx, _issue(), "issue", _result())
        self.assertIn("issue.force_update", _endpoints(ctx))


# ---------------------------------------------------------------------------
# 카테고리 2~5: runtime_error / timeout / api_error / rate_limit — force_error.
# (정책 변경: 실패는 재시도(soft_event, status 유지 → 재픽업 루프)하지 않고 곧장
#  error. 무한 재발행 토큰 폭주 제거 — INFRA-ISSUE-122/TASK-129.)


class FailCategoriesForceErrorTest(unittest.TestCase):
    """runtime_error / timeout / api_error / rate_limit × running — force_error.

    실패는 status 유지(재시도)가 아니라 error 로 전이한다. 사람이 todo 로 재시도
    (HandoffCallout). session reset 동반.
    """

    def _assert_force_error(self, ctx, category):
        endpoints = _endpoints(ctx)
        self.assertIn("issue.force_update", endpoints,
                      f"{category} 인데 force_error 전이 누락: {endpoints}")
        force_call = _find(ctx, "issue.force_update")
        self.assertEqual(force_call[1]["status"], "error")
        self.assertEqual(force_call[1]["comment_subtype"], "halt")
        self.assertEqual(force_call[1]["comment_payload"]["category"], category)

    def test_runtime_error_running_force_error(self):
        ctx = _ctx("running")
        post_turn_guard(ctx, _issue(), "issue",
                        _result(subtype="error_during_execution", message="claude crashed"))
        self._assert_force_error(ctx, "runtime_error")
        self.assertEqual(ctx.reset_calls, ["T-1"])

    def test_timeout_running_force_error(self):
        ctx = _ctx("running")
        # raw text "timeout" 매칭 — subtype 미지정.
        post_turn_guard(ctx, _issue(), "issue",
                        _result(subtype="", message="Request timeout after 600s"))
        self._assert_force_error(ctx, "timeout")

    def test_api_error_running_force_error(self):
        ctx = _ctx("running")
        # subtype 매칭 안 됨, raw text 도 특수 신호 없음 → api_error fallback.
        post_turn_guard(ctx, _issue(), "issue",
                        _result(subtype="", message="HTTP 503 upstream unavailable"))
        self._assert_force_error(ctx, "api_error")

    def test_rate_limit_running_force_error(self):
        ctx = _ctx("running")
        post_turn_guard(ctx, _issue(), "issue",
                        _result(subtype="", message="You hit your limit. Wait 30s."))
        self._assert_force_error(ctx, "rate_limit")


# ---------------------------------------------------------------------------
# 카테고리 5: input_too_long — 사람 게이트 (waiting + handoff).


class InputTooLongHandoffTest(unittest.TestCase):
    def test_input_too_long_running_handoff_waiting(self):
        ctx = _ctx("running")
        post_turn_guard(ctx, _issue(), "issue",
                        _result(subtype="error_input_too_long",
                                message="prompt 100000 tokens > limit"))
        endpoints = _endpoints(ctx)
        # force_update → waiting (status 변경은 force_update 로 진행 — 가드 우회 경로).
        self.assertIn("issue.force_update", endpoints,
                      f"input_too_long 인데 handoff 전이 누락: {endpoints}")
        force_call = _find(ctx, "issue.force_update")
        self.assertEqual(force_call[1]["status"], "waiting",
                         "input_too_long 은 error 가 아니라 waiting(handoff)")
        self.assertEqual(force_call[1]["comment_subtype"], "handoff")
        payload = force_call[1]["comment_payload"]
        self.assertEqual(payload["reason"], "input_too_long")
        # HandoffCallout 원클릭 옵션: 재진입(reply) + 취소(transition cleanup).
        options = payload["options"]
        self.assertEqual(len(options), 2, options)
        self.assertEqual(options[0]["action"]["type"], "reply",
                         "input_too_long 재진입은 reply (워커 wake)")
        self.assertEqual(options[1]["action"], {
            "type": "transition", "status": "cleanup",
            "comment": "취소 진입 (input_too_long)",
        })

    def test_input_too_long_waiting_skips(self):
        # 이미 waiting 이면 handoff 도 skip — passive 면 모든 카테고리 공통 halt event.
        ctx = _ctx("waiting")
        post_turn_guard(ctx, _issue(), "issue",
                        _result(subtype="error_input_too_long", message="too long"))
        endpoints = _endpoints(ctx)
        self.assertNotIn("issue.force_update", endpoints)
        self.assertIn("event.add", endpoints)
        payload = _find(ctx, "event.add")[1]["payload"]
        self.assertEqual(payload["category"], "input_too_long")
        self.assertTrue(payload["force_error_skipped"])


# ---------------------------------------------------------------------------
# 카테고리 6: uncategorized — 안전측 force_error.


class UncategorizedFallbackTest(unittest.TestCase):
    def test_uncategorized_running_forces_error(self):
        # result 빈 문자열 + subtype 없음 → unknown → uncategorized → force_error.
        ctx = _ctx("running")
        post_turn_guard(ctx, _issue(), "issue", {"is_error": True, "subtype": "", "result": ""})
        endpoints = _endpoints(ctx)
        self.assertIn("issue.force_update", endpoints,
                      "분류 불가 는 안전측 force_error 여야 함")
        self.assertEqual(_find(ctx, "issue.force_update")[1]["comment_payload"]["category"],
                         "uncategorized")


# ---------------------------------------------------------------------------
# 카테고리 7: no_progress — silent deadlock 가드.


class NoProgressGuardTest(unittest.TestCase):
    """비에러 cycle 인데 running/cleanup 으로 남으면 force_error.

    능동 status 는 worker 자신만 진전시키므로 _wait_for_wake 로 잠들면 영구 데드락.
    """

    def test_no_progress_running_task_forces_error(self):
        ctx = _ctx("running")
        post_turn_guard(ctx, _issue(), "issue", {"is_error": False},
                        fresh_status="running", no_progress=True)
        endpoints = _endpoints(ctx)
        self.assertIn("issue.force_update", endpoints,
                      f"no_progress running 인데 force_update 누락: {endpoints}")
        force_call = _find(ctx, "issue.force_update")
        self.assertEqual(force_call[1]["status"], "error")
        self.assertEqual(force_call[1]["comment_payload"]["category"], "no_progress")

    def test_no_progress_cleanup_task_forces_error(self):
        # cleanup 도 ISSUE 의 능동 status — worker.py 가 issue cleanup 만 여기로 떨어뜨린다
        # (컨테이너엔 cleanup 자체가 없음).
        ctx = _ctx("cleanup")
        post_turn_guard(ctx, _issue(), "issue", {"is_error": False},
                        fresh_status="cleanup", no_progress=True)
        endpoints = _endpoints(ctx)
        self.assertIn("issue.force_update", endpoints)
        self.assertEqual(_find(ctx, "issue.force_update")[1]["status"], "error")

    def test_no_progress_active_goal_parks_to_waiting(self):
        # 5-status 컨테이너 모델: active 인 채 이번 turn mutation 0 (no_progress) → status=
        # waiting 으로 parked (사람 댓글 reply 로 복구). error/force_update 가 아니라 일반
        # *.update(status=waiting) — 매 cycle self-action 재발급으로 인한 영구 re-invoke 차단.
        ctx = _ctx("active")
        post_turn_guard(ctx, _project(), "project", {"is_error": False},
                        fresh_status="active", no_progress=True)
        endpoints = _endpoints(ctx)
        self.assertNotIn("project.force_update", endpoints)
        self.assertIn("event.add", endpoints)  # halt event
        update_call = _find(ctx, "project.update")
        self.assertEqual(update_call[1]["status"], "waiting")
        self.assertEqual(update_call[1]["comment_subtype"], "handoff")
        # session 리셋 — 다음 cycle 은 댓글 wake 후 reply 진입.
        self.assertEqual(ctx.reset_calls, ["G-1"])

    def test_no_progress_active_initiative_parks_to_waiting(self):
        # 컨테이너 아날로그가 initiative 에도 적용됨.
        ctx = _ctx("active")
        post_turn_guard(
            ctx, {"initiative_id": "I-1", "title": "i"}, "initiative",
            {"is_error": False}, fresh_status="active", no_progress=True,
        )
        self.assertNotIn("initiative.force_update", _endpoints(ctx))
        self.assertEqual(_find(ctx, "initiative.update")[1]["status"], "waiting")


# ---------------------------------------------------------------------------
# rate_limit backoff — busy-retry halt-event flood 회귀 가드 (NESS-ISSUE-32).
#
# 증상: rate_limit × passive(waiting) 가 worker.py 의 POLL_INTERVAL(30s) busy-retry
# 경로를 타 reset 전까지 매 cycle halt event 를 피드에 쌓음 (46분간 91건). rate_limit
# 은 계정 전역 조건 — reset 시각까지 backoff 해 1 cycle 로 collapse.


class RateLimitBackoffParseTest(unittest.TestCase):
    """'resets H[:MM]am/pm' 파싱 → reset 까지 초. now 주입으로 결정론."""

    def test_parses_reset_time_to_seconds(self):
        # 관측된 실제 메시지. now=14:53:08 UTC, reset=15:40 → 46m52s.
        now = datetime(2026, 6, 5, 14, 53, 8, tzinfo=timezone.utc)
        secs = rate_limit_backoff_seconds(
            "success | You've hit your limit · resets 3:40pm (UTC)", now=now
        )
        self.assertEqual(secs, 46 * 60 + 52)

    def test_no_minutes_form(self):
        now = datetime(2026, 6, 5, 22, 30, 0, tzinfo=timezone.utc)
        # resets 11pm → 23:00, 30분 후.
        self.assertEqual(
            rate_limit_backoff_seconds("resets 11pm (UTC)", now=now), 30 * 60
        )

    def test_am_form(self):
        now = datetime(2026, 6, 5, 8, 0, 0, tzinfo=timezone.utc)
        # resets 9am → 09:00, 1시간 후.
        self.assertEqual(
            rate_limit_backoff_seconds("resets 9am (UTC)", now=now), 60 * 60
        )

    def test_already_passed_wraps_to_next_day_capped(self):
        # now=16:00, reset 3:40pm(15:40) 이미 지남 → 다음 날 15:40, 캡(3600)으로 bound.
        now = datetime(2026, 6, 5, 16, 0, 0, tzinfo=timezone.utc)
        secs = rate_limit_backoff_seconds("resets 3:40pm (UTC)", now=now)
        self.assertEqual(secs, _RATE_LIMIT_MAX_BACKOFF_S)

    def test_unparseable_falls_back(self):
        now = datetime(2026, 6, 5, 14, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(
            rate_limit_backoff_seconds("You hit your limit. Wait a while.", now=now),
            _RATE_LIMIT_FALLBACK_BACKOFF_S,
        )

    def test_lower_bound_is_poll_interval(self):
        # reset 이 코앞(< POLL_INTERVAL)이어도 최소 POLL_INTERVAL 만큼은 sleep.
        now = datetime(2026, 6, 5, 15, 39, 50, tzinfo=timezone.utc)
        secs = rate_limit_backoff_seconds("resets 3:40pm (UTC)", now=now)
        self.assertEqual(secs, POLL_INTERVAL)


class PostDispatchBackoffReturnTest(unittest.TestCase):
    """post_dispatch 반환값: rate_limit 이면 backoff>0, 그 외 에러/성공은 0.

    이 반환값을 worker.py 가 sleep 인자로 소비한다 (이전엔 무시돼 busy-retry).
    """

    def _ctx(self):
        ctx = _ctx_base = SimpleNamespace(
            client=_FakeClient("waiting"),
            session_store=SimpleNamespace(reset=lambda eid: None),
            log=SimpleNamespace(error=lambda *_a, **_k: None,
                                warning=lambda *_a, **_k: None,
                                info=lambda *_a, **_k: None),
            log_usage=lambda **_k: None,
        )
        return ctx

    def _wr(self, claude_result):
        work_item = SimpleNamespace(context={
            "session_type": "issue_progress",
            "entity_type": "issue",
            "issue": {"issue_id": "T-1", "title": "t"},
        })
        return SimpleNamespace(work_item=work_item, claude_result=claude_result)

    def test_rate_limit_returns_positive_backoff(self):
        wr = self._wr({"is_error": True, "subtype": "",
                       "result": "You've hit your limit · resets 3:40pm (UTC)"})
        self.assertGreater(post_dispatch(self._ctx(), wr), 0)

    def test_other_error_returns_zero(self):
        wr = self._wr({"is_error": True, "subtype": "error_during_execution",
                       "result": "claude crashed"})
        self.assertEqual(post_dispatch(self._ctx(), wr), 0)

    def test_success_returns_zero(self):
        wr = self._wr({"is_error": False, "result": "done"})
        self.assertEqual(post_dispatch(self._ctx(), wr), 0)


class TestCategoryPolicyInvariant(unittest.TestCase):
    """_CATEGORY_POLICY 가 내는 action 은 force_error/handoff 뿐 — 이 때문에
    post_turn_guard 의 action 은 halt_event(passive)/force_error/handoff 만 가능하고
    soft_event 분기는 도달불가다(제거됨, INFRA-ISSUE-322). soft_event 같은 미구현
    정책값을 handler 없이 재추가하면 이 테스트가 잡는다."""

    def test_policy_values_have_handlers(self):
        self.assertLessEqual(set(_CATEGORY_POLICY.values()), {"force_error", "handoff"})


if __name__ == "__main__":
    unittest.main()
