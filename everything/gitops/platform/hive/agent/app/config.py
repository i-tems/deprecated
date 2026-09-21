"""환경 설정과 상수."""

from __future__ import annotations

import logging
import os
import sys

# ── Core ──
HUB_URL = os.environ.get("HUB_URL", "http://localhost:8000")
# CELL_ID 는 워커 pod 에 k8s_jobs.build_worker_job 가 항상 주입한다 (env "CELL_ID").
# 외부에서 모듈만 import 하는 경로(테스트·도구)에선 미설정일 수 있어 None 을 허용 —
# 묵시 default cell 폴백("default" 문자열)은 폐기. 실제 사용 지점에서 None 검사.
CELL_ID = os.environ.get("CELL_ID")
LOOP_ID = os.environ.get("LOOP_ID") or CELL_ID or "noinit"

# ── Paths ──
PROJECT_DIR = os.environ.get("PROJECT_DIR", None)
HIVE_ROOT = os.environ.get("HIVE_ROOT", PROJECT_DIR)
EXEC_CWD = os.environ.get("EXEC_CWD", PROJECT_DIR)
SHARED_DIR = os.environ.get("SHARED_DIR") or (os.path.join(HIVE_ROOT, "shared") if HIVE_ROOT else None)
# specs 정본은 i-tems/hive repo. hub 부팅 시 NFS HOME으로 sync.
SPECS_ROOT = os.environ.get("SPECS_ROOT", "/data/shared/specs")
SPECS_DIR = os.path.join(SPECS_ROOT, "workflow", "phases")
RUNTIME_SPECS_DIR = os.path.join(SPECS_ROOT, "runtime")

# ── Limits ──
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "1800"))
SESSION_MAX_TURNS = int(os.environ.get("SESSION_MAX_TURNS", "100"))

# ── Tier ──
EXEC_TIER_DEFAULT = os.environ.get("EXEC_TIER_DEFAULT", "high")

# high tier 는 명시 모델 ID 로 핀한다 — "opus" 별칭은 API 서버측에서 해소돼 CLI/계정
# 기본에 따라 구버전(예: claude-opus-4-7)으로 조용히 내려갈 수 있다. 워커가 한글 산문을
# capability tool-arg 로 쓸 때 4-7 에서 간헐적 토큰 깨짐이 관측돼 4-8 로 못 박는다.
TIER_MODEL = {"high": "claude-opus-4-8", "medium": "sonnet", "low": "haiku"}
MODEL_TO_TIER = {
    "opus": "high",
    "claude-opus-4-8": "high",
    "sonnet": "medium",
    "haiku": "low",
}


def resolve_model(tier: str) -> str:
    """tier(또는 모델명) → 실제 모델명."""
    tier = MODEL_TO_TIER.get(tier, tier)
    return TIER_MODEL.get(tier, tier)


# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(f"loop.{LOOP_ID}")
