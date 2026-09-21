# hive-term

브라우저 안 hive UI 터미널(xterm.js 드로어) 대신 **내 로컬 터미널**로 hive
sandbox 에 붙는다. pod 안 공유 tmux 세션(`hive`)에 attach 하므로 웹 UI 에서
열던 claude/셸 세션에 **그대로 이어 붙는다** — 둘은 같은 세션이다. tmux·복붙·
스크롤백·폰트가 전부 네이티브 터미널 그대로 동작한다.

## 가장 쉬운 길: 콘솔의 🔑 버튼 (원클릭)

콘솔 터미널 드로어 헤더의 **🔑 버튼**을 누르면 "받아서 실행" 스니펫이 클립보드에
복사된다. 로컬 터미널에 **붙여넣기 1회**면 끝 — hive-term 을 콘솔에서 받아 토큰과
함께 현재 보고 있는 세션에 attach 한다. 파일을 따로 받을 필요가 없다.

```bash
# 🔑 가 복사해주는 내용 (붙여넣기만):
export HIVE_AUTH_TOKEN='<자동>'
cloudflared access curl https://hive.tunnel.i-tems.com/hive-term -fsSL -o /tmp/hive-term \
  && python3 /tmp/hive-term attach <현재-세션-id> --cell <cell>
```

전제: `cloudflared` 1회 로그인(`cloudflared access login https://hive.tunnel.i-tems.com`),
Python 3.10+. 그 외 의존성 0.

## 설치 (수동/영구)

**의존성 0이다 — 파일 하나만 있으면 된다.** `src/hive_term/__init__.py` 를
`hive-term` 으로 저장하고 바로 실행한다 (Python 3.10+ 면 끝, pip·PyPI·venv 불필요).
콘솔이 같은 파일을 `https://hive.tunnel.i-tems.com/hive-term` 으로도 서빙한다:

```bash
# 파일 받아서 실행
chmod +x hive-term
./hive-term attach --name mywork
# 또는
python3 hive-term attach --name mywork
```

off-network(사내 PyPI 미도달) 사용자는 이 파일 전달 방식이 기본이다. PATH 에 두면
어디서나 `hive-term`:

```bash
install -m 755 hive-term ~/.local/bin/hive-term
```

사내망/VPN 이면 사내 PyPI 로도 설치 가능(머지 시 자동 퍼블리시):

```bash
uv tool install hive-term --index-url https://pypi.lab.i-tems.com/simple/
```

`cloudflared` 만 별도로 필요하다 (엣지 Cloudflare Access 통과용):

```bash
brew install cloudflared   # macOS
```

## 인증 (최초 1회 + 토큰 만료 시)

두 겹을 통과해야 한다.

### 1) Cloudflare Access — 엣지 직원 게이트

```bash
cloudflared access login https://hive.tunnel.i-tems.com
```

브라우저로 **기존과 똑같은 Google SSO** 가 뜨고, 성공하면 토큰이 로컬에 캐시된다.
hive 콘솔을 브라우저로 열 수 있는 사람이면 누구나 그대로 된다(관리자 발급 불필요).
세션 TTL(보통 24h) 지나면 이 명령만 다시.

### 2) console JWT — 앱단 owner 인증

sandbox 의 owner(= JWT 의 이메일)와 일치해야 한다. 셋 중 하나:

```bash
export HIVE_AUTH_TOKEN='<jwt>'              # 환경변수
# 또는 ~/.config/hive/token 파일에 한 줄
# 또는 --token '<jwt>'
```

토큰 얻는 법 (둘 중 하나):
- **콘솔 터미널 드로어 헤더의 🔑 버튼** → 클립보드에 복사 (권장).
- 또는 브라우저 devtools → Application → Cookies → `auth_token` 값 복사.

## 사용

```bash
# 내 sandbox 목록
hive-term list

# id 로 붙기
hive-term attach sandbox-1a2b3c4d

# 이름 붙은 sandbox (없으면 자동 생성, 영속 claude 대화)
hive-term attach --name mywork

# entity steering 세션 자동 생성하며 붙기
hive-term attach --name issue-INFRA-307 --entity-type issue --entity-id INFRA-ISSUE-307

# 생성만
hive-term create --name mywork --ttl 4
```

떼기(detach)는 tmux 키 **`Ctrl-b d`** — 세션은 pod 안에 살아 있어 다음에 다시 붙으면
그대로다(웹 UI 에서 다시 열어도 같은 세션).

## 옵션

| 플래그 | 기본 | 설명 |
|--------|------|------|
| `--host` | `hive.tunnel.i-tems.com` (`HIVE_HOST`) | 콘솔 호스트 |
| `--cell` | `$CELL_ID` (`HIVE_CELL`) | 대상 cell |
| `--token` | `HIVE_AUTH_TOKEN` → `~/.config/hive/token` | console JWT |

옵션은 서브커맨드 앞/뒤 어디든 둘 수 있다 (`hive-term attach <id> --cell infra` = `hive-term --cell infra attach <id>`).

## 문제 해결

| 증상 | 원인·해결 |
|------|-----------|
| `인증 거부(HTTP 403)` / 리다이렉트 | Cloudflare Access 미인증 → `cloudflared access login https://hive.tunnel.i-tems.com` |
| `인증 거부(close 1008)` | console JWT 만료/owner 불일치 → 🔑 버튼으로 새 토큰 복사해 `HIVE_AUTH_TOKEN` 갱신 |
| `attach 는 TTY 가 필요합니다` | 파이프/리다이렉트로는 불가 — 실제 터미널에서 실행 |
| 즉시 `연결 종료` | sandbox 가 Pending/Failed — `hive-term list` 로 상태 확인, 또는 잠시 후 재시도 |

## 동작 원리

UI 와 **완전히 같은 경로**를 쓴다 — 새 백엔드·새 포트·새 인증 경로 없음:

```
hive-term ──wss──> hive.tunnel.i-tems.com/container/sandbox.ws
            (CF Access[cf-access-token] + Bearer[console JWT])
        nginx ──> hive-capability-container ──k8s exec(TTY)──> pod tmux 'hive'
```

resize 는 UI 와 동일한 in-band 제어 메시지(`__hive_control__:{"type":"resize",…}`).
서버는 `sandbox.ws` 에서 Authorization Bearer 와 `auth_token` 쿠키를 모두 받는다
(브라우저=쿠키, CLI=Bearer).
