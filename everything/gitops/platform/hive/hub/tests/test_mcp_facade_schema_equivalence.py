"""전용 함수(facade) ↔ capability.describe 스키마 1:1 동등성 + 하위호환 회귀.

핵심 계약(드리프트 0):
  레지스트리 기반 전용 함수의 advertised inputSchema 는 ``capability.describe``
  가 반환하는 스키마에 transport-level ``cell`` 인자를 합성한 형태여야 한다.
  ``cell`` 한 키를 제외하면 capability handler request model 스키마와
  **바이트 동일** — 손으로 박은 정적 스키마가 아니라 동일 코드 경로
  (introspection)에서 동적 생성됨을 강제 검증한다. ``cell`` 은 transport
  레이어가 합성하는 cell-agnostic MCP 의 라우팅 인자.

하위호환:
  generic 메타툴 3종(capability_list/describe/invoke)은 (cell 인자 추가
  외에는) 잔존하고, 선정되지 않은 long-tail capability 는 전용 함수가 생기지
  않는다 (= capability_invoke 경로 그대로).

격리:
  full app import 가 필요한데, 이 스위트의 일부 테스트는 teardown 없이
  ``sys.modules['app']``·``fastapi``·``httpx`` 를 stub 으로 덮어쓴다(전역
  오염). discover 순서에 영향받지 않도록 검증 본문을 **서브프로세스**에서
  깨끗한 인터프리터로 실행한다(test_env_branch_subprocess 선례와 동일 전략).
"""

import json
import os
import subprocess
import sys
import textwrap
import unittest

_HUB_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_FRAMEWORK_DIR = os.path.normpath(
    os.path.join(_HUB_DIR, "..", "capability", "framework")
)

_CHILD = textwrap.dedent(
    """
    import asyncio, json, os, sys
    os.environ.setdefault("JWT_SECRET", "test_secret_test_secret_test_secret_0123456789")
    os.environ.setdefault("HUB_INTERNAL_TOKEN", "internal_test_token_internal_test_token")
    os.environ.setdefault("HIVE_DB_DISABLED", "1")
    os.environ.setdefault("DATABASE_URL", "sqlite://")

    import app as hub_app_mod
    from app import mcp_server, mcp_facade
    from app.mcp_facade import selected_capabilities
    from app.entities import introspection
    from app.entities.introspection import CapabilityDescribeRequest

    class _DummyRequest:
        headers = {}

    def describe(cap_id):
        resp = asyncio.run(
            introspection.capability_describe(
                CapabilityDescribeRequest(ids=[cap_id]), _DummyRequest()
            )
        )
        data = resp.data if hasattr(resp, "data") else resp["data"]
        return data["capabilities"][cap_id]

    tools = mcp_server.mcp._tool_manager._tools
    selected = selected_capabilities()
    out = {"selected": selected, "checks": {}}

    # issue 4종은 반드시 포함 (과제 1차 후보·DoD)
    out["checks"]["task_quartet"] = all(
        c in selected for c in ("issue.create", "issue.get", "issue.update", "issue.list")
    )

    # facade schema 에서 transport-level cell 인자를 제거한 사본 — capability.describe 와 비교용.
    # capability 가 원래 required 가 없으면 (예: issue.list) cell 제거 후 키 자체를 비운다 —
    # describe schema 에 required 키가 없는 형태와 일치시키기 위함.
    def _strip_cell(schema):
        props = {k: v for k, v in schema.get("properties", {}).items() if k != "cell"}
        required = [r for r in schema.get("required", []) if r != "cell"]
        out = dict(schema)
        if props:
            out["properties"] = props
        else:
            out.pop("properties", None)
        if required:
            out["required"] = required
        else:
            out.pop("required", None)
        return out

    # 각 facade: 등록·이름·스키마(cell 제외) 동일·description 포함·cell 인자 노출
    schema_eq, name_ok, desc_ok, cell_present = True, True, True, True
    for cap_id in selected:
        if cap_id not in tools or tools[cap_id].name != cap_id:
            name_ok = False
            continue
        d = describe(cap_id)
        params = tools[cap_id].parameters
        if _strip_cell(params) != d["parameters"]:
            schema_eq = False
        if "cell" not in params.get("properties", {}):
            cell_present = False
        if "cell" not in params.get("required", []):
            cell_present = False
        if d["description"] and d["description"].strip() not in tools[cap_id].description:
            desc_ok = False
        if cap_id not in tools[cap_id].description:
            desc_ok = False
    out["checks"]["all_registered_named"] = name_ok
    out["checks"]["schema_byte_equal_modulo_cell"] = schema_eq
    out["checks"]["cell_arg_present_required"] = cell_present
    out["checks"]["description_carried"] = desc_ok

    # 하위호환: 메타툴 3종 잔존
    out["checks"]["metatools_intact"] = all(
        m in tools for m in ("capability_list", "capability_describe", "capability_invoke")
    )

    # long-tail: 비선정 capability 는 전용 함수 없음 (capability_invoke 경로 그대로)
    out["checks"]["longtail_no_dedicated"] = (
        "signal.emit" in selected or "signal.emit" not in tools
    )

    # passthrough dispatch: facade → _invoke_internal 동일 경로
    # cell 은 transport-level kwarg 으로 분리, 나머지 평면인자는 payload 그대로
    captured = {}
    async def fake_invoke(ctx, endpoint, payload, *, cell):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        captured["cell"] = cell
        return {"status": "ok", "data": {"echo": payload}}
    ftools = mcp_facade.build_facade_tools(hub_app_mod.app, fake_invoke)
    tget = [t for t in ftools if t.name == "issue.get"][0]
    res = asyncio.run(
        tget.run(
            {"cell": "infra", "issue_id": "ITEMS-ISSUE-1", "extra": "x"},
            context=None,
        )
    )
    out["checks"]["passthrough_dispatch"] = (
        captured.get("endpoint") == "issue.get"
        and captured.get("payload") == {"issue_id": "ITEMS-ISSUE-1", "extra": "x"}
        and captured.get("cell") == "infra"
        and res.get("status") == "ok"
    )

    # cell 누락 → cell_required error envelope, dispatch 호출 자체 없음
    captured.clear()
    res_no_cell = asyncio.run(
        tget.run({"issue_id": "ITEMS-ISSUE-1"}, context=None)
    )
    out["checks"]["cell_required_when_missing"] = (
        res_no_cell.get("status") == "error"
        and res_no_cell.get("error_code") == "cell_required"
        and "endpoint" not in captured
    )

    print("RESULT_JSON:" + json.dumps(out))
    """
)


class TestFacadeSchemaEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [_FRAMEWORK_DIR, _HUB_DIR, env.get("PYTHONPATH", "")]
        )
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD],
            cwd=_HUB_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"child import/eval failed (rc={proc.returncode}):\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        line = next(
            ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT_JSON:")
        )
        cls.result = json.loads(line[len("RESULT_JSON:"):])

    def test_default_selection_ticket_centric(self):
        self.assertTrue(
            self.result["checks"]["task_quartet"],
            f"issue 4종 미포함: {self.result['selected']}",
        )

    def test_each_facade_present_and_named_canonically(self):
        self.assertTrue(self.result["checks"]["all_registered_named"])

    def test_facade_schema_equals_capability_describe_modulo_cell(self):
        self.assertTrue(
            self.result["checks"]["schema_byte_equal_modulo_cell"],
            "facade inputSchema 가 (cell 제외) capability.describe 와 불일치 — 정적 드리프트",
        )

    def test_facade_schema_exposes_required_cell_arg(self):
        self.assertTrue(
            self.result["checks"]["cell_arg_present_required"],
            "facade inputSchema 의 properties/required 에 transport-level cell 인자 누락",
        )

    def test_facade_description_carries_capability_doc(self):
        self.assertTrue(self.result["checks"]["description_carried"])

    def test_generic_metatools_unchanged_backward_compat(self):
        self.assertTrue(self.result["checks"]["metatools_intact"])

    def test_longtail_capability_has_no_dedicated_tool(self):
        self.assertTrue(self.result["checks"]["longtail_no_dedicated"])

    def test_facade_is_passthrough_dispatch(self):
        self.assertTrue(self.result["checks"]["passthrough_dispatch"])

    def test_facade_rejects_when_cell_missing(self):
        self.assertTrue(
            self.result["checks"]["cell_required_when_missing"],
            "cell 누락 시 cell_required error envelope 미반환 — 묵시 default 폴백 위험",
        )


if __name__ == "__main__":
    unittest.main()
