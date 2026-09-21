#!/bin/bash
set -euo pipefail

# 글로벌 agent-loop. HOME=/data/shared(NFS 공용 .claude), CWD=$HOME 기본.
HOME_DIR="${HOME:-/data/shared}"
mkdir -p "${HOME_DIR}/.claude"
cd "${HOME_DIR}"

uvicorn app.loop:app --host 0.0.0.0 --port 8001 --log-level warning &
exec python3 -m app.loop
