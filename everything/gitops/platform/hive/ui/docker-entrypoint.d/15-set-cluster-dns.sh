#!/bin/sh
# /etc/resolv.conf 의 첫 nameserver를 nginx resolver로 주입.
# k8s 내에서는 cluster DNS(coredns)의 ClusterIP가 들어 있다.
set -eu

CLUSTER_DNS="$(awk '/^nameserver /{print $2; exit}' /etc/resolv.conf)"
if [ -z "${CLUSTER_DNS:-}" ]; then
  echo >&2 "[15-set-cluster-dns] no nameserver in /etc/resolv.conf, falling back to 8.8.8.8"
  CLUSTER_DNS="8.8.8.8"
fi
echo "[15-set-cluster-dns] using $CLUSTER_DNS as nginx resolver"

# nginx:alpine 의 envsubst 단계는 *.template 을 conf로 만들지만, 우리는 sed 한 방으로 끝냄.
# default.conf.template → default.conf
sed -e "s/__CLUSTER_DNS__/${CLUSTER_DNS}/g" \
    /etc/nginx/conf.d/default.conf.template \
    > /etc/nginx/conf.d/default.conf
