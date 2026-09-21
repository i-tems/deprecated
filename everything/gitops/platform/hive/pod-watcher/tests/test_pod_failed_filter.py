"""pod_failed 정상 종료 필터 회귀 테스트 (INFRA-ISSUE-184, INFRA-ISSUE-289, INFRA-ISSUE-292).

근본 결함: pod-watcher 가 exit_code != 0 이면 무조건 infra.pod_failed 를 emit 해,
K8s 가 Pod 를 graceful terminate(롤아웃·스케일다운·작업완료 후 삭제) 할 때 보내는
SIGTERM(143) 정상 종료까지 장애로 신고 → 시그널 큐 노이즈 누적.

수정: _seed_or_emit 의 emit 경로에서 아래 정상 종료 잔재를 건너뛴다.
  - exit_code==143 + restart_count==0
  - Deployment owner + exit_code==137 + reason!=OOMKilled + restart_count==0
  - owner 없는 sandbox-* pod + exit_code==137 + reason!=OOMKilled + restart_count==0

검증:
  - graceful SIGTERM(143, restart=0) → emit 안 함
  - crashloop SIGTERM(143, restart>0)  → emit 함 (crashloop 은 장애)
  - 일반 크래시(exit=1, restart=0)      → emit 함
  - rollout SIGKILL(137, Error, Deployment, restart=0) → emit 안 함
  - sandbox teardown SIGKILL(137, Error, owner 없음, restart=0) → emit 안 함
  - OOMKilled(137), crashloop SIGKILL(137), non-Deployment/non-sandbox SIGKILL(137) → emit 함
"""

import importlib.util
import os
import threading
import unittest
from unittest import mock
from types import SimpleNamespace

# app/main.py 를 파일 경로로 직접 로드 (site-packages 의 동명 'app' 패키지 충돌 회피).
_MAIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "main.py"
)
_spec = importlib.util.spec_from_file_location("pod_watcher_main", _MAIN)
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)


def _make_pod(
    exit_code: int,
    restart_count: int,
    reason: str = "Error",
    pod_name: str = "worker-pod",
):
    """단일 컨테이너가 terminated(exit_code, restart_count) 인 Pod stub."""
    terminated = SimpleNamespace(
        exit_code=exit_code,
        reason=reason,
        started_at=None,
        finished_at=None,
    )
    cs = SimpleNamespace(
        name="worker",
        restart_count=restart_count,
        state=SimpleNamespace(terminated=terminated),
        last_state=SimpleNamespace(terminated=None),
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            uid=f"uid-{exit_code}-{restart_count}",
            namespace="cell-pen",
            name=pod_name,
            owner_references=[],  # _resolve_owner → (None, None), apps 미사용
        ),
        spec=SimpleNamespace(node_name="node-1"),
        status=SimpleNamespace(
            container_statuses=[cs],
            init_container_statuses=[],
        ),
    )


class _RecordingHub:
    def __init__(self):
        self.emitted = []

    def emit(self, body):
        self.emitted.append(body)


class PodFailedFilterTest(unittest.TestCase):
    def setUp(self):
        # __init__ 은 kube/token 부트스트랩을 하므로 우회하고 필요한 필드만 세팅.
        self.w = object.__new__(pw.Watcher)
        self.w.apps = None  # owner_references 가 비어 _resolve_owner 가 호출 안 함
        self.w.hub = _RecordingHub()
        self.w.seen = set()
        self.w.lock = threading.Lock()

    def _emit_for(
        self,
        exit_code,
        restart_count,
        reason="Error",
        owner_kind=None,
        owner_name="owner",
        pod_name="worker-pod",
    ):
        self.w.hub.emitted.clear()
        self.w.seen.clear()
        with mock.patch.object(pw, "_resolve_owner", return_value=(owner_kind, owner_name)):
            self.w._seed_or_emit(_make_pod(exit_code, restart_count, reason, pod_name), emit=True)
        return self.w.hub.emitted

    def test_graceful_sigterm_not_emitted(self):
        self.assertEqual(self._emit_for(143, 0), [])

    def test_crashloop_sigterm_emitted(self):
        emitted = self._emit_for(143, 2)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["detail"]["raw"]["exit_code"], 143)

    def test_normal_crash_emitted(self):
        self.assertEqual(len(self._emit_for(1, 0)), 1)

    def test_oom_sigkill_emitted(self):
        emitted = self._emit_for(137, 0, reason="OOMKilled", owner_kind="Deployment")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["detail"]["raw"]["exit_code"], 137)

    def test_rollout_sigkill_not_emitted(self):
        self.assertEqual(
            self._emit_for(137, 0, reason="Error", owner_kind="Deployment"),
            [],
        )

    def test_crashloop_sigkill_emitted(self):
        emitted = self._emit_for(137, 2, reason="Error", owner_kind="Deployment")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["detail"]["raw"]["exit_code"], 137)

    def test_non_deployment_sigkill_emitted(self):
        emitted = self._emit_for(137, 0, reason="Error", owner_kind="StatefulSet")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["detail"]["raw"]["exit_code"], 137)

    def test_ownerless_sandbox_sigkill_not_emitted(self):
        self.assertEqual(
            self._emit_for(
                137,
                0,
                reason="Error",
                owner_kind=None,
                owner_name=None,
                pod_name="sandbox-abc123",
            ),
            [],
        )

    def test_ownerless_non_sandbox_sigkill_emitted(self):
        emitted = self._emit_for(
            137,
            0,
            reason="Error",
            owner_kind=None,
            owner_name=None,
            pod_name="worker-pod",
        )
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["detail"]["raw"]["exit_code"], 137)

    def test_sandbox_oom_sigkill_emitted(self):
        emitted = self._emit_for(
            137,
            0,
            reason="OOMKilled",
            owner_kind=None,
            owner_name=None,
            pod_name="sandbox-abc123",
        )
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["detail"]["raw"]["exit_code"], 137)


if __name__ == "__main__":
    unittest.main()
