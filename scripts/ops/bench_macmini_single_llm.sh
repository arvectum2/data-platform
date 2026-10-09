#!/usr/bin/env bash
# BENCHMARK ONLY. Briefly takes ONLY Gemma llama.cpp launchd server offline.
# Restores its original job definition on shell exit, even on benchmark failure.
# Requires a separate Qwen MLX server :18081 and test DP server :18094 already healthy.
set -Eeuo pipefail
domain="gui/$(id -u)"
label="local.llama-server-8081"
plist="$HOME/Library/LaunchAgents/local.llama-server-8081.plist"
restore() {
  if ! /bin/launchctl print "$domain/$label" >/dev/null 2>&1; then
    /bin/launchctl bootstrap "$domain" "$plist" || true
  fi
  for n in $(seq 1 35); do
    if /usr/bin/curl -fsS --max-time 2 http://127.0.0.1:8081/health >/dev/null 2>&1; then
      echo "GEMMA_RESTORED_HEALTHY"
      return
    fi
    sleep 1
  done
  echo "WARNING_GEMMA_RESTORE_UNCONFIRMED"
}
trap restore EXIT
for p in 18081 18094 8090 8091 8094 8001; do
  /usr/bin/curl -fsS --max-time 4 "http://127.0.0.1:$p/health" >/dev/null
done
echo "SINGLE_LLM_TRIAL_BEGIN"
echo "BASELINE_MEMORY"
memory_pressure | grep "free percentage" || true
/bin/launchctl bootout "$domain/$label"
sleep 3
echo "AFTER_GEMMA_STOP"
memory_pressure | grep "free percentage" || true
sysctl vm.swapusage || true
set -a
source "$HOME/Library/Application Support/Arvectum/data-platform/runtime.env"
set +a
cd /Volumes/ArvectumSSD/Arvectum/repos/data-platform
ARVECTUM_STACK_SMOKE_URL=http://127.0.0.1:18094 \
ARVECTUM_STACK_SMOKE_OUTPUT=/Volumes/ArvectumSSD/Models/data-platform-benchmarks/quality-results/macmini-live-e2e-qwen35-4b-single-llm.json \
.venv/bin/python -u scripts/ops/smoke_live_macmini_tender_dp.py
echo "SINGLE_LLM_TRIAL_DONE"
