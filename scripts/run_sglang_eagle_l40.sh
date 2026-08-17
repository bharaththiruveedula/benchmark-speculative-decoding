#!/usr/bin/env bash
# Retry SGLang EAGLE-3 after SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p results
FAIL_RE="Engine core initialization failed|Received sigquit|Not enough memory|OutOfMemoryError|Thunder Compute runtime has crashed|gated repo|403 Client Error|Cannot access gated|awaiting a review"

stop_servers() {
  fuser -k 8000/tcp >/dev/null 2>&1 || true
  fuser -k 30000/tcp >/dev/null 2>&1 || true
  sleep 3
  nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | while read -r pid; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  sleep 3
}

wait_ready() {
  local port="$1" log="$2"
  for _ in $(seq 1 180); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/v1/models" || echo 000)
    if [ "$code" = "200" ]; then
      sleep 25
      code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/v1/models" || echo 000)
      if [ "$code" = "200" ]; then return 0; fi
    fi
    if grep -qE "$FAIL_RE" "$log" 2>/dev/null; then
      echo "SERVER_FAILED $log"; tail -20 "$log"; return 1
    fi
    sleep 5
  done
  echo "SERVER_TIMEOUT $log"; tail -20 "$log"; return 1
}

run_cfg() {
  local cfg="$1"
  local name; name=$(basename "$cfg" .yaml)
  local log="results/serve_${name}.log"
  echo "==== START $cfg ===="
  stop_servers
  : > "$log"
  nohup bash scripts/serve_sglang.sh "$cfg" >"$log" 2>&1 &
  if ! wait_ready 30000 "$log"; then
    echo "==== SKIP $cfg (server failed) ===="
    return 1
  fi
  .venv/bin/python bench/run.py --config "$cfg" --concurrency 1 || echo "BENCH_C1_FAILED $cfg"
  .venv/bin/python bench/run.py --config "$cfg" --concurrency 16 || echo "BENCH_C16_FAILED $cfg"
  echo "==== DONE $cfg ===="
}

run_cfg configs/sglang_eagle3.yaml
run_cfg configs/sglang_eagle3_adaptive.yaml

# vLLM classic: Thunder aborts during CUDA-graph profiling; eager mode.
run_vllm_classic() {
  local cfg="configs/vllm_classic.yaml"
  local log="results/serve_vllm_classic.log"
  echo "==== START $cfg (eager retry) ===="
  stop_servers
  : > "$log"
  nohup bash scripts/serve_vllm.sh "$cfg" >"$log" 2>&1 &
  if ! wait_ready 8000 "$log"; then
    echo "==== SKIP $cfg (server failed) ===="
    return 1
  fi
  .venv/bin/python bench/run.py --config "$cfg" --concurrency 1 || echo "BENCH_C1_FAILED $cfg"
  .venv/bin/python bench/run.py --config "$cfg" --concurrency 16 || echo "BENCH_C16_FAILED $cfg"
  echo "==== DONE $cfg ===="
}
run_vllm_classic

stop_servers
echo "SGLANG_EAGLE_COMPLETE"
