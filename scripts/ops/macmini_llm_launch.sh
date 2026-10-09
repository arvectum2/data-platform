#!/bin/bash
# Invoked by the existing launchd Gemma job; one server on port 8081.
set -euo pipefail
profile_file="/Users/master/arvectum-runtime/data-platform/.llm-profile"
profile="quality"
if [ -f "$profile_file" ]; then
  read -r profile < "$profile_file"
fi
case "$profile" in
  quality)
    exec /opt/homebrew/bin/llama-server \
      -m /Users/master/arvectum-runtime/models/gemma4-12b-qat-q4.gguf \
      --host 127.0.0.1 --port 8081 -c 32768 -np 1 -ngl 99 \
      -b 512 -ub 512 --flash-attn auto --reasoning off \
      --reasoning-budget 0 --alias arvectum-gemma4-12b-it-qat-q4_0 ;;
  fast)
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
    exec /opt/homebrew/bin/python3 -m mlx_lm.server \
      --model /Users/master/arvectum-runtime/models/qwen3.5-4b-mlx-4bit \
      --host 127.0.0.1 --port 8081 \
      --chat-template-args '{"enable_thinking":false}' \
      --decode-concurrency 1 --prompt-concurrency 1 \
      --prompt-cache-size 1 --prompt-cache-bytes 268435456 \
      --max-tokens 640 --log-level WARNING ;;
  *)
    echo "Refusing invalid LLM profile: $profile" >&2
    exit 2 ;;
esac
