#!/usr/bin/env python3
"""Switch Mac-mini single-LLM launchd job, with rollback and bounded probes.

One model at a time on :8081. Model profile survives process restarts.
External integrations are not altered unless this command is explicitly run.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path("/Users/master/arvectum-runtime/data-platform")
PROFILE = ROOT / ".llm-profile"
ENV = Path("/Users/master/Library/Application Support/Arvectum/data-platform/runtime.env")
LOCK = ROOT / ".llm-profile.lock"
LLM_JOB = f"gui/{os.getuid()}/local.llama-server-8081"
DP_JOB = f"gui/{os.getuid()}/com.arvectum.data-platform"
OS_JOB = f"gui/{os.getuid()}/com.arvectum.os.persistent-internal"
GEMMA_ID = "arvectum-gemma4-12b-it-qat-q4_0"
QWEN_ID = "/Users/master/arvectum-runtime/models/qwen3.5-4b-mlx-4bit"
PROFILES = {
    "quality": (GEMMA_ID, "local-2026-10-06"),
    "fast": (QWEN_ID, "qwen3.5-4b-mlx4bit"),
}


def current() -> str:
    profile = PROFILE.read_text().strip() if PROFILE.exists() else "quality"
    if profile not in PROFILES:
        raise ValueError("Unknown configured model profile")
    return profile


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *args], capture_output=True, text=True, timeout=25
    )


def put(path: Path, value: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.new")
    try:
        with open(tmp, "x", encoding="utf-8") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(value)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def configured_env(original: str, profile: str) -> str:
    model_id, version = PROFILES[profile]
    changes = {
        "ARVECTUM_DATA_REASONING_MODEL": model_id,
        "ARVECTUM_DATA_REASONING_MODEL_VERSION": version,
        "ARVECTUM_DATA_REASONING_BASE_URL": "http://127.0.0.1:8081/v1",
        "ARVECTUM_DATA_MODEL_MAX_CONCURRENCY": "1",
    }
    out = []
    seen = set()
    for line in original.splitlines():
        key = line.partition("=")[0]
        if key in changes:
            out.append(f"{key}={changes[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key in changes.keys() - seen:
        out.append(f"{key}={changes[key]}")
    return "\n".join(out) + "\n"


def probe_server(profile: str, timeout: float = 105.0) -> float:
    model_id, _ = PROFILES[profile]
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Ответь одним словом: ГОТОВО."}],
        "max_tokens": 48,
        "temperature": 0,
    }
    request = urllib.request.Request(
        "http://127.0.0.1:8081/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    last = ""
    while time.monotonic() - started < timeout:
        try:
            with urllib.request.urlopen(request, timeout=9) as response:
                value = json.load(response)["choices"][0]["message"]["content"]
            if "ГОТОВО" in value.upper():
                return round(time.monotonic() - started, 3)
            last = "response did not match test phrase"
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(1)
    raise TimeoutError(f"{profile} model did not pass generation: {last}")


def probe_api(timeout: float = 50.0) -> None:
    stop = time.monotonic() + timeout
    while time.monotonic() < stop:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8094/health", timeout=3) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError("Data Platform API did not become healthy")


def apply(profile: str) -> float:
    result = launchctl("kickstart", "-k", LLM_JOB)
    if result.returncode:
        raise RuntimeError("LLM launchd kickstart failed: " + result.stderr[:180])
    elapsed = probe_server(profile)
    result = launchctl("kickstart", "-k", DP_JOB)
    if result.returncode:
        raise RuntimeError("Data Platform launchd restart failed: " + result.stderr[:180])
    probe_api()
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=["status", "fast", "quality"])
    parser.add_argument(
        "--acknowledge-shared-consumers",
        action="store_true",
        help="Accept that Arvectum OS and other consumers of :8081 may expect Gemma",
    )
    args = parser.parse_args()
    if args.profile == "status":
        print(json.dumps({"profile": current(), "llm_port": 8081}, ensure_ascii=False))
        return 0
    if args.profile == "fast" and not args.acknowledge_shared_consumers:
        parser.error("Fast mode affects other :8081 consumers; explicit acknowledgement required")
    if not Path("/Users/master/arvectum-runtime/models/gemma4-12b-qat-q4.gguf").is_file():
        raise RuntimeError("Verified local Gemma weights not found")
    if not Path(QWEN_ID).is_dir():
        raise RuntimeError("Qwen3.5-4B MLX weights not found")

    with open(LOCK, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = current()
        new = args.profile
        if old == new:
            print(json.dumps({"profile": old, "unchanged": True}))
            return 0
        original_env = ENV.read_text()
        original_profile = PROFILE.read_text() if PROFILE.exists() else None
        print(f"SWITCH_START {old} -> {new}", flush=True)
        try:
            put(ENV, configured_env(original_env, new))
            put(PROFILE, new + "\n")
            elapsed = apply(new)
            print(json.dumps({"profile": new, "success": True,
                              "inference_probe_seconds": elapsed}), flush=True)
            return 0
        except BaseException:
            print("ROLLBACK_START", file=sys.stderr, flush=True)
            put(ENV, original_env)
            if original_profile is None:
                PROFILE.unlink(missing_ok=True)
            else:
                put(PROFILE, original_profile)
            try:
                apply(old)
                print("ROLLBACK_OK", file=sys.stderr, flush=True)
            except Exception as recovery:
                print(f"ROLLBACK_INCOMPLETE: {type(recovery).__name__}",
                      file=sys.stderr, flush=True)
            raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"PROFILE_ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
