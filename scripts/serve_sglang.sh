#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-$ROOT/configs/sglang_ar.yaml}"
cd "$ROOT"
PYTHON="${SGLANG_PYTHON:-$ROOT/.venv-sglang/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi
# SpecForge EAGLE-3 draft derives max len 2048; keep target ctx 4096 for a fair vs-vLLM table.
export SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN="${SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN:-1}"
export PATH="${ROOT}/.venv-sglang/bin:${PATH}"
exec "$PYTHON" "$ROOT/scripts/build_serve_cmd.py" --exec sglang "$CONFIG"
