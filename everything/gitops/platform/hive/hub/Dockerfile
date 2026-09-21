FROM registry.lab.i-tems.com/hive-capability-framework:main

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates tini \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir httpx PyJWT google-auth requests watchfiles jsonschema mcp sqlalchemy pymysql "kubernetes>=35,<36" PyYAML ruamel.yaml prometheus_client

COPY app ./app
COPY schemas ./schemas

EXPOSE 8000
# tini 를 PID 1 로 두어 reparent 된 git 헬퍼 좀비를 즉시 reap (zombie leak 방지)
ENTRYPOINT ["tini", "-g", "--"]
# --timeout-graceful-shutdown 10: 장수명 연결(SSE /events · MCP streamable)이
# SIGTERM 후 안 닫혀 grace 를 SIGKILL 까지 소진하던 것을 10s 로 cap. 단일-replica
# Recreate 배포 다운 윈도우 단축 (INFRA-ISSUE-280).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "10"]

# rebuild trigger 1777855030

# rebuild trigger 1777855741
# rebuild trigger 1777864603
# rebuild trigger 1777865499
# rebuild trigger 1777866400
# rebuild trigger 1778388626
# rebuild trigger 1779578692  # fresh capability-framework :main pull (action_log 제거 반영)
