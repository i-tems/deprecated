"""codex 구독 OAuth 토큰의 단일 refresh 권한 데몬 (INFRA-ISSUE-256).

문제: ChatGPT OAuth 는 refresh 시 refresh_token 을 rotate 하고, rotate-out 된 토큰의
재사용을 도난 신호로 탐지해 **세션 전체를 무효화**한다. 공유 auth.json 을 동시 워커가
각자 refresh 하면 rotation 경합 → 세션 전멸 (codex 워커 fleet 전체 다운).

해법: 이 데몬만 refresh 한다 (단일 프로세스·replicas=1 → 경합 0). 워커 공유
auth.json 에는 access_token 만 두고 refresh_token 을 제거해 **워커가 refresh 자체를
못 하게** 한다 (codex 는 access_token 만으로도 동작 — 검증됨). 따라서 reuse 탐지가
구조적으로 불가능하다.

루프(주기 CHECK_PERIOD):
  1. 데몬 home(refresh_token 보유) access_token 의 exp 를 본다.
  2. 만료 임박(REFRESH_BEFORE 이내)이면 access_token 을 비워 codex 로 강제 refresh
     (refresh_token → 새 access_token + rotated refresh_token, 데몬 home 에 영속).
  3. 현재 access_token 을 access-token-only 로 워커 공유 auth.json 에 atomic 배포.
"""

import base64
import json
import os
import subprocess
import tempfile
import time

DAEMON_HOME = os.environ.get("CODEX_DAEMON_HOME", "/data/shared/.codex-daemon")
WORKER_HOME = os.environ.get("CODEX_WORKER_HOME", "/data/shared/.codex")
CHECK_PERIOD = int(os.environ.get("CODEX_REFRESH_CHECK_SEC", "300"))
REFRESH_BEFORE = int(os.environ.get("CODEX_REFRESH_BEFORE_SEC", "1200"))
MODEL = os.environ.get("CODEX_MODEL", "gpt-5.5")


def _expires_in(access_token: str) -> float:
    """access_token(JWT) 의 만료까지 남은 초. 디코드 실패 시 0 (= 즉시 refresh)."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0)
        return float(exp) - time.time()
    except Exception:
        return 0.0


def _force_refresh(dpath: str) -> None:
    """데몬 home access_token 을 비워 codex 가 refresh_token 으로 refresh 하게 한다."""
    d = json.load(open(dpath))
    d.setdefault("tokens", {})["access_token"] = ""
    json.dump(d, open(dpath, "w"))
    subprocess.run(
        ["codex", "exec", "--json", "-m", MODEL, "-s", "read-only",
         "--skip-git-repo-check", "-C", "/tmp", "ok"],
        input="", capture_output=True, text=True, timeout=120,
        env=dict(os.environ, CODEX_HOME=DAEMON_HOME),
    )


def _distribute(dpath: str) -> None:
    """데몬 home 의 현재 access_token 을 access-token-only 로 워커 auth.json 에 atomic 배포."""
    fresh = json.load(open(dpath))
    tok = dict(fresh.get("tokens") or {})
    if not tok.get("access_token"):
        raise RuntimeError("access_token 없음 — refresh 실패 추정")
    tok["refresh_token"] = ""  # 워커는 refresh 불가 (reuse 탐지 차단)
    out = dict(fresh)
    out["tokens"] = tok
    os.makedirs(WORKER_HOME, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=WORKER_HOME)
    os.close(fd)
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, os.path.join(WORKER_HOME, "auth.json"))  # atomic swap


def _cycle() -> str:
    dpath = os.path.join(DAEMON_HOME, "auth.json")
    at = (json.load(open(dpath)).get("tokens") or {}).get("access_token") or ""
    remaining = _expires_in(at)
    refreshed = False
    if remaining < REFRESH_BEFORE:
        _force_refresh(dpath)
        refreshed = True
    _distribute(dpath)
    return f"refreshed={refreshed} remaining={int(remaining)}s"


def main() -> None:
    print(f"[codex-auth-daemon] start (check={CHECK_PERIOD}s, refresh_before={REFRESH_BEFORE}s, "
          f"daemon={DAEMON_HOME}, worker={WORKER_HOME})", flush=True)
    while True:
        try:
            print(f"[codex-auth-daemon] {_cycle()}", flush=True)
        except Exception as exc:  # 데몬은 죽지 않고 다음 주기 재시도
            print(f"[codex-auth-daemon] error: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(CHECK_PERIOD)


if __name__ == "__main__":
    main()
