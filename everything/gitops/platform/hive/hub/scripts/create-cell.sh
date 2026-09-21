#!/usr/bin/env bash
# 새 hive cell 생성 한방 스크립트 (meta 통합 모델 기준 — 전 단계 멱등).
#
# meta 소스 바인딩은 순수 컨벤션(ns==레포 basename, 허용=cell-*)이라
# meta 설정 변경이 필요 없다 — cell 레포 이름만으로 자동 매칭된다.
#
# 흐름:
#   1. PAT 을 hive-cell-tokens Secret 에 추가 (이미 있으면 no-op)
#   2. git commit + push  (ArgoCD 가 Secret 동기화)
#   3. hive-hub Application hard refresh
#   4. Secret 에 cell key 등장까지 폴링
#   5. port-forward + caller token + POST /cell.create → /cell.list 검증
#   6. Gitea pull-mirror 생성(private→PAT) + Actions 활성화 + 초기 mirror-sync
#   7. POST /deployment.cell_register (ArgoCD AppProject + Gitea notify webhook)
#   8. GitHub webhook → hub-webhook/cell.github_push (멱등)
#   9. cell repo 가 비어 있으면 baseline 시드 (.claude / cell.json /
#      knowledge / .gitea/workflows/meta-sync.yml) — 마지막 push 가 전체
#      파이프라인(빌드+meta /sync/git) 발화
#
# 전제: kubectl(클러스터), git push 권한(everything), gh(GitHub webhook용,
#       repo admin), gitea.lab.i-tems.com LAN 도달.
#
# 사용 예:
#   hub/scripts/create-cell.sh \
#     --cell-id pen \
#     --name pen \
#     --repo-url https://github.com/i-tems/cell-pen.git \
#     --pat ghp_xxx \
#     --emails dahuin000@gmail.com

set -euo pipefail

usage() {
  sed -n '2,28p' "$0" >&2
  exit 1
}

CELL_ID="" NAME="" REPO_URL="" PAT="" EMAILS="" DESC=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cell-id)     CELL_ID="$2"; shift 2 ;;
    --name)        NAME="$2"; shift 2 ;;
    --repo-url)    REPO_URL="$2"; shift 2 ;;
    --pat)         PAT="$2"; shift 2 ;;
    --emails)      EMAILS="$2"; shift 2 ;;
    --description) DESC="$2"; shift 2 ;;
    -h|--help)     usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[ -n "$CELL_ID" ] && [ -n "$NAME" ] && [ -n "$REPO_URL" ] && [ -n "$PAT" ] && [ -n "$EMAILS" ] || usage

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SECRET_YAML="$SCRIPT_DIR/../manifests/secret-cell-tokens.yaml"
META_SYNC_TMPL="$SCRIPT_DIR/../../../meta/client/meta-sync.gitea.yml"
REPO_ROOT=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)

# i-tems/cell-pen.git → owner=i-tems repo=cell-pen
GH_OWNER=$(printf '%s' "$REPO_URL" | sed -E 's#.*github.com[:/]+([^/]+)/.*#\1#')
GH_REPO=$(printf '%s' "$REPO_URL" | sed -E 's#.*/([^/]+)$#\1#; s#\.git$##')
GITEA="https://gitea.lab.i-tems.com"

step() { echo "[$1/9] $2"; }
ksecret() { kubectl get secret hive-hub -n hive -o jsonpath="{.data.$1}" | base64 -d; }

# --- 1. yaml patch: PAT secret (멱등) ---
step 1 "Secret 에 $CELL_ID PAT 추가/갱신"
python3 - "$SECRET_YAML" "$CELL_ID" "$PAT" <<'PY'
import re, sys
path, cid, pat = sys.argv[1:4]
with open(path) as f:
    text = f.read()
pat_re = re.compile(rf"^(\s*{re.escape(cid)}:\s).*$", re.M)
if pat_re.search(text):
    text = pat_re.sub(rf"\g<1>{pat}", text)
else:
    text = text.rstrip() + f"\n  {cid}: {pat}\n"
with open(path, "w") as f:
    f.write(text)
PY

# --- 2. commit + push ---
step 2 "commit + push (secret)"
git -C "$REPO_ROOT" add "$SECRET_YAML"
if ! git -C "$REPO_ROOT" diff --cached --quiet; then
  git -C "$REPO_ROOT" commit -m "feat(hive): $CELL_ID cell PAT 추가"
  git -C "$REPO_ROOT" push
else
  echo "  변경 없음 (이미 동일 값)"
fi

# --- 3. ArgoCD refresh ---
step 3 "hive-hub Application hard refresh"
kubectl annotate application hive-hub -n argocd \
  argocd.argoproj.io/refresh=hard --overwrite >/dev/null

# --- 4. Secret sync 대기 ---
step 4 "Secret 에 $CELL_ID key 등장 대기 (≤ 120s)"
ok_secret=0
for _ in $(seq 1 60); do
  keys=$(kubectl get secret hive-cell-tokens -n hive -o jsonpath='{.data}' \
    | python3 -c 'import sys,json;print(" ".join(json.load(sys.stdin).keys()))')
  if echo " $keys " | grep -q " $CELL_ID "; then echo "  secret OK"; ok_secret=1; break; fi
  sleep 2
done
[ "$ok_secret" = 1 ] || { echo "  timeout: $CELL_ID 가 Secret 에 안 생김" >&2; exit 1; }

# --- 5. port-forward + cell.create + verify ---
step 5 "port-forward + cell.create"
kubectl port-forward -n hive svc/hive-hub 18000:8000 >/dev/null 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
  if curl -sf -o /dev/null http://localhost:18000/health; then break; fi
  sleep 0.25
done

INTERNAL=$(kubectl get secret hive-hub -n hive -o jsonpath='{.data.HUB_INTERNAL_TOKEN}' | base64 -d)
TOKEN=$(curl -sf -X POST http://localhost:18000/auth.caller_token \
  -H "Content-Type: application/json" -H "X-Internal-Token: $INTERNAL" \
  -d "{\"principal_type\":\"cli\",\"principal_id\":\"cli:create-cell\",\"cell_id\":\"$CELL_ID\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["token"])')

PAYLOAD=$(CELL_ID="$CELL_ID" NAME="$NAME" DESC="$DESC" REPO_URL="$REPO_URL" EMAILS="$EMAILS" \
  python3 -c '
import json, os
emails = [e.strip().lower() for e in os.environ["EMAILS"].split(",") if e.strip()]
print(json.dumps({
    "cell_id": os.environ["CELL_ID"],
    "name": os.environ["NAME"],
    "description": os.environ.get("DESC") or None,
    "repo_url": os.environ["REPO_URL"],
    "allowed_emails": emails,
}))')

# cell.create 는 already_exists 면 멱등 skip
CREATE=$(curl -s -X POST http://localhost:18000/cell.create \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$PAYLOAD")
echo "$CREATE" | python3 -c '
import sys, json
d = json.load(sys.stdin)
if d.get("status") == "ok":
    print("  cell.create OK")
elif d.get("error_code") == "already_exists":
    print("  cell 이미 존재 — skip")
else:
    print("  cell.create FAIL:", json.dumps(d, ensure_ascii=False)); sys.exit(1)
'

step 5 "cell.list 검증"
curl -sf -X POST http://localhost:18000/cell.list \
  -H "Authorization: Bearer $TOKEN" -H "X-Cell-Id: $CELL_ID" \
  -H "Content-Type: application/json" -d '{}' \
  | CELL_ID="$CELL_ID" python3 -c '
import json, os, sys
d = json.load(sys.stdin)["data"]
cid = os.environ["CELL_ID"]
hit = next((c for c in d["cells"] if c["cell_id"] == cid), None)
if not hit:
    print(f"FAIL: {cid} not in list", file=sys.stderr); sys.exit(1)
print("  OK status={s} repo={r}".format(s=hit["status"], r=hit["repo_url"]))
'

# --- 6. Gitea pull-mirror + Actions (멱등) ---
step 6 "Gitea pull-mirror 생성 + Actions 활성화"
GT=$(ksecret HUB_GITEA_ADMIN_TOKEN)
if curl -sf -o /dev/null -H "Authorization: token $GT" \
     "$GITEA/api/v1/repos/$GH_OWNER/$GH_REPO" 2>/dev/null; then
  echo "  미러 이미 존재 — migrate skip"
else
  curl -s -o /dev/null -w "  migrate -> %{http_code}\n" -XPOST \
    "$GITEA/api/v1/repos/migrate" -H "Authorization: token $GT" \
    -H 'content-type: application/json' -d "{
      \"clone_addr\":\"https://x-access-token:${PAT}@github.com/${GH_OWNER}/${GH_REPO}.git\",
      \"repo_owner\":\"$GH_OWNER\",\"repo_name\":\"$GH_REPO\",
      \"mirror\":true,\"mirror_interval\":\"30m\",\"private\":true,\"service\":\"git\"}"
fi
# 신규 미러는 Actions off 기본 — 멱등 활성화 + 초기 sync
curl -s -o /dev/null -w "  actions enable -> %{http_code}\n" -XPATCH \
  "$GITEA/api/v1/repos/$GH_OWNER/$GH_REPO" -H "Authorization: token $GT" \
  -H 'content-type: application/json' -d '{"has_actions":true}'
curl -s -o /dev/null -w "  mirror-sync -> %{http_code}\n" -XPOST \
  "$GITEA/api/v1/repos/$GH_OWNER/$GH_REPO/mirror-sync" -H "Authorization: token $GT"

# --- 7. deployment.cell_register (AppProject + Gitea notify webhook) ---
step 7 "deployment.cell_register"
curl -sf -X POST http://localhost:18000/deployment.cell_register \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"cell_id\":\"$CELL_ID\"}" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  ",json.dumps(d.get("data",d),ensure_ascii=False))'

# --- 8. GitHub webhook → cell.github_push (멱등) ---
step 8 "GitHub webhook 등록"
WH_SECRET=$(ksecret HUB_CELL_WEBHOOK_SECRET)
WH_URL="https://hub-webhook.i-tems.com/cell.github_push?owner=${GH_OWNER}&repo=${GH_REPO}"
EXIST=$(gh api "repos/$GH_OWNER/$GH_REPO/hooks" \
  --jq ".[]|select(.config.url==\"$WH_URL\")|.id" 2>/dev/null || true)
if [ -n "$EXIST" ]; then
  echo "  webhook 이미 존재 (id=$EXIST) — skip"
else
  printf '{"name":"web","active":true,"events":["push"],"config":{"url":"%s","content_type":"json","secret":"%s"}}' \
    "$WH_URL" "$WH_SECRET" \
    | gh api -X POST "repos/$GH_OWNER/$GH_REPO/hooks" --input - \
        --jq '"  webhook 생성 id="+(.id|tostring)' 2>&1 | tail -1
fi

# --- 9. seed baseline (idempotent) ---
step 9 "cell repo 베이스라인 시드 (incl meta-sync 워크플로)"
SEED_DIR=$(mktemp -d)
trap 'rm -rf "$SEED_DIR"; kill $PF_PID 2>/dev/null || true' EXIT

CLONE_URL=$(REPO_URL="$REPO_URL" PAT="$PAT" python3 -c '
import os
url, pat = os.environ["REPO_URL"], os.environ["PAT"]
scheme, rest = url.split("://", 1)
print(f"{scheme}://x-access-token:{pat}@{rest}")')

git clone --quiet "$CLONE_URL" "$SEED_DIR/repo" 2>&1 | grep -v "warning: You appear" || true

if [ -n "$(ls -A "$SEED_DIR/repo" 2>/dev/null | grep -v '^.git$')" ]; then
  echo "  이미 파일 존재 — skip"
else
  cd "$SEED_DIR/repo"
  mkdir -p .claude knowledge .gitea/workflows
  echo '{}' > .claude/settings.json
  echo '{}' > cell.json
  sed "s/__CELLID__/$CELL_ID/g" "$META_SYNC_TMPL" > .gitea/workflows/meta-sync.yml
  cat > README.md <<MD
# cell-$CELL_ID

Hive cell repository for **$CELL_ID**.

${DESC:-}

## 구조

- \`.claude/\` — cell-specific Claude project config
- \`cell.json\` — capability config + key + 그 외 cell 설정 (정본).
  워커가 부팅 시 \`/data/cells/$CELL_ID/cell.json\` 으로 미러링.
- \`knowledge/\` — 누적 지식·결정·핸드오프 (markdown)
- \`.gitea/workflows/meta-sync.yml\` — push 시 이미지 빌드 + meta /sync/git

워커가 부팅 시 이 repo 를 emptyDir 에 shallow clone 해 사용합니다.
MD
  cat > knowledge/README.md <<'MD'
# Knowledge

이 디렉토리에는 cell 의 누적 지식, 의사결정 로그, 핸드오프 문서가 들어갑니다.
워커가 task 실행 시 컨텍스트로 참조합니다.
MD
  git -c user.email=hive-bot@i-tems.com -c user.name=hive-bot \
      -C . checkout -q -b main 2>/dev/null || git -C . checkout -q main
  git -C . add .
  git -c user.email=hive-bot@i-tems.com -c user.name=hive-bot \
      -C . commit -q -m "feat: initial baseline (.claude / cell.json / knowledge / meta-sync)"
  git -C . push -q -u origin main
  cd "$REPO_ROOT"
  echo "  pushed baseline"
fi

echo
echo "✅ Cell '$CELL_ID' ready (meta 통합 모델 전 단계 완료)."
