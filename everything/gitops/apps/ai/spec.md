# ai.i-tems.com

Google OAuth으로 보호된 Claude Code Opus 웹 프론트엔드.

## 요약

- 페이지 1장. 프롬프트 입력 → SSE로 실시간 응답 스트리밍
- 백엔드 FastAPI가 `claude -p` subprocess 실행 (stdin으로 프롬프트 전달)
- 파일 첨부(이미지/텍스트/PDF/CSV 등) 지원 — 요청별 `/tmp/ai-uploads/{uuid}/` 저장, 응답 후 삭제
- 매 요청 독립 (멀티턴 없음)

## 보안

- Google OAuth + `ALLOWED_EMAILS` 화이트리스트 (기본 `dahuin000@gmail.com`)
- JWT(HS256) httpOnly + Secure + SameSite=Lax 세션 쿠키 (1주)
- OAuth state 쿠키 검증 (CSRF 방지)
- 프롬프트는 stdin (shell injection 불가)
- claude 플래그: `--bare --disable-slash-commands --permission-mode default`
  - 파일 없으면 `--tools ""` (도구 전부 OFF)
  - 파일 있으면 `--tools "Read" --add-dir {upload_dir}` (Read만 허용)
- 응답 헤더: `X-Robots-Tag: noindex, nofollow`, `X-Content-Type-Options: nosniff`

## 제한 (환경변수)

| 변수 | 기본값 | 의미 |
|------|--------|------|
| MAX_CONCURRENT | 3 | 동시 실행 수 |
| MAX_USD_PER_DAY | 80 | 계정별 일일 누적 비용 상한($). `_stats.json` today.cost 기반, 초과 시 429 (영속 — 재시작에도 유지) |
| MAX_PROMPT_CHARS | 50000 | 프롬프트 길이 상한 |
| MAX_UPLOAD_MB | 10 | 파일당 크기 상한 |
| REQUEST_TIMEOUT_SEC | 600 | subprocess 타임아웃 |

## 배포

```bash
cd /root/code/data-product/ai
cp .env.example .env
# .env에 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET 채움
docker compose up -d --build
```

### nginx-proxy 추가

`/root/code/platform/nginx-proxy/nginx.conf`에 다음 블록 추가 후 `docker compose restart` (nginx-proxy).

```nginx
# ai.i-tems.com -> ai (port 8005)
server {
    listen 443 ssl;
    server_name ai.i-tems.com;
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    location / {
        proxy_pass http://host.docker.internal:8005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 610s;
        proxy_http_version 1.1;
    }
}
```

### Google Cloud Console

OAuth 2.0 클라이언트(meetup-scheduler 재사용)의 Authorized redirect URIs에
`https://ai.i-tems.com/auth/callback` 추가 필요.

## 디렉토리

```
ai/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  spec.md
  app/
    __init__.py
    main.py       # FastAPI + /api/ask (SSE) + quota + 파일 업로드
    auth.py       # Google OAuth + JWT + 화이트리스트
    runner.py     # claude subprocess + stream-json -> SSE
    static/
      index.html
      app.js      # marked + highlight.js + DOMPurify
      style.css
```
