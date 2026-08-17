#!/usr/bin/env python3
"""Drive an OpenAI-compatible vLLM or SGLang server and record decode metrics."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data


def load_prompts(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "prompt" not in row:
                raise ValueError(f"Prompt row missing 'prompt': {row}")
            rows.append({"id": str(row.get("id", len(rows))), "prompt": row["prompt"]})
    if not rows:
        raise ValueError(f"No prompts in {path}")
    return rows


def gpu_memory_mb(gpu_index: int | None = None) -> float | None:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    values: dict[int, float] = {}
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            values[int(float(parts[0]))] = float(parts[1])
    if not values:
        return None
    if gpu_index is None:
        return sum(values.values())
    return values.get(int(gpu_index))


def scrape_spec_metrics(metrics_url: str) -> dict[str, float]:
    """Parse Prometheus text for speculative-decode counters (vLLM / SGLang)."""
    try:
        r = httpx.get(metrics_url, timeout=5.0)
        r.raise_for_status()
    except httpx.HTTPError:
        return {}
    found: dict[str, float] = {}
    for raw in r.text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "spec_decode" not in line and "speculative" not in line.lower() and "accept" not in line:
            continue
        name, _, rest = line.partition(" ")
        name = name.split("{", 1)[0]
        try:
            found[name] = float(rest.strip().split()[0])
        except (ValueError, IndexError):
            continue
    return found


def spec_acceptance(before: dict[str, float], after: dict[str, float]) -> dict[str, float | None]:
    def delta(*keys: str) -> float | None:
        for k in keys:
            if k in after:
                return after[k] - before.get(k, 0.0)
        return None

    accepted = delta(
        "vllm:spec_decode_num_accepted_tokens_total",
        "vllm:spec_decode_num_accepted_tokens",
    )
    draft = delta(
        "vllm:spec_decode_num_draft_tokens_total",
        "vllm:spec_decode_num_draft_tokens",
    )
    drafts = delta("vllm:spec_decode_num_drafts_total", "vllm:spec_decode_num_drafts")
    out: dict[str, float | None] = {
        "spec_accepted_tokens": accepted,
        "spec_draft_tokens": draft,
        "spec_num_drafts": drafts,
        "mean_accepted_tokens_per_draft": None,
        "draft_accept_rate": None,
    }
    if accepted is not None and drafts:
        out["mean_accepted_tokens_per_draft"] = accepted / drafts
    if accepted is not None and draft:
        out["draft_accept_rate"] = accepted / draft
    return out


async def wait_for_server(base_url: str, timeout_s: float) -> None:
    models_url = base_url.rstrip("/") + "/models"
    deadline = time.monotonic() + timeout_s
    ok_streak = 0
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(models_url)
                if r.status_code == 200:
                    ok_streak += 1
                    if ok_streak >= 3:
                        return
                    await asyncio.sleep(2)
                    continue
            except httpx.HTTPError:
                pass
            ok_streak = 0
            await asyncio.sleep(2)
    raise TimeoutError(f"Server not ready at {models_url} after {timeout_s}s")


async def one_request(
    client: AsyncOpenAI,
    model: str,
    prompt: str,
    prompt_id: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    first_token_at: float | None = None
    chunks: list[str] = []
    completion_tokens = 0

    create_kwargs = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )
    try:
        stream = await client.chat.completions.create(
            **create_kwargs, stream_options={"include_usage": True}
        )
    except Exception:
        stream = await client.chat.completions.create(**create_kwargs)
    usage = None
    async for event in stream:
        if event.usage is not None:
            usage = event.usage
        if not event.choices:
            continue
        delta = event.choices[0].delta
        text = delta.content or ""
        if text:
            if first_token_at is None:
                first_token_at = time.perf_counter()
            chunks.append(text)
    t1 = time.perf_counter()

    output = "".join(chunks)
    if usage is not None and usage.completion_tokens:
        completion_tokens = usage.completion_tokens
    else:
        completion_tokens = max(len(output.split()), 1) if output else 0

    ttft = (first_token_at - t0) if first_token_at is not None else (t1 - t0)
    gen_s = (t1 - (first_token_at or t0))
    tpot = (gen_s / completion_tokens) if completion_tokens else None
    tokens_per_s = (completion_tokens / (t1 - t0)) if (t1 > t0 and completion_tokens) else 0.0

    return {
        "id": prompt_id,
        "ok": bool(output),
        "ttft_s": ttft,
        "tpot_s": tpot,
        "latency_s": t1 - t0,
        "completion_tokens": completion_tokens,
        "tokens_per_s": tokens_per_s,
        "output": output,
    }


async def run_bench(cfg: dict[str, Any], config_path: Path) -> dict[str, Any]:
    prompts_path = Path(cfg["prompts"])
    if not prompts_path.is_absolute():
        prompts_path = ROOT / prompts_path
    prompts = load_prompts(prompts_path)

    base_url = cfg["base_url"]
    model = cfg["model"]
    max_tokens = int(cfg.get("max_tokens", 256))
    temperature = float(cfg.get("temperature", 0.0))
    concurrency = int(cfg.get("concurrency", 1))
    max_wait_s = float(cfg.get("max_wait_s", 600))
    engine = cfg.get("engine", "unknown")
    method = cfg.get("method", "ar")

    print(f"Waiting for {base_url} ...", flush=True)
    await wait_for_server(base_url, max_wait_s)
    print("Server ready.", flush=True)

    metrics_url = cfg.get("metrics_url")
    if not metrics_url:
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        metrics_url = root.rstrip("/") + "/metrics"
    spec_before = scrape_spec_metrics(metrics_url)

    gpu_index = cfg.get("gpu_index", cfg.get("gpu_id", cfg.get("base_gpu_id")))
    if gpu_index is not None:
        gpu_index = int(gpu_index)
    mem_before = gpu_memory_mb(gpu_index)
    client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
    sem = asyncio.Semaphore(concurrency)
    wall0 = time.perf_counter()
    results: list[dict[str, Any]] = []

    async def wrapped(row: dict[str, str]) -> dict[str, Any]:
        async with sem:
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    return await one_request(
                        client,
                        model,
                        row["prompt"],
                        row["id"],
                        max_tokens,
                        temperature,
                    )
                except Exception as exc:  # noqa: BLE001 — retry connection races
                    last_exc = exc
                    await asyncio.sleep(2 * (attempt + 1))
            return {
                "id": row["id"],
                "ok": False,
                "error": str(last_exc),
                "ttft_s": None,
                "tpot_s": None,
                "latency_s": None,
                "completion_tokens": 0,
                "tokens_per_s": 0.0,
                "output": "",
            }

    gathered = await asyncio.gather(*(wrapped(p) for p in prompts))
    results.extend(gathered)
    wall = time.perf_counter() - wall0
    mem_after = gpu_memory_mb(gpu_index)
    spec_after = scrape_spec_metrics(metrics_url)
    spec_stats = spec_acceptance(spec_before, spec_after)

    ok = [r for r in results if r.get("ok")]
    total_tokens = sum(r["completion_tokens"] for r in ok)
    ttfts = [r["ttft_s"] for r in ok if r.get("ttft_s") is not None]
    tpots = [r["tpot_s"] for r in ok if r.get("tpot_s") is not None]
    summary = {
        "engine": engine,
        "method": method,
        "model": model,
        "config": str(config_path),
        "concurrency": concurrency,
        "n_prompts": len(prompts),
        "n_ok": len(ok),
        "wall_s": wall,
        "total_completion_tokens": total_tokens,
        "output_tokens_per_s": (total_tokens / wall) if wall > 0 else 0.0,
        "mean_ttft_s": statistics.mean(ttfts) if ttfts else None,
        "mean_tpot_s": statistics.mean(tpots) if tpots else None,
        "p50_ttft_s": statistics.median(ttfts) if ttfts else None,
        "gpu_index": gpu_index,
        "gpu_memory_used_mb_before": mem_before,
        "gpu_memory_used_mb_after": mem_after,
        "gpu_memory_used_mb_peak_observed": max(
            x for x in (mem_before, mem_after) if x is not None
        )
        if mem_before is not None or mem_after is not None
        else None,
        "ts": datetime.now(timezone.utc).isoformat(),
        **spec_stats,
    }
    return {"summary": summary, "requests": results}


def write_outputs(payload: dict[str, Any], engine: str, method: str) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    jsonl_path = out_dir / f"{engine}_{method}_{stamp}.jsonl"
    summary_path = out_dir / f"{engine}_{method}_{stamp}_summary.json"
    with jsonl_path.open("w") as f:
        f.write(json.dumps({"type": "summary", **payload["summary"]}) + "\n")
        for row in payload["requests"]:
            f.write(json.dumps({"type": "request", **row}) + "\n")
    summary_path.write_text(json.dumps(payload["summary"], indent=2) + "\n")
    return jsonl_path, summary_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, help="YAML config path")
    p.add_argument("--concurrency", type=int, default=None, help="Override config concurrency")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    cfg = load_yaml(config_path)
    if args.concurrency is not None:
        cfg["concurrency"] = args.concurrency

    payload = asyncio.run(run_bench(cfg, config_path))
    jsonl_path, summary_path = write_outputs(
        payload, cfg.get("engine", "unknown"), cfg.get("method", "ar")
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"wrote {jsonl_path}")
    print(f"wrote {summary_path}")
    return 0 if payload["summary"]["n_ok"] == payload["summary"]["n_prompts"] else 1


if __name__ == "__main__":
    sys.exit(main())
