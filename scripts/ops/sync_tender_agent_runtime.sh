#!/bin/bash
# Deploy the canonical Tender Agent checkout to the Mac mini's TCC-safe runtime.
# No database modifications, no automatic service restart, no secret logging.
set -euo pipefail
source_repo=/Volumes/ArvectumSSD/Arvectum/repos/tender-agent
runtime=/Users/master/arvectum-runtime/tender-agent
private_env="/Users/master/Library/Application Support/Arvectum/tender-agent/runtime.env"
install -d -m 700 "$runtime"
for directory in src scripts migrations alembic demo_data; do
  if [ -d "$source_repo/$directory" ]; then
    rsync -a "$source_repo/$directory/" "$runtime/$directory/"
  fi
done
rsync -a "$source_repo/.venv/" "$runtime/.venv/"
for name in alembic.ini pyproject.toml requirements.txt setup.cfg uv.lock; do
  if [ -f "$source_repo/$name" ]; then
    cp -p "$source_repo/$name" "$runtime/$name"
  fi
done
printf '%s\n' "$runtime" > "$runtime/.venv/lib/python3.12/site-packages/__editable__.ai_corporation-0.1.0.pth"
if [ ! -f "$private_env" ]; then
  install -d -m 700 "$(dirname "$private_env")"
  install -m 600 /Volumes/ArvectumSSD/Arvectum/private/tender-agent/runtime/backend.env "$private_env"
fi
chmod 600 "$private_env"
install -m 700 /Volumes/ArvectumSSD/Arvectum/repos/data-platform/scripts/ops/tender_backend_launch_internal.sh /Users/master/arvectum-runtime/tender-agent-backend-launch.sh
commit=$(git -C "$source_repo" rev-parse HEAD)
printf '%s\n' "$commit" > "$runtime/.source_commit"
echo "TENDER_INTERNAL_RUNTIME_SYNCED commit=${commit:0:12}"
echo "Service restart is a separate, explicitly verified operation."
