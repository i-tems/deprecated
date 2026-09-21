FROM ubuntu:24.04


ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# python3, node 22 (claude-code CLI 의존), git, gh CLI (AI 가 직접 PR 생성·머지),
# tmux (sandbox 터미널이 한 claude 를 여러 WS 연결에서 공유 — container sandbox.ws)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ca-certificates curl gnupg git tmux \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs gh \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# 비루트 agent 사용자 (uid 1000). ubuntu:24.04는 기본 'ubuntu' 사용자가 1000을 차지해 먼저 제거.
RUN userdel -r ubuntu 2>/dev/null || true \
 && groupadd -g 1000 agent \
 && useradd -m -u 1000 -g 1000 -s /bin/bash agent

WORKDIR /opt/agent

# pyproject.toml과 패키지를 함께 복사 후 pip install. start-agent.sh는 별도 경로에 둠.
COPY pyproject.toml /tmp/agent-build/
COPY app /tmp/agent-build/app
COPY start-agent.sh /usr/local/bin/start-agent.sh
COPY bin/task-clone /usr/local/bin/task-clone

# claude-code·codex 는 공급망 하드닝(INFRA-ISSUE-293)으로 정확 버전 핀 — latest 부동
# 설치 금지. 업데이트는 이 줄을 의도적으로 bump (registry 침해 시 floating tip 차단).
RUN python3 -m venv /home/agent/venv \
 && /home/agent/venv/bin/pip install --no-cache-dir /tmp/agent-build \
 && npm install -g @anthropic-ai/claude-code@2.1.185 @openai/codex@0.140.0 \
 && chmod +x /usr/local/bin/start-agent.sh /usr/local/bin/task-clone \
 && rm -rf /tmp/agent-build \
 && chown -R agent:agent /home/agent

ENV PATH="/home/agent/venv/bin:${PATH}"

USER agent

ENTRYPOINT ["bash", "/usr/local/bin/start-agent.sh"]
# rebuild trigger 1778900000
