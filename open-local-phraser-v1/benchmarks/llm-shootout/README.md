# Pari local-model shootout

This directory is for **generator and editing-model research**, not production model promotion.

The product target is narrow:

> Repair broken, vague, awkward English into clear, natural, maximally grammatical English while preserving every recoverable fact and inventing nothing.

A model does not become Pari's default because it wins a generic reasoning benchmark. It must beat the current controls on Pari's frozen English-repair benchmark and survive the production safety gates.

Pari should not assume that one general LLM must do every editing task. The shootout includes both general rewrite models and compact grammatical-error-correction specialists. The useful question is whether a specialist + general rewrite cascade beats either model alone on quality, safety, memory, and latency.

Current execution priority is tracked in [`docs/remaining-work.md`](../../docs/remaining-work.md).

## Existing direct MLX runner

Use `run_model.py` for checkpoints that load directly with the pinned `mlx-lm` stack:

```bash
python benchmarks/llm-shootout/run_model.py \
  /path/to/model \
  benchmarks/llm-shootout/model-output.jsonl

node benchmarks/eval/run-eval.mjs \
  --outputs benchmarks/llm-shootout/model-output.jsonl
```

That command scores the raw generator, which is useful for model selection.
To measure the output a user would receive after Pari's shared finalization
boundary, add `--production-postprocess`; it applies the same local fragment,
direct-English, collocation, flow, and grammar repairs used by the app before
running the evaluator:

```bash
node benchmarks/eval/run-eval.mjs \
  --outputs benchmarks/llm-shootout/model-output.jsonl \
  --production-postprocess
```

Keep both numbers: a postprocessed score measures the product boundary, while
the raw score remains the fair comparison of generator quality. Neither score
is a substitute for a held-out human comparison.

## Best-of-N candidate experiments

`run_candidates.py` keeps the model loaded while generating multiple drafts;
`select-best.mjs` applies the evaluator to every draft and can require the
production protected-content gate before choosing a winner. The default
schedule preserves the older greedy-first experiment. To mirror the
production Qwen3 schedule on the frozen 300-case corpus, run:

```bash
python benchmarks/llm-shootout/run_candidates.py \
  "/path/to/Qwen3-4B-MLX-4bit" \
  /tmp/pari-qwen3-frozen-candidates.jsonl \
  --corpus benchmarks/quillbot/corpus.frozen.json \
  --temperatures 0.24,0.46,0.68,0.9 --top-p 0.86 --max-tokens 220

node benchmarks/llm-shootout/select-best.mjs \
  /tmp/pari-qwen3-frozen-candidates.jsonl \
  /tmp/pari-qwen3-frozen-winners.jsonl \
  --corpus benchmarks/quillbot/corpus.frozen.json \
  --production-postprocess --production-safety

node benchmarks/eval/run-eval.mjs \
  --corpus benchmarks/quillbot/corpus.frozen.json \
  --outputs /tmp/pari-qwen3-frozen-winners.jsonl
```

The selector is an automatic research aid, not a replacement for the
production TypeScript ranker or a human/QuillBot comparison.

## Encoder-decoder research runner

T5-family editing checkpoints are not direct `mlx-lm` models. Use
`run_seq2seq.py` with the local Transformers/MPS runtime so the raw output,
task prefix, revision, license, model size, peak memory, and timing receipt
are preserved:

```bash
python benchmarks/llm-shootout/run_seq2seq.py \
  /path/to/coedit-large \
  benchmarks/paraphrase-v2/results/coedit-large.raw.jsonl \
  --corpus benchmarks/paraphrase-v2/corpus.json \
  --prompt-prefix 'Paraphrase this:' \
  --model-repo grammarly/coedit-large \
  --model-revision '<pinned-commit>' \
  --license cc-by-nc-4.0 \
  --role research-reference \
  --engine-name coedit-large-research
```

This runner is for reproducible research comparisons only; the official
CoEdIT checkpoint is non-commercial and cannot be promoted into the shipped
Pari bundle without a separate licensing decision.

The 2026-09-07 frozen-corpus replay recorded 222/300 raw and 228/300 after
Pari finalization for the deterministic Qwen3 incumbent. The production-like
best-of-four replay produced 236/300 under the normalized benchmark judge,
but 227/300 after requiring exact protected-content preservation; it was not a
production promotion. The retained artifacts are
[`raw Qwen3 output`](qwen3-4b-corpus-frozen-20260907.jsonl),
[`best-of-four candidates`](qwen3-4b-corpus-frozen-bestof4-candidates-20260907.jsonl),
[`safe winners`](qwen3-4b-corpus-frozen-bestof4-winners-safe-20260907.jsonl),
and the corresponding reports under [`../eval/`](../eval/).

## OpenAI-compatible local runner

Use `run_openai_compatible.py` for local runtimes that expose `/v1/chat/completions` but are not yet supported by Pari's direct `mlx-lm` path.

This keeps the benchmark model-agnostic and lets new Apple-Silicon runtimes compete without first wiring them into production.

The same adapter can probe FreeLLMAPI without storing its key:

```bash
FREELLM_KEY="$(pbpaste | tr -d '\r\n')"
python benchmarks/llm-shootout/run_openai_compatible.py \
  --base-url http://127.0.0.1:31415/v1 \
  --model gemma-4-31b \
  --api-key "$FREELLM_KEY" \
  --out /tmp/pari-gemma431.jsonl \
  --max-tokens 220

node benchmarks/eval/run-eval.mjs --outputs /tmp/pari-gemma431.jsonl
```

Use `--offset` and `--limit` for bounded availability probes and preserve the
raw JSONL before scoring. In the latest 2026-09-07 full 64-case FreeLLMAPI
comparison, `gemma-4-31b` scored 59/64 raw and 59/64 after Pari finalization;
`gpt-oss-120b` scored 50/64 in both views and exposed control-text/empty-style
responses. An earlier provider snapshot recorded Gemma at 57/64 versus
`llama-3.3-70b-fp8-fast` at 59/64, so dated captures should not be treated as
stable provider guarantees. These automatic scores are selection evidence
only; the production app still applies its own gates and falls back closed.

## MiniCPM5-2B candidate

Tracking issue: [#10](https://github.com/tverma101/Pari/issues/10)

Primary model card:

- https://huggingface.co/openbmb/MiniCPM5-2B

Why it is a high-priority test:

- ~2.6B dense parameters;
- Apache-2.0;
- 131k advertised context;
- intended for on-device / edge use;
- Artificial Analysis Intelligence Index v4.2 score of 15, versus an estimated 14 for Qwen3.5-4B Reasoning in the same comparison;
- substantially smaller weight footprint than the 4B benchmark control.

Those generic results do **not** establish that MiniCPM is the better Pari paraphraser. The exact test is MiniCPM5-2B vs Qwen3.5-4B vs the production Qwen3-4B backend on the frozen Pari corpus, with reasoning/thinking disabled for the normal rewrite path unless separately justified.

The 2026-09-07 temporary MLX run completed all 64 MiniCPM5-2B cases. It scored
43/64 raw and 51/64 after Pari finalization, below the retained Qwen3 product
boundary of 64/64 after finalization, so it was not promoted or installed.
The replay and both score reports are committed as
[`minicpm5-2b-mlx-outputs-20260907.jsonl`](minicpm5-2b-mlx-outputs-20260907.jsonl),
[`raw results`](../eval/results-minicpm5-2b-mlx-outputs-20260907.jsonl.json),
and [`Pari-finalized results`](../eval/results-minicpm5-2b-mlx-outputs-20260907.jsonl_pari-postprocess.json).

Save raw outputs/candidates before changing the production backend. Promotion requires zero new hard safety regressions, comparable-or-better coherence/meaning preservation, and either a product-quality win or a meaningful memory/latency win at comparable quality.

## Grammar-specialist candidates

Initial research targets:

| Candidate | Approx. size | Primary use |
| --- | ---: | --- |
| GECToR | ~355M | high-precision minimal grammar edits |
| DeCoGLM | ~335M | detect suspicious spans, then locally correct |
| BART-family GEC | ~400M | compact seq2seq grammatical correction |
| CoEdIT-large | ~770M | grammar, coherence, paraphrase, formality |

These are research targets, not pinned production dependencies. Verify checkpoint license, runtime support, and actual Pari benchmark quality before downloading or bundling anything. In particular, released CoEdIT checkpoints should be treated as research/non-commercial references unless a distributable alternative is selected.

The preferred experiment is not only `specialist vs Qwen`. Also test the cascade:

```text
input
  -> grammar specialist candidate
  -> conservative general rewrite candidate
  -> stronger general rewrite candidate
  -> original/deterministic fallback
  -> Pari safety + grammar + semantic scorer
  -> winner
```

A specialist should be rewarded for **precision**, not edit count. Unnecessary corrections and meaning drift are failures.

## Ling-3.0-tiny candidate

Tracking issue: #6

Primary model card:

- https://huggingface.co/inclusionAI/Ling-3.0-tiny

Current Apple 4-bit conversion/runtime documentation:

- https://huggingface.co/rapid-mlx/Ling-3.0-tiny-MLX-4bit

Why it is being tested:

- 7.9B total parameters
- 1.3B active parameters per token
- sparse MoE architecture
- official Apple-Silicon validation
- InclusionAI reports roughly 86-90 tokens/s on an M4 Pro MacBook with FP8 at 8K context
- the current 4-bit Apple conversion is about 4.2 GB

The architecture is newer than the current production incumbent and is **not yet a drop-in `mlx-lm` production replacement**. The current 4-bit Apple path documents `rapid-mlx` as the serving runtime while upstream `mlx-lm` support for `bailing_hybrid` catches up.

### Smoke-test Ling through the generic runner

Install/start the runtime according to the conversion's current model card, then run:

```bash
rapid-mlx serve ling-3.0-tiny-4bit

python benchmarks/llm-shootout/run_openai_compatible.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model ling-3.0-tiny-4bit \
  --out benchmarks/llm-shootout/ling3-tiny-4bit.jsonl \
  --chat-template-kwargs '{"enable_thinking": false}'

node benchmarks/eval/run-eval.mjs \
  --outputs benchmarks/llm-shootout/ling3-tiny-4bit.jsonl
```

If the runtime exposes a different model ID, pass that exact ID to `--model`; the benchmark adapter intentionally does not hard-code Ling.

## Promotion rules

Do not replace the production backend or add a second model based only on the current automatic score.

A candidate or cascade must eventually be judged on:

1. grammatical correctness and syntactic well-formedness;
2. natural English / collocations;
3. clarity and reconstruction of broken prose;
4. meaning preservation and unsupported-invention rate;
5. protected-span / negation / modality / quantity safety;
6. unnecessary-edit / overcorrection rate;
7. latency and peak memory on the target Mac;
8. installed-app/native-runtime reliability.

Qwen3.5-4B remains the **general-model benchmark control pending issue #10**. The shipped backend may differ; benchmark control and production backend are deliberately separate concepts.
