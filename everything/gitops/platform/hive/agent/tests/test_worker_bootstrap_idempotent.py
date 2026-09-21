"""workspace bootstrap 멱등성 회귀 테스트.

2차 결함(NESS-ISSUE-3): 비정상 종료한 이전 워커가 공유 PVC bare repo 에 남긴
stale worktree 등록(gitdir 깨짐 → `prunable`)이 issue 브랜치를 점유 → 다음
워커의 `git worktree add -B <branch>` 가 "branch already used by worktree"
로 영구 실패. cell 전 entity 가 같은 landmine 을 밟아 stuck.

수정: _bootstrap_workspace 진입 시 항상 `git worktree prune`(깨진 등록 청소),
worktree add 1차 실패 시 force-remove + rmtree + prune 후 1회 self-heal 재시도.

검증:
  - 정상 경로에서도 add 전에 `worktree prune` 가 호출된다
  - add 가 "already used by worktree" 로 실패하면 force-remove·rmtree·prune
    후 재시도해 성공하면 RuntimeError 안 난다
  - 재시도도 실패하면 RuntimeError
"""

import sys
import types as _types
import unittest
from unittest import mock

if "claude_agent_sdk" not in sys.modules:
    _sdk = _types.ModuleType("claude_agent_sdk")
    for _n in ("AssistantMessage", "ClaudeAgentOptions", "ClaudeSDKClient",
               "ResultMessage", "SystemMessage", "TextBlock", "ToolUseBlock",
               "UserMessage"):
        setattr(_sdk, _n, type(_n, (), {}))
    _t = _types.ModuleType("claude_agent_sdk.types")
    _t.ToolResultBlock = type("ToolResultBlock", (), {})
    _sdk.types = _t
    sys.modules["claude_agent_sdk"] = _sdk
    sys.modules["claude_agent_sdk.types"] = _t

from app import worker


def _cp(rc=0, out="", err=""):
    import subprocess
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


class FakeRun:
    """subprocess.run 대역. (cmd 인자 리스트) 기록 + worktree add 결과 시퀀스 주입."""

    def __init__(self, add_results):
        self.calls = []          # list[list[str]]
        self._add = list(add_results)  # worktree add 호출별 CompletedProcess

    def __call__(self, cmd, *a, **kw):
        self.calls.append(cmd)
        if isinstance(cmd, list) and "worktree" in cmd and "add" in cmd:
            return self._add.pop(0) if self._add else _cp(0)
        if isinstance(cmd, list) and "ls-remote" in cmd:
            return _cp(0, out="")           # 브랜치 없음 → origin/main base
        return _cp(0)

    def opnames(self):
        """worktree 하위명령 시퀀스 (prune/add/remove ...) 만 추출."""
        seq = []
        for c in self.calls:
            if isinstance(c, list) and "worktree" in c:
                i = c.index("worktree")
                seq.append(c[i + 1] if i + 1 < len(c) else "")
        return seq


ENV = {
    "CELL_REPO_URL": "https://github.com/i-tems/cell-ness.git",
    "CELL_ID": "ness",
    "EXEC_CWD": "/data/workspaces/ness/NESS-ISSUE-3/cell",
    "WORKSPACE_NFS_PATH": "/data/workspaces/ness/NESS-ISSUE-3",
    "GITHUB_TOKEN": "",  # 빈 토큰 → credential 파일 쓰기 분기 skip
}


def _bootstrap():
    with mock.patch.dict(worker.os.environ, ENV, clear=False), \
         mock.patch.object(worker.os.path, "isdir", return_value=True), \
         mock.patch.object(worker.os.path, "exists", return_value=False), \
         mock.patch.object(worker.os, "makedirs"), \
         mock.patch.object(worker.shutil, "rmtree") as rmtree:
        worker._bootstrap_workspace(entity_type="issue", entity_id="NESS-ISSUE-3")
        return rmtree


class BootstrapIdempotentTests(unittest.TestCase):
    def test_prune_always_runs_before_add_on_happy_path(self):
        fake = FakeRun(add_results=[_cp(0)])
        with mock.patch.object(worker.subprocess, "run", fake):
            _bootstrap()
        seq = fake.opnames()
        self.assertIn("prune", seq, f"prune 미호출 seq={seq}")
        self.assertIn("add", seq)
        self.assertLess(seq.index("prune"), seq.index("add"),
                        f"prune 가 add 이전에 와야 함 seq={seq}")

    def test_stale_worktree_self_heals_and_no_raise(self):
        # 1차 add 가 stale 등록 충돌로 실패 → 정리 후 재시도 성공.
        fake = FakeRun(add_results=[
            _cp(128, err="fatal: 'issue/NESS-ISSUE-3' is already used by worktree at "
                          "'/data/workspaces/ness/NESS-ISSUE-3/cell'"),
            _cp(0),
        ])
        with mock.patch.object(worker.subprocess, "run", fake):
            rmtree = _bootstrap()  # 예외 안 나야 함
        seq = fake.opnames()
        self.assertEqual(seq.count("add"), 2, f"재시도(add 2회) 없음 seq={seq}")
        self.assertIn("remove", seq, f"force-remove 미호출 seq={seq}")
        rmtree.assert_called_once()
        # remove 는 1차 add 실패 후·2차 add 전.
        self.assertLess(seq.index("remove"), len(seq) - 1)

    def test_persistent_failure_raises(self):
        fake = FakeRun(add_results=[
            _cp(128, err="already used by worktree"),
            _cp(128, err="still broken"),
        ])
        with mock.patch.object(worker.subprocess, "run", fake):
            with self.assertRaises(RuntimeError):
                _bootstrap()


if __name__ == "__main__":
    unittest.main()
