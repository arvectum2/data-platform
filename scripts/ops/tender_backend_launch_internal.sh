#!/bin/bash
# Tender Agent launchd runtime: only internal APFS code and secrets are read at startup.
set -euo pipefail
export ARVECTUM_ENV_FILE="/Users/master/Library/Application Support/Arvectum/tender-agent/runtime.env"
cd /Users/master/arvectum-runtime/tender-agent
set -a
source "$ARVECTUM_ENV_FILE"
set +a
exec ./.venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port "${AI_CORP_BACKEND_PORT:-8001}"
