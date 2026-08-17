#!/usr/bin/env bash
# Start a server from YAML, wait until /v1/models is up, run c=1 and c=16, stop it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ENGINE="$1"
CONFIG="$2"
PORT="$3"
LOG="results/serve_${ENGINE}_$(basename "$CONFIG" .yaml).log"

stop_port() {
  local p="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${p}/tcp" >/dev/null 2>&1 || true
  fi
  sleep 2
  # leftover GPU workers
  nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | while read -r pid; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  sleep 2
}

wait_ready() {
  local url="$1"
  local log="$2"
  for _ in $(seq 1 90); do
    if curl -sf "$url" >/dev/null; then
      return 0
    fi
    if grep -qE "Engine core initialization failed|Received sigquit|OutOfMemoryError" "$log" 2>/dev/null; then
      echo "SERVER_FAILED $log"
      tail -30 "$log"
      return 1
    fi
    sleep 5
  done
  echo "SERVER_TIMEOUT $log"
  tail -30 "$log"
  return 1
}

mkdir -p results
stop_port "$PORT"
: > "$LOG"
if [ "$ENGINE" = "vllm" ]; then
  export PATH="$ROOT/.venv-vllm/bin:$HOME/.local/bin:$PATH"
  nohup bash scripts/serve_vllm.sh "$CONFIG" >"$LOG" 2>&1 &
  URL="http://127.0.0.1:${PORT}/v1/models"
else
  nohup bash scripts/serve_sglang.sh "$CONFIG" >"$LOG" 2>&1 &
  URL="http://127.0.0.1:${PORT}/v1/models"
fi
echo "started $ENGINE $CONFIG log=$LOG"
wait_ready "$URL" "$LOG"
.venv/bin/python bench/run.py --config "$CONFIG" --concurrency 1
.venv/bin/python bench/run.py --config "$CONFIG" --concurrency 16
stop_port "$PORT"
echo "DONE $CONFIG"
