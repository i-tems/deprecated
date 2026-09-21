#!/usr/bin/env bash
# kaniko 가 push 할 registry-docker-config secret 을 hive ns 에 생성/갱신한다.
# build_runner 가 BUILDER_REGISTRY_SECRET 환경변수로 이 secret 을 mount 한다.
#
# 자격은 lab default `items:items` 를 hardcoded — 변경 시 CREDS 환경변수 override.
# (이전에는 image-updater-registry-creds 에서 읽었으나 image-updater 가 제거되어
# self-contained 로 변경.)
#
# 일회성 실행. 자격이 변경되면 다시 실행하면 된다.
#
# 사용:
#   bash gitops/platform/hive/hub/scripts/setup-builder-registry-secret.sh
#
# 환경:
#   REGISTRY: registry hostname (default: registry.lab.i-tems.com)
#   CREDS: "user:pass" (default: items:items)
#   TARGET_NS: target namespace (default: hive)
#   TARGET_SECRET: target secret name (default: registry-docker-config)

set -euo pipefail

REGISTRY="${REGISTRY:-registry.lab.i-tems.com}"
CREDS="${CREDS:-items:items}"
TARGET_NS="${TARGET_NS:-hive}"
TARGET_SECRET="${TARGET_SECRET:-registry-docker-config}"

if [[ "$CREDS" != *:* ]]; then
  echo "ERROR: CREDS must be 'user:pass' format" >&2
  exit 1
fi

auth_b64=$(printf '%s' "$CREDS" | base64 -w0)
dockerconfig=$(printf '{"auths":{"%s":{"auth":"%s"}}}' "$REGISTRY" "$auth_b64")
dockerconfig_b64=$(printf '%s' "$dockerconfig" | base64 -w0)

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: ${TARGET_SECRET}
  namespace: ${TARGET_NS}
type: Opaque
data:
  .dockerconfigjson: ${dockerconfig_b64}
EOF

echo "OK: ${TARGET_NS}/${TARGET_SECRET} created/updated for ${REGISTRY}"
