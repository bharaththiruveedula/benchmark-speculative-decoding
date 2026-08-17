# Speculative decoding benchmarks

Repository: [github.com/bharaththiruveedula/benchmark-speculative-decoding](https://github.com/bharaththiruveedula/benchmark-speculative-decoding)

Fair comparison of speculative decoding methods on **Llama-3.1-8B-Instruct** across **vLLM** and **SGLang**. Phase 0 is the shared client plus **autoregressive (AR)** baselines: normal one-token-at-a-time decoding, no speculation.

You need a Hugging Face account with access to Llama 3.1, then:

```bash
export HF_TOKEN=...
huggingface-cli login --token "$HF_TOKEN"
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install the engines in that same env (or Docker) yourself. They are heavy and GPU-specific:

```bash
pip install vllm
# SGLang in a separate venv so it does not fight vLLM:
#   uv venv .venv-sglang --python 3.12 && uv pip install --python .venv-sglang "sglang[srt]"
```

On 2x RTX 5070 (12 GB), use the `*_5070.yaml` configs (FP8 / float16). On an 80 GB A100/H100, use `configs/vllm_ar.yaml` and `configs/sglang_ar.yaml` (BF16).

The reported benchmark in `results/table_latest.json` and `slides/index.html` was run on a single **NVIDIA L40 (48 GB GDDR6)** with **vLLM 0.27.1** and **SGLang 0.5.17**, BF16 target (`configs/vllm_ar.yaml`, `configs/sglang_ar.yaml` and their method variants). The 5070 configs below are the earlier 12 GB development setup; the L40 run is the final reported experiment.

The GPU box is `bharath@192.168.1.138`. Llama-3.1-8B-Instruct is gated: vLLM 0.20.0 there cannot download it until you `huggingface-cli login` with an account that accepted the Llama license. Until then, smoke tests use `configs/vllm_ar_5070_qwen.yaml` (`Qwen/Qwen2.5-3B-Instruct`, already cached).

## Run AR baseline

Terminal 1 (vLLM):

```bash
chmod +x scripts/serve_vllm.sh scripts/serve_sglang.sh
./scripts/serve_vllm.sh configs/vllm_ar_5070.yaml
```

Terminal 2:

```bash
source .venv/bin/activate
python bench/run.py --config configs/vllm_ar_5070.yaml
```

SGLang is the same with `serve_sglang.sh` and `configs/sglang_ar_5070.yaml` (default port 30000).

Busy-server smoke test (many in-flight requests):

```bash
python bench/run.py --config configs/vllm_ar_5070.yaml --concurrency 16
```

Results land in `results/` as JSONL plus a `*_summary.json`. Metrics: TTFT, TPOT, output tokens/s, GPU memory if `nvidia-smi` is available.

## Phase 1: speculative methods

Same client (`bench/run.py`). Restart the server with a method config (do not stack a draft on the AR process — 12 GB is already full).

Pinned Hugging Face IDs:

| Role | ID | Engine |
| --- | --- | --- |
| Target (vLLM) | `meta-llama/Llama-3.1-8B-Instruct` + online FP8 | vLLM |
| Target (SGLang, 12 GB) | `RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8-dynamic` | SGLang |
| Classical draft | `meta-llama/Llama-3.2-1B-Instruct` | both |
| Medusa heads | `nebius/MEDUSA-Llama-3.1-8B-Instruct` | vLLM only |
| EAGLE-3 (vLLM) | `yuhuili/EAGLE3-LLaMA3.1-Instruct-8B` | vLLM |
| EAGLE-3 (SGLang) | `lmsys/SGLang-EAGLE3-Llama-3.1-8B-Instruct-SpecForge` | SGLang |

Those EAGLE checkpoints are **not interchangeable**.

```bash
./scripts/serve_vllm.sh configs/vllm_eagle3_5070.yaml
python bench/run.py --config configs/vllm_eagle3_5070.yaml
python bench/run.py --config configs/vllm_eagle3_5070.yaml --concurrency 16
```

vLLM 0.27.1 has no Dynamic Speculative Decoding schedule. The vLLM "fixed-K ablation" rows are `vllm_eagle3_k5.yaml` (K=5), `vllm_eagle3_k1.yaml` (K=1), with `vllm_eagle3.yaml` as the K=3 default &mdash; these are separately configured fixed draft lengths, not an adaptive policy. SGLang adaptive (`sglang_eagle3_adaptive.yaml`) is an acceptance-driven policy that dynamically adjusts the speculative configuration &mdash; a different algorithm; label it that way on slides. Do not pool the vLLM fixed-K grid with SGLang adaptive.

Medusa is vLLM-only (`configs/vllm_medusa_5070.yaml`). There is no SGLang Medusa config on purpose.
