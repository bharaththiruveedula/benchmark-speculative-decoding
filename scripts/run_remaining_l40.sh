#!/usr/bin/env bash
# Remaining L40 cells after the first driver: SGLang EAGLE, Medusa, EAGLE K c=1, classic.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p results

export PATH="$ROOT/.venv-vllm/bin:$HOME/.local/bin:$PATH"
export VLLM_ENABLE_V1_MULTIPROCESSING=0

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

wait_ready() { # port log
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

run_cfg() { # engine config port
  local engine="$1" cfg="$2" port="$3"
  local name; name=$(basename "$cfg" .yaml)
  local log="results/serve_${name}.log"
  echo "==== START $cfg ===="
  stop_servers
  : > "$log"
  if [ "$engine" = "vllm" ]; then
    nohup bash scripts/serve_vllm.sh "$cfg" >"$log" 2>&1 &
  else
    nohup bash scripts/serve_sglang.sh "$cfg" >"$log" 2>&1 &
  fi
  if ! wait_ready "$port" "$log"; then
    echo "==== SKIP $cfg (server failed) ===="
    return 1
  fi
  .venv/bin/python bench/run.py --config "$cfg" --concurrency 1 || echo "BENCH_C1_FAILED $cfg"
  .venv/bin/python bench/run.py --config "$cfg" --concurrency 16 || echo "BENCH_C16_FAILED $cfg"
  echo "==== DONE $cfg ===="
}

run_cfg sglang configs/sglang_eagle3.yaml 30000
run_cfg sglang configs/sglang_eagle3_adaptive.yaml 30000
run_cfg vllm configs/vllm_medusa.yaml 8000
run_cfg vllm configs/vllm_eagle3_k1.yaml 8000
run_cfg vllm configs/vllm_eagle3_k5.yaml 8000
run_cfg vllm configs/vllm_classic.yaml 8000
run_cfg sglang configs/sglang_classic.yaml 30000

stop_servers
echo "REMAINING_BENCHMARKS_COMPLETE"
