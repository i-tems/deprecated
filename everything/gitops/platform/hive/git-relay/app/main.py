"""hive-git-relay — GitHub push webhook → Gitea mirror-sync 즉시 트리거.

hub 의 `/cell.github_push` 릴레이를 hub 생명주기(단일 replica + Recreate 롤아웃
공백)에서 떼어낸 항상-떠있는(2 replica RollingUpdate) stateless 전용 서비스.

배경(INFRA-ISSUE-259): GitHub push webhook 은 실패 시 재시도가 없다. relay 가
hub 안에 있어, hub 롤아웃 공백(~60–90s)에 webhook 이 도착하면 Traefik 503 으로
유실 → mirror-sync 누락 → Gitea pull-mirror 폴링(분 단위)으로 강등돼 배포가
지연됐다. 이 서비스는 hub 와 독립적으로 떠 있어 그 공백을 없앤다.

동작은 hub `cell.github_push` 핸들러(hub/app/entities/deployment.py)와 1:1 동일:
  POST /cell.github_push?owner=<o>&repo=<r>
    1) X-Hub-Signature-256 == "sha256=" + HMAC_SHA256(HUB_CELL_WEBHOOK_SECRET, body)
    2) Gitea POST /api/v1/repos/{owner}/{repo}/mirror-sync  (HUB_GITEA_ADMIN_TOKEN)
  GET /health → 200

cell.json subscriptions 등 2차 처리는 그대로 hub 가 담당한다(mirror 갱신 후
Gitea 가 발사하는 push webhook → hub /deployment.notify_push). 이 서비스는 첫
홉(mirror-sync 트리거)만 책임진다.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("git-relay")

# K8s DNS-1123 label — hub `_safe_name` 와 동일 (owner/repo 신뢰 입력 가드).
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
GITEA_URL = os.environ.get(
    "HUB_GITEA_INTERNAL_URL", "http://gitea-http.gitea.svc:3000",
).rstrip("/")


def _secret() -> str:
    return os.environ.get("HUB_CELL_WEBHOOK_SECRET", "").strip()


def _token() -> str:
    return os.environ.get("HUB_GITEA_ADMIN_TOKEN", "").strip()


def _mirror_sync(owner: str, repo: str) -> tuple[int, str]:
    """Gitea mirror-sync 호출. (status_code, err_msg) — 2xx 면 err 빈 문자열."""
    url = f"{GITEA_URL}/api/v1/repos/{owner}/{repo}/mirror-sync"
    req = urllib.request.Request(
        url, method="POST", headers={"Authorization": f"token {_token()}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, f"Gitea {exc.code}: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "git-relay/1"

    def log_message(self, *_args) -> None:  # 기본 access log 억제 — 자체 log 만.
        return

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        u = urlparse(self.path)
        if u.path != "/cell.github_push":
            self._send(404, {"error": "not_found"})
            return

        q = parse_qs(u.query)
        owner = (q.get("owner") or [""])[0]
        repo = (q.get("repo") or [""])[0]
        if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
            self._send(400, {"error": "invalid_request",
                             "message": "owner/repo 는 K8s DNS-1123 label"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""

        secret = _secret()
        if not secret:
            self._send(500, {"error": "auth_unconfigured"})
            return
        presented = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, "sha256").hexdigest()
        if not hmac.compare_digest(presented, expected):
            self._send(401, {"error": "auth_invalid"})
            return

        if not _token():
            self._send(500, {"error": "gitea_token_missing"})
            return

        code, err = _mirror_sync(owner, repo)
        if 200 <= code < 300:
            log.info("mirror-sync ok %s/%s", owner, repo)
            self._send(200, {"owner": owner, "repo": repo, "synced": True})
        else:
            log.warning("mirror-sync fail %s/%s: %s", owner, repo, err or code)
            self._send(502, {"error": "sync_failed", "message": err or f"status {code}"})


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    log.info("git-relay listening on :%d (gitea=%s)", port, GITEA_URL)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
