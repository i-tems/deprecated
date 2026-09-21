#!/usr/bin/env python3
"""hive-term — 네이티브 터미널에서 hive sandbox 에 붙는 CLI (의존성 0).

브라우저 안 xterm.js 드로어 대신 로컬 터미널(tmux·복붙·스크롤백·폰트 그대로)로
sandbox.ws WebSocket 에 attach 한다. pod 안 공유 tmux 세션(`hive`)을 무므로
웹 UI 에서 열던 claude/셸 세션에 그대로 이어 붙는다 — 둘은 같은 세션이다.

표준 라이브러리만 쓴다 — pip·PyPI·venv 불필요. 파일 하나를 그대로 실행:
    python3 hive_term.py attach --name mywork

인증 2겹:
  1) Cloudflare Access(엣지) — `cloudflared access token` 으로 받은 JWT 를
     cf-access-token 헤더로. 없으면 `cloudflared access login <host>` 안내.
  2) 앱 console JWT — Authorization: Bearer. --token / HIVE_AUTH_TOKEN /
     ~/.config/hive/token 순. owner(=JWT sub)가 sandbox owner 와 일치해야 통과.

명령:
  hive-term attach <id> | --name <name>   sandbox 에 붙기 (핵심)
  hive-term list                          내 sandbox 목록
  hive-term create [--name N] [...]       sandbox 생성
"""
import argparse
import base64
import codecs
import json
import os
import select
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

DEFAULT_HOST = os.environ.get("HIVE_HOST", "hive.tunnel.i-tems.com")
DEFAULT_CELL = os.environ.get("HIVE_CELL") or os.environ.get("CELL_ID") or ""
# 서버(main.py)의 WS_CONTROL_PREFIX 와 동기화. resize in-band 제어.
CONTROL_PREFIX = "__hive_control__:"
TOKEN_FILE = os.path.expanduser("~/.config/hive/token")


# ── 최소 WebSocket 클라이언트 (RFC 6455, stdlib 만) ──────────────────────────
# `websockets` 패키지 의존을 없애 단일 파일이 그대로 돌게 한다. 터미널 스트림에
# 필요한 만큼만 구현 — text/binary 프레임, 클라이언트 마스킹, ping→pong, close,
# 단편(continuation) 재조립.

class WSClosed(Exception):
    def __init__(self, code=None, reason=""):
        super().__init__(f"closed code={code} {reason}".strip())
        self.code = code
        self.reason = reason


class WSHandshakeError(Exception):
    def __init__(self, code, head=""):
        super().__init__(f"handshake HTTP {code}")
        self.code = code
        self.head = head


class _WSConn:
    def __init__(self, sock):
        self.sock = sock
        self._send_lock = threading.Lock()
        self._buf = b""
        self.close_code = None

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSClosed(self.close_code)
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send(self, data, opcode: int = 0x1) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        header = bytearray([0x80 | opcode])
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", n)
        header += mask
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
        with self._send_lock:
            self.sock.sendall(bytes(header) + masked)

    def _recv_frame(self):
        b0, b1 = self._read_exact(2)
        fin = b0 & 0x80
        opcode = b0 & 0x0F
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", self._read_exact(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", self._read_exact(8))[0]
        payload = self._read_exact(ln) if ln else b""
        if b1 & 0x80:  # 서버는 마스킹 안 하지만 방어적으로 해제
            mk, payload = payload[:4], payload[4:]
            payload = bytes(b ^ mk[i & 3] for i, b in enumerate(payload))
        return fin, opcode, payload

    def recv(self):
        """완성된 메시지 한 개를 (opcode, payload) 로. 제어 프레임은 내부 처리."""
        frags = []
        first_op = None
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == 0x9:  # ping → pong
                self.send(payload, opcode=0xA)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                if len(payload) >= 2:
                    self.close_code = struct.unpack("!H", payload[:2])[0]
                raise WSClosed(self.close_code, payload[2:].decode("utf-8", "replace"))
            if opcode == 0x0:  # continuation
                frags.append(payload)
                if fin:
                    return first_op, b"".join(frags)
            else:
                if fin:
                    return opcode, payload
                first_op, frags = opcode, [payload]

    def __iter__(self):
        while True:
            try:
                op, data = self.recv()
            except WSClosed:
                return
            if op == 0x1:
                yield data.decode("utf-8", "replace")
            elif op == 0x2:
                yield data

    def close(self) -> None:
        try:
            with self._send_lock:
                self.sock.sendall(b"\x88\x80" + os.urandom(4))  # masked empty close
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def ws_connect(url: str, headers: dict, timeout: float) -> _WSConn:
    u = urlparse(url)
    secure = u.scheme == "wss"
    host = u.hostname
    port = u.port or (443 if secure else 80)
    path = u.path + (f"?{u.query}" if u.query else "")
    sock = socket.create_connection((host, port), timeout=timeout)
    if secure:
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [
        f"GET {path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket",
        "Connection: Upgrade", f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    for k, v in headers.items():
        lines.append(f"{k}: {v}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())

    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            raise WSHandshakeError(0, "connection closed during handshake")
        resp += chunk
        if len(resp) > 65536:
            raise WSHandshakeError(0, "handshake response too large")
    head, _, rest = resp.partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0].decode("latin-1").split()
    code = int(status[1]) if len(status) > 1 and status[1].isdigit() else 0
    if code != 101:
        raise WSHandshakeError(code, head.decode("latin-1", "replace"))
    conn = _WSConn(sock)
    conn._buf = rest  # 헤더 뒤 잔여 바이트는 이미 WS 스트림
    sock.settimeout(None)
    return conn


# ── 인증 ──────────────────────────────────────────────────────────────────────

def _cf_access_token(host: str):
    """`cloudflared access token` 으로 Access JWT 를 받는다. 없으면 None."""
    try:
        out = subprocess.run(
            ["cloudflared", "access", "token", "--app", f"https://{host}"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    tok = (out.stdout or "").strip()
    # cloudflared 는 미로그인 시 "Unable to find token ..." 를 낸다.
    if not tok or tok.lower().startswith("unable") or " " in tok:
        return None
    return tok


def _app_jwt(arg_token):
    if arg_token:
        return arg_token.strip()
    env = os.environ.get("HIVE_AUTH_TOKEN")
    if env and env.strip():
        return env.strip()
    try:
        with open(TOKEN_FILE) as fp:
            return fp.read().strip() or None
    except OSError:
        return None


def _auth_headers(host: str, jwt):
    """(headers, warnings). cf-access-token·Authorization 을 채우고 누락은 경고."""
    headers, warnings = {}, []
    cf = _cf_access_token(host)
    if cf:
        headers["cf-access-token"] = cf
    else:
        warnings.append(
            f"Cloudflare Access 토큰 없음 — 먼저 실행:\n"
            f"    cloudflared access login https://{host}"
        )
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    else:
        warnings.append(
            "console JWT 없음 — --token, 또는 HIVE_AUTH_TOKEN 환경변수, 또는\n"
            f"    {TOKEN_FILE} 파일에 토큰을 두세요 (브라우저 devtools →\n"
            "    Application → Cookies → auth_token 값)."
        )
    return headers, warnings


# ── REST (list/create) ───────────────────────────────────────────────────────

def _post(host: str, path: str, body: dict, headers: dict, cell: str) -> dict:
    url = f"https://{host}/container/{path}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if cell:
        req.add_header("X-Cell-Id", cell)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        raise SystemExit(f"[{e.code}] {path} 실패: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"{path} 연결 실패: {e.reason}")


def cmd_list(host: str, headers: dict, cell: str) -> int:
    body = _post(host, "sandbox.list", {}, headers, cell)
    if body.get("status") != "ok":
        raise SystemExit(f"list 오류: {body.get('error_code')} {body.get('message','')}")
    items = body.get("data") or []
    if not items:
        print("(sandbox 없음)")
        return 0
    for it in items:
        name = it.get("sandbox_name") or "-"
        ent = it.get("entity_type") or ""
        eid = it.get("entity_id") or ""
        tag = f"{ent}:{eid}" if ent else ""
        print(f"{it.get('id'):<22} {it.get('status','?'):<10} name={name:<16} "
              f"{tag:<20} expires={it.get('expires_at','')}")
    return 0


def cmd_create(host: str, headers: dict, cell: str, args) -> int:
    body = {"ttl_hours": args.ttl, "cpus": args.cpus, "memory_mb": args.memory}
    if args.name:
        body["name"] = args.name
    if args.image:
        body["image"] = args.image
    res = _post(host, "sandbox.create", body, headers, cell)
    if res.get("status") != "ok":
        raise SystemExit(f"create 오류: {res.get('error_code')} {res.get('message','')}")
    d = res.get("data") or {}
    print(f"생성됨: {d.get('id')}  status={d.get('status')}  "
          f"name={d.get('sandbox_name') or '-'}  expires={d.get('expires_at')}")
    print(f"붙기:  hive-term attach {d.get('id')}")
    return 0


# ── attach (WebSocket 터미널) ────────────────────────────────────────────────

def _winsize():
    sz = shutil.get_terminal_size(fallback=(80, 24))
    return sz.columns, sz.lines


def _resize_msg() -> str:
    cols, rows = _winsize()
    return CONTROL_PREFIX + json.dumps({"type": "resize", "cols": cols, "rows": rows})


# 끊겨도 자동 재연결한다 — 서버는 매 연결에서 같은 cwd 의 claude 대화를
# `--continue` 로 재개(또는 named/anon 세션 재진입)하므로 재attach 가 곧 세션
# 복귀다. 깨끗한 종료(close 1000)·owner 거부(1008)·init 실패·사용자가 터미널을
# 닫은 경우엔 재연결하지 않는다. (웹 드로어는 이미 재연결하는데 CLI 만 없어,
# 자리 비운 사이 TCP 가 끊기면 — 랩톱 sleep·네트워크 전환·엣지 recycle — 영구
# detach 되던 문제를 맞춘다. uvicorn 30s ping 은 깨어 있는 idle 만 유지한다.)
RECONNECT_BACKOFF_MAX = 8.0


def _reconnect_wait(target: str, backoff: float) -> float:
    """재연결 전 대기. raw-tty 는 이미 복원된 cooked 모드라 Ctrl-C 로 빠져나갈 수
    있다. 다음 backoff 값을 반환한다."""
    sys.stderr.write(
        f"\x1b[33m연결 끊김 — {backoff:.0f}s 후 재연결… ({target})  "
        "[Ctrl-C 로 종료]\x1b[0m\r\n"
    )
    sys.stderr.flush()
    time.sleep(backoff)
    return min(backoff * 2, RECONNECT_BACKOFF_MAX)


def _attach_session(ws) -> str:
    """raw-tty 로 한 연결을 끝까지 편다. 반환:
    'done'  — 정상 종료(안의 claude/셸 exit) 또는 사용자가 터미널을 닫음 → 멈춤
    'fail'  — owner/인증 거부·init 실패 → 힌트 출력 후 멈춤
    'retry' — 살아있던 세션이 전송단에서 끊김 → 재연결"""
    fd = sys.stdin.fileno()
    old_attr = termios.tcgetattr(fd)
    wake_r, wake_w = os.pipe()
    stop = threading.Event()
    got_data = threading.Event()
    # 디코더는 연결마다 새로 — 끊긴 연결의 멀티바이트 잔여 상태가 다음 연결의 첫
    # 글자를 깨뜨리지 않게 한다.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    user_exit = False

    def reader():
        try:
            for message in ws:
                got_data.set()
                if isinstance(message, bytes):
                    os.write(1, message)
                else:
                    os.write(1, message.encode("utf-8", "replace"))
        except (WSClosed, OSError):
            pass
        finally:
            stop.set()
            try:
                os.write(wake_w, b"x")
            except OSError:
                pass

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()

    # SIGWINCH 핸들러 없이 매 select 틱에서 폭 변화를 폴링해 전송한다 — 핸들러에서
    # ws.send 하면 reader 의 pong 송신과 드물게 경합하므로 메인 스레드로 일원화.
    last_size = (-1, -1)
    try:
        tty.setraw(fd)
        try:
            ws.send(_resize_msg())
        except OSError:
            pass
        last_size = _winsize()
        while not stop.is_set():
            try:
                rlist, _, _ = select.select([fd, wake_r], [], [], 0.25)
            except InterruptedError:
                continue
            cur = _winsize()
            if cur != last_size:
                last_size = cur
                try:
                    ws.send(_resize_msg())
                except OSError:
                    break
            if wake_r in rlist:   # reader 가 깨움 = 원격/전송단이 닫음
                break
            if fd in rlist:
                data = os.read(fd, 4096)
                if not data:       # stdin EOF = 터미널 닫힘 → 사용자 종료
                    user_exit = True
                    break
                text = decoder.decode(data)
                if text:
                    try:
                        ws.send(text)
                    except OSError:
                        break       # 전송단 끊김 — 아래 close_code 로 판정
    finally:
        stop.set()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)
        ws.close()
        os.close(wake_r)
        os.close(wake_w)

    if user_exit:
        sys.stderr.write("\x1b[2m\r\n연결 종료.\x1b[0m\r\n")
        sys.stderr.flush()
        return "done"
    code = ws.close_code
    # 데이터 한 번도 못 받고 닫힘 = 앱단 인증/owner 또는 sandbox init 실패.
    # 재시도해도 안 풀리므로 멈춘다.
    if not got_data.is_set() and code in (1008, 1011):
        if code == 1008:
            sys.stderr.write(
                f"\x1b[33m\r\n인증 거부(close {code}) — console JWT 가 "
                "sandbox owner 와 같은지 확인하세요.\x1b[0m\r\n"
            )
        else:
            sys.stderr.write(
                f"\x1b[31m\r\n연결 실패(close {code}) — sandbox 상태를 "
                "'hive-term list' 로 확인하세요.\x1b[0m\r\n"
            )
        sys.stderr.flush()
        return "fail"
    if code == 1000:
        # 서버가 정상 종료(안의 claude/bash 가 exit). 재연결하지 않는다.
        sys.stderr.write("\x1b[2m\r\n세션 종료.\x1b[0m\r\n")
        sys.stderr.flush()
        return "done"
    # 그 외(1006/1011/None) + 한 번이라도 데이터가 흘렀음 → 전송단 끊김 → 재연결.
    return "retry"


def cmd_attach(host: str, headers: dict, cell: str, args) -> int:
    params = {}
    if args.id:
        params["id"] = args.id
    if args.name:
        params["name"] = args.name
    if cell:
        params["cell_id"] = cell
    if args.workdir:
        params["workdir"] = args.workdir
    if args.entity_type:
        params["entity_type"] = args.entity_type
    if args.entity_id:
        params["entity_id"] = args.entity_id
    # 기본은 콘솔 nginx 경유(wss). HIVE_WS_BASE 로 base 를 덮어쓰면 kubectl
    # port-forward·스테이징 등 대체 경로로 붙을 수 있다 (예: ws://localhost:8000).
    base = os.environ.get("HIVE_WS_BASE") or f"wss://{host}/container"
    url = f"{base}/sandbox.ws?{urlencode(params)}"

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("attach 는 TTY 가 필요합니다 (파이프/리다이렉트 불가).")

    target = args.id or f"name={args.name}"
    sys.stderr.write(f"\x1b[2m연결 중… {target} @ {host}\x1b[0m\r\n")
    sys.stderr.flush()

    live = False        # 한 번이라도 attach 에 성공했나 (= 재연결 대상)
    backoff = 1.0
    while True:
        if live:
            # 자리 비운 사이 Access JWT(엣지)가 만료됐을 수 있다 — 매 재연결마다
            # cf 토큰만 다시 받는다. 앱 console JWT 는 CLI 에서 갱신 불가라 만료 시
            # 1008 로 멈춘다(_attach_session).
            cf = _cf_access_token(host)
            if cf:
                headers["cf-access-token"] = cf

        try:
            ws = ws_connect(url, headers, timeout=30)
        except WSHandshakeError as e:
            if e.code in (401, 403):
                raise SystemExit(
                    f"인증 거부(HTTP {e.code}). Cloudflare Access 로그인 필요:\n"
                    f"    cloudflared access login https://{host}"
                )
            if e.code in (301, 302, 303, 307, 308):
                raise SystemExit(
                    f"리다이렉트(HTTP {e.code}) — Cloudflare Access 미인증으로 보임:\n"
                    f"    cloudflared access login https://{host}"
                )
            if not live:
                raise SystemExit(f"연결 실패(HTTP {e.code or '?'}).")
            backoff = _reconnect_wait(target, backoff)
            continue
        except OSError as e:
            if not live:
                raise SystemExit(f"연결 실패: {e}")
            backoff = _reconnect_wait(target, backoff)
            continue

        if live:
            sys.stderr.write("\x1b[2m재연결됨.\x1b[0m\r\n")
            sys.stderr.flush()
        live = True
        backoff = 1.0
        outcome = _attach_session(ws)
        if outcome == "retry":
            backoff = _reconnect_wait(target, backoff)
            continue
        return 1 if outcome == "fail" else 0


# ── main ─────────────────────────────────────────────────────────────────────

def _add_common(ap, *, suppress: bool) -> None:
    """공통 옵션(--host/--cell/--token)을 메인·서브 파서 양쪽에 달아 서브커맨드
    앞/뒤 어느 위치에 써도 먹게 한다. 서브 파서엔 default=SUPPRESS 로 달아야
    (provide 안 했을 때) 메인 파서가 정한 값을 덮어쓰지 않는다 — argparse 서브파서가
    fresh namespace 로 파싱 후 main 으로 복사하는 동작 때문."""
    SUP = argparse.SUPPRESS
    ap.add_argument("--host", default=(SUP if suppress else DEFAULT_HOST),
                    help=f"콘솔 호스트 (기본 {DEFAULT_HOST})")
    ap.add_argument("--cell", default=(SUP if suppress else DEFAULT_CELL),
                    help="대상 cell (기본 $CELL_ID)")
    ap.add_argument("--token", default=(SUP if suppress else None),
                    help="console JWT (기본 HIVE_AUTH_TOKEN/토큰파일)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="hive-term", description="hive sandbox 네이티브 터미널")
    _add_common(p, suppress=False)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("attach", help="sandbox 에 붙기")
    _add_common(pa, suppress=True)
    g = pa.add_mutually_exclusive_group(required=True)
    g.add_argument("id", nargs="?", help="sandbox id (예: sandbox-1a2b3c4d)")
    g.add_argument("--name", help="이름 붙은 sandbox (없으면 자동 생성)")
    pa.add_argument("--workdir", help="진입 작업 디렉토리 override")
    pa.add_argument("--entity-type", dest="entity_type",
                    choices=["issue", "project", "initiative", "attending", "directing"],
                    help="skill-bound 세션(자동 생성 시)")
    pa.add_argument("--entity-id", dest="entity_id", help="entity 세션 대상 id")

    plist = sub.add_parser("list", help="내 sandbox 목록")
    _add_common(plist, suppress=True)

    pc = sub.add_parser("create", help="sandbox 생성")
    _add_common(pc, suppress=True)
    pc.add_argument("--name", help="재사용할 이름")
    pc.add_argument("--image", help="컨테이너 이미지")
    pc.add_argument("--ttl", type=float, default=2.0, help="TTL 시간 (기본 2)")
    pc.add_argument("--cpus", type=int, default=1)
    pc.add_argument("--memory", type=int, default=1024, help="메모리 MB")

    args = p.parse_args(argv)

    jwt = _app_jwt(args.token)
    headers, warnings = _auth_headers(args.host, jwt)
    if warnings:
        for w in warnings:
            sys.stderr.write("\x1b[33m[경고]\x1b[0m " + w + "\n")

    if args.cmd == "attach":
        return cmd_attach(args.host, headers, args.cell, args)
    if args.cmd == "list":
        return cmd_list(args.host, headers, args.cell)
    if args.cmd == "create":
        return cmd_create(args.host, headers, args.cell, args)
    p.print_help()
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
