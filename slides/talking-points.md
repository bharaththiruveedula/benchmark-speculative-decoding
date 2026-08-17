# Talking points — `slides/index.html`

## Slide 1 — Title

Good morning. Our project studies speculative decoding under production serving
stacks.

The speedups reported for speculative decoding are typically two to three times
over autoregressive decoding.

Rather than reproducing a single number from a paper, we measured several
speculative methods — classical draft-model speculation, Medusa, and EAGLE-3 —
on the same Llama-3.1-8B-Instruct target, across two serving engines and two
levels of offered load. Across those configurations our measured speedups
ranged from 2.48× down to 0.90×. One configuration was slower than the
autoregressive baseline it was meant to accelerate.

That spread frames our two questions. First, does the same draft method rank
fastest on both engines, or does the ordering change? Second, does the speedup
persist as concurrency increases?

The takeaway we will support is that speculative decoding cannot be described
by one universal speedup number; it has to be measured under the deployment
conditions you intend to run.

Transition: to understand why speculative decoding may help, let's first look
at the fundamental limitation of normal autoregressive decoding.

## Slide 2 — Motivation

Let's start with the bottleneck we are trying to solve: autoregressive decoding
is inherently sequential.

After processing the prompt, the model predicts one token. That token is
appended to the sequence and becomes part of the input needed to predict the
next one.

For example, the model must select Paris before it can predict the token that
follows Paris. The next decoding step cannot begin until the previous step
finishes.

KV caching prevents us from recomputing the entire prompt, but it does not
remove this token-to-token dependency.

Each decoding step invokes the full target model to produce one new token. That
cost is dominated by reading the model's parameters out of memory rather than
by the arithmetic itself, which means a single-token step leaves much of the
GPU's compute idle.

One approximation worth noting: the first output token can be produced from the
prompt-prefill computation, so saying that N output tokens require exactly N
decoding passes is not strictly accurate. The important point is that the
tokens after it require serial decoding steps.

This motivates speculative decoding: a cheaper mechanism proposes several
future tokens, and the target model verifies them together — using compute that
a single-token step would have left idle.

Reported speedups, however, are usually measured on a single serving
implementation, at one batch size, with one draft length. Speculative decoding
has no universal speedup; it depends on draft quality, draft cost, the serving
engine, the hardware, and the request load. A single-engine protocol cannot
separate those factors, and that is what our design addresses.

Transition: now that we have the sequential bottleneck, let's look at how
speculative decoding changes the execution schedule through draft and verify.

## Slide 3 — Background

That cheaper mechanism is called the drafter. It proposes several candidate
tokens ahead of the current confirmed sequence.

Different methods create these candidates differently. A small draft language
model proposes tokens autoregressively, and EAGLE-3 invokes its draft module
repeatedly to extend a candidate tree, whereas Medusa uses additional heads to
predict future-token candidates in parallel.

The proposed tokens are temporarily supplied to the target model. The target
performs its normal next-token calculations across those positions in one
verification step.

The serving engine then compares the target's predictions with the draft
tokens. It accepts the matching prefix and rejects the draft from the first
mismatch onward, and the target's own prediction at the mismatch supplies the
correction.

With the correct acceptance procedure, this improves execution efficiency
without changing the target model's output distribution.

It is not free, though. Depending on the method, speculation requires an
additional draft model, an auxiliary module, or extra decoding heads, and that
cost belongs in the accounting.

Transition: with that common draft-and-verify framework established, let's look
at the specific drafting methods we evaluated.

## Slide 4 — Methods benchmarked

Autoregressive decoding is our baseline. It uses only the target model and does
not speculate.

Classical speculative decoding uses Llama-3.2-1B-Instruct as a separate draft
model, while Llama-3.1-8B-Instruct remains the target. This method may achieve
good acceptance, but it also introduces the cost of running a second
Transformer.

Medusa avoids a separate draft Transformer. It adds decoding heads that predict
multiple future-token candidates in parallel.

In our comparison, Medusa is available through vLLM. It is not listed as a
supported method in the SGLang 0.5.17 documentation, so we report it as not
available rather than inventing a comparison.

EAGLE-3 uses a specialized draft module with direct token prediction and
multi-layer features from the target model. We state that precisely because
feature-level prediction describes earlier EAGLE approaches and is not an
accurate description of EAGLE-3.

We also need to distinguish fixed draft lengths from adaptive decoding. The
vLLM K equals one, three, and five rows are a fixed-K ablation. SGLang adaptive
decoding is a different, acceptance-driven policy that adjusts the speculative
configuration at runtime, so we do not pool the two.

Because checkpoints and configurations differ between engines, these are
practical serving comparisons — not perfectly controlled engine-only
experiments.

Transition: next, I'll describe the experimental setup used to make the
comparisons as consistent as possible.

## Slide 5 — Experimental setup

The target model is Llama-3.1-8B-Instruct running in BF16 with a configured
context length of 4,096.

We use greedy decoding with temperature zero and allow up to 256 new tokens.

The workload contains 16 short technical prompts.

We test two concurrency levels. Concurrency one represents an interactive
request, while concurrency sixteen represents multiple requests sharing the GPU.

The hardware is an NVIDIA L40 with 48 GB of physical GDDR6 memory. Software may
report roughly 44.7 to 46 gibibytes of visible capacity, depending on how it is
measured.

The two serving engines are vLLM 0.27.1 and SGLang 0.5.17, run one process at a
time so they never contend for the same GPU.

Our main metrics include output tokens per second, time to first token, time
per output token, peak VRAM, and acceptance counters where the engine exposes
them.

Every speedup is calculated relative to the autoregressive baseline from the
same engine.

One asymmetry to keep in mind for the results. On vLLM, the Medusa and
classical rows ran with enforce-eager after CUDA-graph capture aborted on this
virtualized GPU, while SGLang retained its graphs.

The reported cells completed 16 out of 16 requests, although this is a small
experimental workload rather than a statistically representative production
test.

Transition: although the target and workload are held constant, the two serving
engines still differ in several important ways.

## Slide 6 — Comparison design

The target model, tokenizer, prompts, decoding configuration, and client-side
metric definitions are held fixed.

What changes is the serving stack around the model.

vLLM and SGLang have different schedulers, CUDA-graph behavior,
speculative-verification kernels, memory management, and method support.

The EAGLE-3 implementations also use engine-compatible checkpoints and
configurations that are not necessarily interchangeable.

Therefore, a difference between vLLM and SGLang cannot automatically be
attributed to the engine alone.

Similarly, matching rankings across engines are consistent with an algorithmic
advantage, but they do not prove that the algorithm is the only cause.

This distinction is important: we are evaluating practical end-to-end
configurations, not conducting a perfectly isolated engine experiment. It is
also why every speedup is reported against its own engine's baseline, rather
than combined into a single headline figure.

Transition: with those limitations in mind, let's look first at the
interactive, concurrency-one results.

## Slide 7 — Results at concurrency one

At concurrency one, EAGLE-3 is the highest-performing method in the
project-reported results for both engines.

For vLLM, EAGLE-3 with K equal to five reports 99.5 output tokens per second.
The vLLM autoregressive baseline reports 40.2 tokens per second, giving a
reported speedup of 2.48 times.

For SGLang, adaptive EAGLE reports 83.0 tokens per second and a reported
2.36-times speedup over its own autoregressive baseline.

The EAGLE K-equals-three configurations report similar speedups — 2.22 times
for vLLM and 2.24 times for SGLang.

That similar ranking across engines supports the interpretation that EAGLE-3 is
effective for this workload, although checkpoint and configuration differences
prevent strict algorithm-only attribution.

Classical 1B speculation reports only 1.05 times on vLLM but 1.90 times on
SGLang. The vLLM classical row used eager mode, so this difference should not
be interpreted as a clean comparison of the two engines.

These values are project-reported measurements and require the raw benchmark
logs and repeated runs for independent verification.

Transition: the next question is whether the advantage remains when multiple
requests compete for the GPU.

## Slide 8 — Results at concurrency sixteen

At concurrency sixteen, the GPU is serving multiple requests concurrently, so
the workload emphasizes aggregate throughput.

Speculative verification becomes more compute-intensive as effective work grows
with batch size and draft length. Because of this, speculative decoding can
eventually lose its advantage at sufficiently high load.

However, that crossover does not occur for EAGLE-3 at concurrency sixteen in
these project-reported L40 results.

vLLM EAGLE-3 with K equal to five reports 831.5 tokens per second. Compared with
the vLLM autoregressive baseline of 413.7 tokens per second, that is a reported
2.01-times speedup.

SGLang adaptive EAGLE reports 628.6 tokens per second, or 1.49 times its
autoregressive baseline.

The only reported method below its same-engine baseline is vLLM classical 1B, at
0.90 times. This is consistent with draft-model overhead and eager-mode
overhead, but the experiment does not measure their individual contributions.

The correct conclusion is limited: EAGLE remains beneficial at concurrency
sixteen on this specific model, GPU, and workload. It is not a universal
statement about high-batch inference.

Transition: the charts show the main trend. The next slide brings both engines
together in one table.

## Slide 9 — Full matrix

This table brings together both engines at concurrency one and concurrency
sixteen. The upper block is vLLM, the lower block is SGLang.

For each method, we show output throughput, speedup relative to that engine's
own autoregressive decoding, and accepted tokens per draft where vLLM exposes
that counter. The full results file retains TTFT, TPOT, VRAM, and the
full-precision values without forcing all of them into one slide.

Taking the vLLM block first. At concurrency one, throughput increases from 40.2
tokens per second for autoregressive decoding to 99.5 for EAGLE-3 with K equal
to five. As K increases from one to five, the reported acceptance value rises
from 0.76 to 2.05 accepted tokens per draft. Throughput rises alongside
acceptance, but acceptance alone does not explain performance, because draft and
verification costs also increase with K.

Medusa provides a smaller improvement: 1.39 times at concurrency one and 1.12
times at concurrency sixteen. Classical 1B moves from a small 1.05-times
improvement at concurrency one to 0.90 times at concurrency sixteen.

In the SGLang block, EAGLE-3 reports 2.24 times and adaptive decoding 2.36 times
at concurrency one, and 1.40 and 1.49 times at concurrency sixteen, each
relative to SGLang's own baseline.

Three things to read carefully. The asterisks matter: the vLLM classical 1B and
Medusa configurations used eager mode, which introduces a confounding
difference. The acceptance column is vLLM-primary, because SGLang did not expose
equivalent counters, so those cells are blank rather than zero. And Medusa on
SGLang is reported as not available, since it is not listed in the 0.5.17
documentation we used.

Because every speedup is relative to its own engine's baseline, the two engines'
absolute throughputs should not be compared directly.

The table is useful for understanding the trend, but not the third decimal.
Independent validation requires the raw results, the server commands, the logs,
the warmup details, and repeated measurements.

Transition: next, we isolate one variable on vLLM — the draft length — to see
how acceptance and speedup respond to it.

## Slide 10 — Draft-length ablation

The three configurations shown are separately configured fixed draft lengths, at
K equal to one, three, and five, on the same EAGLE-3 checkpoint. SGLang's
adaptive decoding adjusts its configuration at runtime, so it is not a point
on this curve and we do not place it here.

Acceptance rises with draft length: 0.76, 1.65, and 2.05 accepted tokens per
draft step at K equal to one, three, and five.

Speedup rises with it at both levels of load. At concurrency one, from 1.66 to
2.22 to 2.48 times. At concurrency sixteen, from 1.45 to 1.79 to 2.01 times.

Each pair of points on the chart is one configuration moving from concurrency
one to concurrency sixteen. Every draft length loses some advantage under
load, but none of them falls below the baseline.

We did not test beyond K equal to five, so we cannot say from this experiment
where the curve turns over.

Transition: those numbers raise a why question — acceptance, cost, and the
serving stack all contribute, and we should not collapse them into one cause.

## Slide 11 — Attribution

The accounting identity on this slide is a reminder, not a fitted decomposition.
Speedup is accepted work divided by the combined cost of drafting and verifying.

Draft quality shows up clearly in the vLLM counters. Medusa accepts 0.96 tokens
per draft versus 2.05 for EAGLE at K=5, and their concurrency-one speedups are
1.39× and 2.48×.

Draft cost is the counterexample. Classical 1B accepts more tokens per draft
(2.56) and still reports only 1.05× on eager-mode vLLM. High acceptance is not
enough if the drafter itself is expensive.

The serving stack matters for the same 1B draft: 1.05× on eager-mode vLLM versus
1.90× on graph-enabled SGLang. That gap is confounded by graph mode, so we do
not treat it as a pure algorithmic result.

Offered load still leaves EAGLE above autoregressive decoding at concurrency
sixteen, but the gains shrink because verification work grows with effective
batch times K.

These comparisons are consistent with those mechanisms. The experiment does not
separately estimate each component’s causal contribution.

Transition: given that, what should a serving team actually pick on this setup?

## Slide 12 — Serving implications

Conditional on this hardware, this model, and these two engines, the best
observed choice is EAGLE on both stacks.

At concurrency one, vLLM EAGLE-3 with K=5 reports 99.5 tokens per second, or
2.48× the same-engine AR baseline. SGLang adaptive EAGLE reports 83.0 tokens
per second, or 2.36×.

At concurrency sixteen the ranking does not change. vLLM K=5 reports 831.5
tokens per second (2.01×). SGLang adaptive reports 628.6 (1.49×).

Do not generalize the vLLM classical or Medusa rows: both include eager-mode
execution. Medusa is not available on SGLang 0.5.17 in the documentation we
used.

Transition: before we close, we should be explicit about what this evidence
cannot support.

## Slide 13 — Limitations

Read the trend, not the third decimal. This is one published run per
configuration after warmup, with no error bars.

What we measured is Llama-3.1-8B-Instruct on an NVIDIA L40 with 48 GB, BF16,
greedy decoding at temperature zero, sixteen short prompts, vLLM 0.27.1 and
SGLang 0.5.17.

Outside this study: 70B or MoE models, A100 or H100, sampled decoding,
production traffic, and statistical confidence intervals.

The internal confound is that vLLM classical 1B and Medusa used eager mode
while SGLang retained CUDA graphs. Acceptance analysis is also vLLM-primary
because equivalent SGLang counters were unavailable.

Transition: those caveats in place, here is what we can still conclude.

## Slide 14 — Conclusions

There is no universal speculative-decoding speedup. Across the configurations
we published, the project-reported range is 2.48× to 0.90×.

Ranking: EAGLE-3 is first on both engines at concurrency one and remains first
at concurrency sixteen.

Load: EAGLE gains shrink but remain positive at concurrency sixteen on this
L40. The often-cited batch crossover did not occur for EAGLE here; it did
occur for eager-mode vLLM classical speculation.

Attribution: acceptance, draft cost, graph mode, checkpoint, and engine
implementation all matter.

A useful serving claim names the draft method, the engine, the hardware, and
the offered load.

Transition: the last slide is the evidence trail, not a bibliography dump.

## Slide 15 — Appendix

The measurements live in results/table_latest.json. The shared client is
bench/run.py. Server settings are in configs/. Every published cell completed
16 of 16 requests. The code and published table are at
https://github.com/bharaththiruveedula/benchmark-speculative-decoding

Independent verification still needs raw logs, the exact warmup trace, and
repeated runs.

The architecture citations are Leviathan et al. for speculative decoding,
Cai et al. for Medusa, and Li et al. for EAGLE-3, plus the vLLM and SGLang
speculative-decoding docs and the NVIDIA L40 specifications.

Benchmark values are project-reported. Hardware and method statements are tied
to those primary sources.

