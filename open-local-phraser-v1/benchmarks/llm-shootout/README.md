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
raw JSONL before scoring. On 2026-09-07 the full 64-case FreeLLMAPI comparison
selected `gemma-4-31b` over `llama-3.3-70b-fp8-fast`: Gemma scored 57/64 with
two hard-gate failures and a 0.51-second median; Llama scored 59/64 with three
hard-gate failures and a 0.62-second median. These automatic scores are
selection evidence only; the production app still applies its own gates and
falls back closed.

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
