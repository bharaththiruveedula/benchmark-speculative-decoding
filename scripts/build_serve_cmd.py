#!/usr/bin/env python3
"""Build or exec a vLLM / SGLang serve command from a YAML config."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml


def vllm_cmd(cfg: dict) -> list[str]:
    cmd = [
        "vllm",
        "serve",
        cfg["model"],
        "--port",
        str(int(cfg.get("port", 8000))),
        "--dtype",
        str(cfg.get("dtype") or "auto"),
        "--tensor-parallel-size",
        str(int(cfg.get("tensor_parallel_size", 1))),
        "--gpu-memory-utilization",
        str(float(cfg.get("gpu_memory_utilization", 0.9))),
        "--max-model-len",
        str(int(cfg.get("max_model_len", 4096))),
    ]
    quant = cfg.get("quantization")
    if quant:
        cmd.extend(["--quantization", str(quant)])
    spec = cfg.get("speculative_config")
    if spec:
        cmd.extend(["--speculative-config", json.dumps(spec, separators=(",", ":"))])
    if cfg.get("enforce_eager"):
        cmd.append("--enforce-eager")
    return cmd


def sglang_cmd(cfg: dict) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "sglang.launch_server",
        "--model-path",
        cfg["model"],
        "--port",
        str(int(cfg.get("port", 30000))),
        "--dtype",
        str(cfg.get("dtype") or "bfloat16"),
        "--tp",
        str(int(cfg.get("tensor_parallel_size", 1))),
        "--mem-fraction-static",
        str(float(cfg.get("mem_fraction_static", 0.85))),
        "--context-length",
        str(int(cfg.get("max_model_len", 4096))),
    ]
    quant = cfg.get("quantization")
    if quant:
        cmd.extend(["--quantization", str(quant)])
    base_gpu = cfg.get("base_gpu_id")
    if base_gpu is not None:
        cmd.extend(["--base-gpu-id", str(int(base_gpu))])
    spec = cfg.get("speculative") or {}
    algo = spec.get("algorithm") or cfg.get("speculative_algorithm")
    if algo:
        cmd.extend(["--speculative-algorithm", str(algo)])
    draft = (
        spec.get("draft_model")
        or spec.get("draft_model_path")
        or cfg.get("speculative_draft_model_path")
    )
    if draft:
        cmd.extend(["--speculative-draft-model-path", str(draft)])
    mapping = [
        ("num_steps", "--speculative-num-steps"),
        ("eagle_topk", "--speculative-eagle-topk"),
        ("num_draft_tokens", "--speculative-num-draft-tokens"),
        ("draft_quantization", "--speculative-draft-model-quantization"),
        ("draft_model_quantization", "--speculative-draft-model-quantization"),
        ("accept_threshold_single", "--speculative-accept-threshold-single"),
        ("accept_threshold_acc", "--speculative-accept-threshold-acc"),
    ]
    for key, flag in mapping:
        val = spec.get(key)
        if val is not None:
            cmd.extend([flag, str(val)])
    if cfg.get("enable_metrics"):
        cmd.append("--enable-metrics")
    if cfg.get("disable_cuda_graph"):
        cmd.append("--disable-cuda-graph")
    if cfg.get("skip_server_warmup"):
        cmd.append("--skip-server-warmup")
    return cmd


def main() -> int:
    args = sys.argv[1:]
    do_exec = False
    if args and args[0] == "--exec":
        do_exec = True
        args = args[1:]
    if len(args) != 2:
        print("usage: build_serve_cmd.py [--exec] {vllm|sglang} CONFIG.yaml", file=sys.stderr)
        return 2
    engine, path = args[0], Path(args[1])
    cfg = yaml.safe_load(path.read_text())
    if engine == "vllm":
        cmd = vllm_cmd(cfg)
    elif engine == "sglang":
        cmd = sglang_cmd(cfg)
    else:
        print(f"unknown engine {engine}", file=sys.stderr)
        return 2
    vis = cfg.get("cuda_visible_devices")
    if vis is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(vis)
    print(" ".join(cmd), flush=True)
    if do_exec:
        os.execvp(cmd[0], cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
