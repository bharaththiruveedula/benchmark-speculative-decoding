#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-$ROOT/configs/vllm_ar.yaml}"
cd "$ROOT"
PYTHON="${VLLM_BUILDER_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi
export PATH="${ROOT}/.venv-vllm/bin:${PATH}"
# Thunder Compute: EngineCore fork can abort; keep this on every vLLM serve.
export VLLM_ENABLE_V1_MULTIPROCESSING="${VLLM_ENABLE_V1_MULTIPROCESSING:-0}"
exec "$PYTHON" "$ROOT/scripts/build_serve_cmd.py" --exec vllm "$CONFIG"
