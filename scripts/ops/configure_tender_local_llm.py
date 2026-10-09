#!/usr/bin/env python3
"""Activate localhost-only Gemma for the Tender Agent's controlled provider.

Backs up the private runtime env; never prints secrets or changes DB settings.
Call from the Mac mini explicitly, then kickstart the launchd backend.
"""
from pathlib import Path
import os
import shutil
import tempfile

p = Path("/Users/master/Library/Application Support/Arvectum/tender-agent/runtime.env")
backup = p.with_name("runtime.env.bak-20261009-before-local-llm")
if not backup.exists():
    shutil.copy2(p, backup)
    os.chmod(backup, 0o600)

changes = {
    "AI_CORP_LLM_PROVIDER": "openai_compatible",
    "AI_CORP_LLM_MODEL": "arvectum-gemma4-12b-it-qat-q4_0",
    "AI_CORP_OPENAI_BASE_URL": "http://127.0.0.1:8081/v1",
    "AI_CORP_OPENAI_API_KEY": "local-only-no-auth",
    "AI_CORP_LLM_TIMEOUT_SECONDS": "120",
    "AI_CORP_LLM_MAX_RETRIES": "1",
}
old = p.read_text()
seen = set()
new_lines = []
for line in old.splitlines():
    key = line.partition("=")[0].strip().removeprefix("export ").strip()
    if key in changes:
        new_lines.append(f"{key}={changes[key]}")
        seen.add(key)
    else:
        new_lines.append(line)
for key in changes:
    if key not in seen:
        new_lines.append(f"{key}={changes[key]}")
new = "\n".join(new_lines) + "\n"
assert "http://127.0.0.1:8081/v1" in new
fd, temp = tempfile.mkstemp(prefix=".runtime.env.", dir=p.parent)
try:
    with os.fdopen(fd, "w") as stream:
        stream.write(new)
    os.chmod(temp, 0o600)
    os.replace(temp, p)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
print("TENDER_LOCAL_ONLY_GEMMA_CONFIGURED; PRIVATE_ENV_BACKED_UP")
print("NO_DATABASE_OR_OTHER_CONFIG_CHANGED")
