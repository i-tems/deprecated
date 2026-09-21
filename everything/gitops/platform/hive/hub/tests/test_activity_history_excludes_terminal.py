"""worker.activity_history 가 사람 터미널 skill 세션을 AI Activity 이력에서
제외하는지 (회귀: 터미널 attach 가 자율 loop 이력에 섞이던 버그).

AI Activity 과거 이력은 entity 의 loop 워커 transcript(`/data/workspaces/<cell>/
<entity>/cell` → slug `-data-workspaces-…-<id>-cell`)만 읽어야 한다. 사람이 직접
attach 한 터미널 skill 세션은 cwd 가 `/work/sessions/<cell>/<type>/<id>/cell` →
slug `-work-sessions-…-<id>-cell` 로 같은 `-<id>-cell` 접미사를 갖는다. 과거에
`_entity_session_dirs` 가 `*-<id>-cell` 로 glob 해 터미널 세션까지 빨아들였다.

hub 테스트 규약상 app import 금지 — `_entity_session_dirs` 함수 소스만 AST 로
떼어내 스텁 globals(os/glob/_CLAUDE_PROJECTS_ROOT)로 실행해 동작을 검증한다.
"""

import ast
import glob as _glob_mod
import os
import tempfile
import unittest
from pathlib import Path

_WORKER = Path(__file__).resolve().parents[1] / "app" / "entities" / "worker.py"


def _load_entity_session_dirs(projects_root: str):
    """worker.py 에서 _entity_session_dirs 함수만 떼어내 격리 namespace 에서
    컴파일·실행한다 (app/framework import 없이)."""
    src = _WORKER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_entity_session_dirs":
            ns: dict = {"os": os, "glob": _glob_mod, "_CLAUDE_PROJECTS_ROOT": projects_root}
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            exec(compile(mod, str(_WORKER), "exec"), ns)  # noqa: S102
            return ns["_entity_session_dirs"]
    raise AssertionError("_entity_session_dirs 함수를 worker.py 에서 찾지 못함")


class ActivityHistoryExcludesTerminalTest(unittest.TestCase):
    def test_terminal_session_dir_excluded(self):
        cell, eid = "infra", "INFRA-ISSUE-5"
        with tempfile.TemporaryDirectory() as root:
            # loop 워커 transcript dir (포함되어야 함)
            ws_slug = f"/data/workspaces/{cell}/{eid}/cell".replace("/", "-")
            ws_dir = os.path.join(root, ws_slug)
            os.makedirs(ws_dir)
            # 사람 터미널 skill 세션 dir (제외되어야 함) — 같은 -<id>-cell 접미사
            term_slug = f"/work/sessions/{cell}/issue/{eid}/cell".replace("/", "-")
            term_dir = os.path.join(root, term_slug)
            os.makedirs(term_dir)

            fn = _load_entity_session_dirs(root)
            got = fn(cell, "issue", eid)

            self.assertIn(ws_dir, got, "loop 워커 workspace transcript 는 포함돼야 한다")
            self.assertNotIn(
                term_dir, got,
                "사람 터미널 skill 세션은 AI Activity 이력에서 제외돼야 한다",
            )


if __name__ == "__main__":
    unittest.main()
