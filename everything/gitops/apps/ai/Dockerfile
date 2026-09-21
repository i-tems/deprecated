# trigger build
FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    ca-certificates curl \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# claude-code 정확 버전 핀 — 공급망 하드닝(INFRA-ISSUE-326/293). latest 부동 설치는 악성
# 버전이 claude -p 서브프로세스(runner.py)로 실행돼 NFS 공유 자격증명 노출면을 키운다.
# 현재 배포본(2.1.143, node20)을 그대로 고정 — behavior 무변경, 의도된 bump 시에만 갱신.
RUN npm install -g @anthropic-ai/claude-code@2.1.143

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY app/ /app/app/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
