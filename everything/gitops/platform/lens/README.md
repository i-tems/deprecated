# lens — AI 생성 대시보드 플랫폼 (post-BI MVP)

고정 BI 빌더(Grafana/Superset) 대신, **에이전트 세션이 대시보드를 spec(JSON)으로
저작·재생성**하고 이 앱은 그 spec 의 SQL 을 `query.sql`(read-only)로 실행해 렌더만
한다. 앱에 LLM/Claude 키 없음 — 생성은 이미 자격증명을 가진 에이전트 세션의 몫.

INFRA-ISSUE-264. PoC `~/everything/metrics_dashboard.html`(정적 스냅샷)을 라이브로
일반화한 것.

## 구조

- `app/main.py` — FastAPI: 대시보드 목록/조회 + `/api/run`(SQL 실행). 정적 SPA 서빙.
- `app/hub_client.py` — hive-caller-creds 로 caller_token 부트스트랩 → `POST /query.sql`.
- `app/sql_guard.py` — read-only 단일 SELECT/WITH 가드 (DDL/DML·다중문 거부).
- `dashboards/*.json` — 대시보드 spec. **새 대시보드 = JSON 한 장 추가** (이 디렉토리).
- `static/index.html` — ECharts 렌더러 SPA.
- `manifests/` — Service/Deployment/Ingress(`lens.tunnel.i-tems.com`). `argocd.yaml`.

## 대시보드 spec 포맷

```json
{
  "id": "metrics-overview",
  "title": "...",
  "description": "...",
  "panels": [
    { "title": "...", "chart": { "type": "line|bar|table", "x": "<col>", "y": ["<col>"] },
      "sql": "SELECT ... (read-only)" }
  ]
}
```

`chart.type=table` 은 x/y 무시하고 컬럼 전체를 표로 렌더. line/bar 는 `x`=카테고리
컬럼, `y`=시리즈 컬럼 목록.

## 데이터 경로

`hive-caller-creds` Secret(`HUB_URL`, `HUB_INTERNAL_TOKEN`)을 envFrom 으로 받아
`/auth.caller_token`(`X-Internal-Token`) 으로 단명 caller JWT 를 얻고, 그 JWT +
`X-Cell-Id` 로 `POST {HUB_URL}/query.sql` 호출. `LENS_CELL`(기본 `infra`)이 cell.
airflow Schedule pod 와 동일 패턴. lens ns 는 hive-caller-creds ApplicationSet
`elements` 에 등록돼 Secret 을 받는다.

## 로컬

```bash
pip install -r requirements.txt
LENS_DASHBOARD_DIR=dashboards uvicorn app.main:app --reload
# /api/run 은 클러스터 내 hub 필요. 가드/목록은 hub 없이 동작.
pytest tests/
```
