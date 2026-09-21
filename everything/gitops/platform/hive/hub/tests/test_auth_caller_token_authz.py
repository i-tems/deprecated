"""auth.caller_token authz — caller token 발급은 system principal 만 가능.

cell에 묶인 worker/cli caller가 자기 Bearer로 /auth.caller_token을 호출해
cell 없는 system 토큰(또는 타 cell worker 토큰)을 발급받아 cell 격리를 우회하던
권한 상승 경로를 막은 회귀 가드. (cross-cell 이슈 적재 차단)

auth.py 핸들러를 격리 네임스페이스에서 로드해 await 호출 — request.state.principal
하나만 보는 핸들러라 최소 Request 스텁으로 충분하다.
"""

import asyncio
import os
import sys
import types
import unittest
from pathlib import Path


# ── 런타임 의존 스텁 (google 미설치 환경) ────────────────────────────────────
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


for _g in ("google", "google.oauth2", "google.oauth2.id_token",
           "google.auth", "google.auth.transport"):
    if _g not in sys.modules:
        _stub(_g)
if not hasattr(sys.modules["google.oauth2.id_token"], "verify_oauth2_token"):
    sys.modules["google.oauth2.id_token"].verify_oauth2_token = lambda *a, **k: {}
if "google.auth.transport.requests" not in sys.modules:
    _stub("google.auth.transport.requests", Request=object)

# JWT_SECRET 필수 (≥32자) — 테스트 전용 고정값.
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")

import importlib.util  # noqa: E402

_APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _ensure_pkg():
    pkg = sys.modules.get("authmod_app")
    if pkg is None:
        pkg = types.ModuleType("authmod_app")
        pkg.__path__ = [str(_APP_DIR)]
        sys.modules["authmod_app"] = pkg


def _load(modname, filename):
    _ensure_pkg()
    full = f"authmod_app.{modname}"
    spec = importlib.util.spec_from_file_location(full, _APP_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "authmod_app"
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


# storage / entities 스텁 (caller_token 경로는 미사용이나 방어적으로 주입).
_ensure_pkg()
_storage = types.ModuleType("authmod_app.storage")
_storage.auth_repo = types.SimpleNamespace(record_login=lambda **k: None, list_recent=lambda **k: [])
sys.modules["authmod_app.storage"] = _storage
_entities = types.ModuleType("authmod_app.entities")
_entities.user_settings = types.SimpleNamespace(
    profile_override=lambda email: {"display_name": None, "avatar": None}
)
sys.modules["authmod_app.entities"] = _entities
sys.modules["authmod_app.entities.user_settings"] = _entities.user_settings

_principal = _load("principal", "principal.py")
_auth = _load("auth", "auth.py")
Principal = _principal.Principal


def _req(principal):
    """state.principal 만 보는 핸들러용 최소 Request 스텁."""
    return types.SimpleNamespace(state=types.SimpleNamespace(principal=principal))


def _body(**kw):
    base = dict(principal_type="worker", principal_id="worker:x",
                cell_id=None, issue_id=None, session_type=None, expiry_seconds=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


class CallerTokenAuthzTest(unittest.TestCase):
    def _call(self, principal, **body_kw):
        return asyncio.run(_auth.auth_caller_token(_body(**body_kw), _req(principal)))

    def test_system_caller_can_mint(self):
        """agent-loop(system) 정상 흐름은 그대로 발급된다."""
        sysp = Principal(type="system", id="system:agent-loop")
        out = self._call(sysp, principal_type="worker", principal_id="worker:w1", cell_id="infra")
        self.assertEqual(out["status"], "ok")
        self.assertIn("token", out["data"])

    def test_worker_caller_forbidden(self):
        """cell에 묶인 worker caller 는 발급 거부 (격리 우회 차단)."""
        workerp = Principal(type="worker", id="worker:w1", cell_id="infra")
        out = self._call(workerp, principal_type="worker", principal_id="worker:x", cell_id="infra")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_code"], "forbidden")

    def test_worker_cannot_escalate_to_system_token(self):
        """핵심 익스플로잇: worker 가 cell 없는 system 토큰을 발급받으려는 시도 → 차단."""
        workerp = Principal(type="worker", id="worker:w1", cell_id="infra")
        out = self._call(workerp, principal_type="system", principal_id="worker:escalate", cell_id=None)
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_code"], "forbidden")

    def test_worker_cannot_mint_foreign_cell_token(self):
        """worker(infra) 가 cell=items worker 토큰을 발급받으려는 시도 → 차단."""
        workerp = Principal(type="worker", id="worker:w1", cell_id="infra")
        out = self._call(workerp, principal_type="worker", principal_id="worker:y", cell_id="items")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_code"], "forbidden")

    def test_cli_caller_forbidden(self):
        clip = Principal(type="cli", id="cli:x", cell_id="infra")
        out = self._call(clip, principal_type="worker", principal_id="worker:x", cell_id="infra")
        self.assertEqual(out["error_code"], "forbidden")

    def test_missing_principal_forbidden(self):
        """principal 미설정(미인증) → 발급 거부."""
        out = self._call(None, principal_type="worker", principal_id="worker:x")
        self.assertEqual(out["error_code"], "forbidden")


if __name__ == "__main__":
    unittest.main()
