"""Cell/Generated repo에 파일을 commit·push하는 helper.

hub 의 여러 호출자(issue preview·worker·hive-repo sync 등)가 cell 또는
generated repo를 임시 디렉터리에 clone → 파일 쓰기 → commit → push 한다.

토큰은 ps/log에 노출되지 않도록 URL inline에만 사용하고 환경변수로 전달하지 않는다
(remote URL 자체에 토큰이 박히지만 remote URL은 임시 디렉터리에서만 살고 push 후
디렉터리 삭제되므로 잔존 X).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


GIT_USER_NAME = os.environ.get("HUB_GIT_USER_NAME", "hive-hub")
GIT_USER_EMAIL = os.environ.get("HUB_GIT_USER_EMAIL", "hive-hub@i-tems.com")


@contextmanager
def repo_clone(repo_url: str, token: str, *, branch: str = "main", depth: int = 50,
               prefix: str = "hub-repo-", prefer_mirror: bool = False):
    """임의 repo 를 shallow clone. cell repo 는 prefix='hub-cell-' 로 호출.

    prefer_mirror=True: GitHub URL 이면 in-cluster Gitea mirror 로 clone 해서
    GitHub git protocol 부담을 0 으로. push 가 필요한 호출자 (worker 등)
    는 False (default) 로 두고 정본인 GitHub 로 직접 clone. mirror 매핑이 안 되는
    URL (Gitea 정본 cell — URL 자체가 gitea.lab.i-tems.com) 은 자동으로 그대로 통과.

    yield: (workdir Path, authed_url str) — authed_url 은 *push 가능한 원본 URL*.
    mirror 에서 clone 했더라도 origin 을 원본 URL 로 바꿔두므로 호출자가 동일하게
    `git push origin HEAD:branch` 가능.
    """
    if "://" not in repo_url:
        raise ValueError(f"invalid repo_url: {repo_url!r}")

    # mirror 라우팅 — read-only 흐름이면 Gitea mirror URL 로 clone, push 시점엔
    # origin 을 원본으로 되돌려 준다. mirror 매핑이 없으면 원본 그대로.
    clone_url = repo_url
    clone_token = token
    if prefer_mirror:
        try:
            from . import gitea_mirror
            mapped = gitea_mirror.to_gitea_clone_url(repo_url)
            if mapped:
                clone_url = mapped
                clone_token = os.environ.get("HUB_GITEA_ADMIN_TOKEN", "").strip() or token
        except Exception:
            pass  # mapping 실패 시 GitHub 직접 clone fallback

    scheme, rest = clone_url.split("://", 1)
    authed_clone_url = f"{scheme}://x-access-token:{clone_token}@{rest}"
    # push 용 origin URL — 항상 원본 (정본 GitHub) 인증 토큰 사용
    push_scheme, push_rest = repo_url.split("://", 1)
    authed_push_url = f"{push_scheme}://x-access-token:{token}@{push_rest}"

    tmpdir = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        subprocess.run(
            ["git", "clone", "--depth", str(depth), "--branch", branch,
             authed_clone_url, str(tmpdir / "src")],
            check=True, capture_output=True, text=True, timeout=60,
        )
        workdir = tmpdir / "src"
        subprocess.run(["git", "config", "user.name", GIT_USER_NAME], check=True, cwd=workdir)
        subprocess.run(["git", "config", "user.email", GIT_USER_EMAIL], check=True, cwd=workdir)
        # mirror 에서 clone 했어도 push 는 원본 정본으로 가도록 origin URL 갈아끼움.
        if prefer_mirror and clone_url != repo_url:
            subprocess.run(
                ["git", "remote", "set-url", "origin", authed_push_url],
                check=True, cwd=workdir,
            )
        yield workdir, authed_push_url
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def write_files(workdir: Path, files: dict[str, str]) -> list[str]:
    """workdir 기준 상대경로 → 내용 매핑을 디스크에 쓴다. 디렉터리는 자동 생성.

    반환: 새로 생성됐거나 변경된 파일들의 상대경로.
    """
    written: list[str] = []
    for rel, content in files.items():
        if rel.startswith("/") or ".." in Path(rel).parts:
            raise ValueError(f"unsafe path: {rel!r}")
        path = workdir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text() if path.exists() else None
        if existing != content:
            path.write_text(content)
            written.append(rel)
    return written


def commit_push(workdir: Path, *, message: str, branch: str = "main") -> dict:
    """workdir의 변경사항을 commit·push. 변경 없으면 no-op.

    반환: {pushed: bool, commit: str|None}
    """
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True, cwd=workdir, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return {"pushed": False, "commit": None, "note": "no changes"}

    subprocess.run(["git", "add", "-A"], check=True, cwd=workdir)
    subprocess.run(["git", "commit", "-m", message], check=True, cwd=workdir, capture_output=True, text=True)
    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True, cwd=workdir, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "push", "origin", f"HEAD:{branch}"],
        check=True, cwd=workdir, capture_output=True, text=True, timeout=60,
    )
    return {"pushed": True, "commit": rev}
