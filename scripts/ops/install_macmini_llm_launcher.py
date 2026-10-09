#!/usr/bin/env python3
"""Install the approved single-job LLM launch selector, retaining rollback."""
from pathlib import Path
import os, re, shutil, stat, subprocess

repo = Path(__file__).resolve().parents[2]
runtime = Path("/Users/master/arvectum-runtime/data-platform")
source = repo / "scripts/ops/macmini_llm_launch.sh"
destination = runtime / "macmini_llm_launch.sh"
gate = Path("/Users/master/arvectum-ops/arv-075/scripts/ssd-gate.sh")
backup = gate.with_name("ssd-gate.sh.bak-20261009-profiles")
if not backup.exists():
    shutil.copy2(gate, backup)
shutil.copy2(source, destination)
os.chmod(destination, 0o700)
text = gate.read_text()
if "macmini_llm_launch.sh" not in text:
    expr = r"  llama-8081\)\n.*?(?=  ;;\n)"
    replacement = (
        '  llama-8081)\n'
        '    if wait_for_ssd && verify_symlinks; then\n'
        '      exec "$HOME/arvectum-runtime/data-platform/macmini_llm_launch.sh"\n'
        '    fi\n'
        '    exit 1\n'
    )
    changed, count = re.subn(expr, lambda _: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("SSD gate had an unexpected structure; refusing patch")
    gate.write_text(changed)
for item in (gate, destination):
    subprocess.run(["/bin/bash", "-n", str(item)], check=True)
print("PROFILE_LAUNCHER_INSTALLED",destination)
print("ORIGINAL_SSD_GATE_SAVED",backup)
