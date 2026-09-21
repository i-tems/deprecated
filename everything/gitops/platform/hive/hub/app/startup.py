"""Hub 기동 시 프로비저닝 — hive repo sync, GitHub webhook 확보, DB schema 초기화.

cell은 사람이 cell repo를 미리 만들고 cell.create로 명시 등록해야 함 (auto-bootstrap 없음).
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import db

log = logging.getLogger("hub.startup")

HIVE_REPO_URL = os.environ.get("HIVE_REPO_URL", "https://github.com/i-tems/hive.git")
HIVE_REPO_SYNC_TARGET = Path(os.environ.get("HIVE_REPO_SYNC_TARGET", "/data/shared/.claude"))
HIVE_REPO_SYNC_DIRS = ("specs", "rules", "skills", "schemas", "knowledge")
# 최상위 파일 — worker 의 ~/.claude/ (user-level) 로 그대로 sync. CLAUDE.md 는
# setting_sources=["user"] 일 때 claude CLI 가 자동 로드하는 항상-적용 계약.
HIVE_REPO_SYNC_FILES = ("CLAUDE.md",)

# codex worker(AGENT_BACKEND=codex) 하네스 — ruler 가 .ruler/ 에서 생성한 .codex/.
# worker HOME=/data/shared → codex 의 CODEX_HOME=~/.codex=/data/shared/.codex. repo
# 루트 AGENTS.md 는 $CODEX_HOME 글로벌 instruction 으로 cwd 무관 로드된다(검증). skill
# 의 `specs/...` 참조는 같은 HOME 의 specs/ 가 충족(아래 중립 sync).
HIVE_CODEX_SYNC_TARGET = Path(os.environ.get("HIVE_CODEX_SYNC_TARGET", "/data/shared/.codex"))
HIVE_CODEX_SYNC_DIRS = ("skills",)
HIVE_CODEX_SYNC_FILES = ("AGENTS.md",)

# agent-중립 계약(specs/schemas) — repo-root 에서 worker HOME(/data/shared) 직하로 sync.
# claude·codex 어느 백엔드의 설정 디렉터리에도 두지 않는 공유 자산이라, 두 백엔드 모두
# HOME-상대 `specs/...`·`schemas/...` 로 참조한다. (repo 에서 옛 `.claude/specs` 가
# 사라지면 위 HIVE_REPO_SYNC_DIRS 의 specs/schemas 항목이 /data/shared/.claude/ 의
# 옛 사본을 prune — 전환 중 깨짐 구간 없음.)
HIVE_NEUTRAL_SYNC_TARGET = Path(os.environ.get("HIVE_NEUTRAL_SYNC_TARGET", "/data/shared"))
HIVE_NEUTRAL_SYNC_DIRS = ("specs", "schemas")

# 마지막으로 NFS HOME 에 반영한 i-tems/hive HEAD SHA. poller 가 ls-remote SHA 와
# 비교해 변경 시에만 clone+swap 한다 (불필요한 dir swap = 가동 세션 watcher 교란 방지).
_last_synced_sha: str | None = None


# i-tems/hive 는 Gitea 미러가 아니라 GitHub 정본만 존재 → cell 용 Gitea-hook
# 기계가 안 먹는다. GitHub push webhook 을 hub 외부 ingress 로 직접 받는다.
HIVE_GITHUB_WEBHOOK_URL = os.environ.get(
    "HIVE_GITHUB_WEBHOOK_URL", "https://hub-webhook.i-tems.com/git.github_push",
)


def bootstrap() -> None:
    """기동 시 1회 실행. lifespan에서 호출."""
    sync_hive_repo("bootstrap", force=True)
    _ensure_hive_github_webhook()
    _bootstrap_db()


def _ensure_hive_github_webhook() -> None:
    """i-tems/hive 의 GitHub repo 에 push→hub webhook 을 멱등 보장 (best-effort).

    동일 config.url hook 이 있으면 no-op. 실패는 bootstrap 을 막지 않음
    (webhook 없으면 hub 재기동 시 bootstrap sync 로만 갱신 — graceful degrade).
    """
    import urllib.error
    import urllib.request

    token = os.environ.get("HIVE_REPO_TOKEN", "").strip()
    secret = os.environ.get("HUB_CELL_WEBHOOK_SECRET", "").strip()
    if not token or not secret:
        log.warning("[hive-repo] webhook ensure 스킵 — "
                    "HIVE_REPO_TOKEN(%s)/HUB_CELL_WEBHOOK_SECRET(%s) 확인",
                    bool(token), bool(secret))
        return

    from .gitea_mirror import parse_github_owner_repo
    orr = parse_github_owner_repo(HIVE_REPO_URL)
    if not orr:
        log.warning("[hive-repo] webhook ensure 스킵 — HIVE_REPO_URL 파싱 실패: %s",
                    HIVE_REPO_URL)
        return
    api = f"https://api.github.com/repos/{orr[0]}/{orr[1]}/hooks"
    hdr = {"Authorization": f"token {token}",
           "Accept": "application/vnd.github+json",
           "User-Agent": "hive-hub"}

    def _req(method: str, url: str, data: bytes | None = None):
        r = urllib.request.Request(url, data=data, method=method, headers=hdr)
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read() or b"null")

    try:
        hooks = _req("GET", api) or []
        for h in hooks:
            if (h.get("config") or {}).get("url") == HIVE_GITHUB_WEBHOOK_URL:
                log.info("[hive-repo] github webhook 이미 존재 (id=%s)", h.get("id"))
                return
        body = json.dumps({
            "name": "web", "active": True, "events": ["push"],
            "config": {"url": HIVE_GITHUB_WEBHOOK_URL, "content_type": "json",
                       "secret": secret, "insecure_ssl": "0"},
        }).encode()
        created = _req("POST", api, body)
        log.info("[hive-repo] github webhook 생성 완료 (id=%s) → %s",
                 (created or {}).get("id"), HIVE_GITHUB_WEBHOOK_URL)
    except urllib.error.HTTPError as exc:
        log.warning("[hive-repo] github webhook ensure 실패 HTTP %s: %s",
                    exc.code, exc.read()[:300] if hasattr(exc, "read") else exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("[hive-repo] github webhook ensure 실패: %s", exc, exc_info=True)


def _hive_repo_auth_url() -> str | None:
    """HIVE_REPO_TOKEN 으로 인증된 clone/ls-remote URL. 토큰 없으면 None."""
    token = os.environ.get("HIVE_REPO_TOKEN", "").strip()
    if not token:
        return None
    url = HIVE_REPO_URL
    if url.startswith("https://"):
        # https → token 인증 URL로 변환
        url = url.replace("https://", f"https://x-access-token:{token}@", 1)
    return url


def _remote_head_sha(url: str) -> str | None:
    """origin HEAD SHA (clone 없이). 실패 시 None."""
    try:
        out = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            check=True, capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return out.split()[0] if out else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        log.warning(f"[hive-repo] ls-remote 실패: {exc}")
        return None


def _readonly_tree(root: Path) -> None:
    """sync 사본의 쓰기 비트 제거 (a-w).

    워커가 NFS 런타임 사본을 직접 고쳐 "정본 반영"으로 위장하는 가짜 done 차단
    (INFRA-ISSUE-298) — 정본 수정은 i-tems/hive PR 로만. 다음 sync 의 교체·prune 은
    _rmtree_rw 가 쓰기 비트를 되살려 지운다.
    """
    for p in (root, *root.rglob("*")):
        p.chmod(p.stat().st_mode & ~0o222)


def _rmtree_rw(path: Path) -> None:
    """read-only sync 사본(_readonly_tree)도 지울 수 있는 rmtree — 쓰기 비트 복구 후 삭제."""
    for p in (path, *path.rglob("*")):
        try:
            p.chmod(p.stat().st_mode | 0o200)
        except FileNotFoundError:
            pass
    shutil.rmtree(path)


def _sync_tree(*, clone: Path, target: Path, dir_src: str, dirs, files, file_src: str) -> None:
    """clone 하위 트리를 target 으로 atomic-ish 반영 (dir 은 swap, file 은 replace).

    소스에 없는 관리 dir 은 target 에서 제거(mirror/prune) — 옛 잔재(예: rules 가 ruler
    inline 이관으로 사라진 경우)가 NFS 에 남아 이중 로드되는 것을 막는다. dir_src/file_src
    는 clone 기준 prefix (""=clone 루트). 반영된 사본은 read-only (_readonly_tree).
    """
    target.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        src = (clone / dir_src / d) if dir_src else (clone / d)
        dst = target / d
        if not src.is_dir():
            if dst.is_dir() and not dst.is_symlink():
                _rmtree_rw(dst)
            continue
        dst_new = target / f".{d}.new"
        if dst_new.exists():
            _rmtree_rw(dst_new)
        shutil.copytree(src, dst_new)
        _readonly_tree(dst_new)
        if dst.is_symlink():
            dst.unlink()
        elif dst.exists():
            _rmtree_rw(dst)
        dst_new.rename(dst)
    for fname in files:
        fsrc = (clone / file_src / fname) if file_src else (clone / fname)
        if not fsrc.is_file():
            continue
        fdst = target / fname
        fdst_new = target / f".{fname}.new"
        fdst_new.unlink(missing_ok=True)  # 잔재 .new 가 read-only 일 수 있음
        shutil.copy2(fsrc, fdst_new)
        fdst_new.chmod(fdst_new.stat().st_mode & ~0o222)
        fdst_new.replace(fdst)


def sync_hive_repo(reason: str, *, force: bool = False) -> str | None:
    """i-tems/hive 를 NFS HOME 에 sync. agent/worker pod 이 NFS HOME 에서 그대로 read.

    bootstrap(force=True) 은 무조건 sync, poller(force=False) 는 ls-remote HEAD 가
    마지막 sync SHA 와 다를 때만 clone+swap. 반영한 HEAD SHA 반환 (skip/실패 시 None).
    오류 시 호출자를 막지 않음 — 기존 NFS 내용이 있으면 그걸로 동작 (망실 시에만 문제).
    """
    global _last_synced_sha
    url = _hive_repo_auth_url()
    if url is None:
        if force:
            log.warning("[hive-repo] HIVE_REPO_TOKEN 미설정 — sync 스킵 (NFS 기존 내용 사용)")
        return None

    remote_sha = _remote_head_sha(url)
    if not force:
        if remote_sha is None:
            return None  # poll tick: ls-remote 실패 → 이번 tick skip
        if remote_sha == _last_synced_sha:
            return remote_sha  # 변경 없음 — clone/swap 안 함

    try:
        with tempfile.TemporaryDirectory(prefix="hive-repo-") as tmp:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", url, tmp],
                check=True, capture_output=True, text=True, timeout=60,
            )
            if remote_sha is None:
                # ls-remote 실패했지만 force clone 성공 — clone HEAD 로 baseline 설정.
                try:
                    remote_sha = subprocess.run(
                        ["git", "-C", tmp, "rev-parse", "HEAD"],
                        check=True, capture_output=True, text=True, timeout=10,
                    ).stdout.strip()
                except Exception:
                    remote_sha = None
            # .claude (Claude Code) — dir 은 mirror(prune 포함), CLAUDE.md 는 replace.
            _sync_tree(clone=Path(tmp), target=HIVE_REPO_SYNC_TARGET,
                       dir_src=".claude", dirs=HIVE_REPO_SYNC_DIRS,
                       file_src=".claude", files=HIVE_REPO_SYNC_FILES)
            # .codex (OpenAI Codex CLI) — .codex/skills + 루트 AGENTS.md → ~/.codex/.
            _sync_tree(clone=Path(tmp), target=HIVE_CODEX_SYNC_TARGET,
                       dir_src=".codex", dirs=HIVE_CODEX_SYNC_DIRS,
                       file_src="", files=HIVE_CODEX_SYNC_FILES)
            # agent-중립 계약(specs/schemas) — repo-root → /data/shared/ 직하 (양 백엔드 공유).
            # repo-root 에 아직 없으면(전환 전) src 부재로 no-op.
            _sync_tree(clone=Path(tmp), target=HIVE_NEUTRAL_SYNC_TARGET,
                       dir_src="", dirs=HIVE_NEUTRAL_SYNC_DIRS,
                       file_src="", files=())
            _last_synced_sha = remote_sha
            log.info(
                f"[hive-repo] sync 완료 ({reason}, HEAD={(remote_sha or '?')[:8]}): "
                f".claude[{', '.join(HIVE_REPO_SYNC_DIRS)} + {', '.join(HIVE_REPO_SYNC_FILES)}] "
                f"+ .codex[{', '.join(HIVE_CODEX_SYNC_DIRS)} + {', '.join(HIVE_CODEX_SYNC_FILES)}] "
                f"+ neutral[{', '.join(HIVE_NEUTRAL_SYNC_DIRS)}]"
            )
            return remote_sha
    except subprocess.CalledProcessError as exc:
        log.warning(f"[hive-repo] git clone 실패: {exc.stderr.strip() if exc.stderr else exc}")
    except Exception as exc:
        log.warning(f"[hive-repo] sync 실패: {exc}", exc_info=True)
    return None


def _bootstrap_db() -> None:
    """MySQL 스키마 보장."""
    try:
        db.init_schema()
    except Exception as exc:
        log.error(f"[db] schema init 실패: {exc}", exc_info=True)
        raise
