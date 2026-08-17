#!/usr/bin/env python3
"""Collapse results/*_summary.json into one table (latest good run per engine/method/c)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


def load_summaries() -> list[dict]:
    rows = []
    for path in sorted(RESULTS.glob("*_summary.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        data["_file"] = path.name
        rows.append(data)
    return rows


def key(row: dict) -> tuple:
    return (row.get("engine"), row.get("method"), row.get("concurrency"))


def pick_latest_ok(rows: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for row in rows:
        n_ok = int(row.get("n_ok") or 0)
        n_prompts = int(row.get("n_prompts") or 0)
        if n_ok <= 0 or (n_prompts and n_ok < n_prompts):
            continue
        k = key(row)
        prev = best.get(k)
        if prev is None or str(row.get("ts") or "") > str(prev.get("ts") or ""):
            best[k] = row
    return [best[k] for k in sorted(best)]


def fmt(x, digits=1):
    if x is None:
        return "-"
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def main() -> int:
    rows = pick_latest_ok(load_summaries())
    print(
        f"{'engine':<8} {'method':<16} {'c':>3} {'tok/s':>8} {'ttft':>7} {'tpot':>7} "
        f"{'acc/draft':>9} {'vram_mb':>8} {'file'}"
    )
    for r in rows:
        print(
            f"{str(r.get('engine')):<8} {str(r.get('method')):<16} {int(r.get('concurrency') or 0):>3} "
            f"{fmt(r.get('output_tokens_per_s'), 1):>8} {fmt(r.get('mean_ttft_s'), 3):>7} "
            f"{fmt(r.get('mean_tpot_s'), 4):>7} {fmt(r.get('mean_accepted_tokens_per_draft'), 2):>9} "
            f"{fmt(r.get('gpu_memory_used_mb_peak_observed'), 0):>8} {r.get('_file')}"
        )
    out = RESULTS / "table_latest.json"
    out.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
