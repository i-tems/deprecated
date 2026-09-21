FROM ubuntu:24.04
# rebuild trigger: registry :main manifest 가 GC 로 inner blob 사라져 stale 인덱스 상태.
# 이 Dockerfile 변경으로 build-apps 가 fresh 이미지 push → :main 정상화.

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml /tmp/framework/pyproject.toml
COPY capability_framework /tmp/framework/capability_framework
RUN pip install --no-cache-dir /tmp/framework \
 && rm -rf /tmp/framework

EXPOSE 8000
# rebuild trigger 1777864448
