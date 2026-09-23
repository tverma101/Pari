# Pari local-model shootout harness

This directory contains **research runners** for comparing local generation backends. It does not promote a production model by itself.

The current V1 product contract is defined in:

- `../english-studio-v3/PROJECT_PLAN.md`
- `../english-studio-v3/V1_SHOOTOUT.md`
- `../english-studio-v3/v1-candidates.json`
- `../english-studio-v3/v1-prompt-contracts.json`

## V1 target

Pari is a human-controlled rewriting studio:

```text
paragraph -> useful starting draft
selected word/phrase/sentence -> fast context-aware alternatives
human chooses / mixes / types / reverts
```

The highest-priority benchmark is therefore **interactive alternatives**, not only top-1 paragraph repair.

## Build the internal V1 core

```bash
node benchmarks/english-studio-v3/build-v1-core.mjs
```

This writes:

- `benchmarks/english-studio-v3/v1-core.internal.jsonl`
- `benchmarks/english-studio-v3/v1-core.manifest.json`

The builder deliberately does not fabricate selected spans from paragraph corpora. External human-reference suites such as Smart Word Suggestions and TSAR remain separate evaluation modules.

## Direct MLX V1 runner

Use for checkpoints that load directly with `mlx-lm`:

```bash
python benchmarks/llm-shootout/run_v1_mlx.py \
  /path/to/model \
  benchmarks/llm-shootout/results/model-v1.jsonl \
  --model-id exact/model-id-or-revision
```

Smoke-test one route:

```bash
python benchmarks/llm-shootout/run_v1_mlx.py \
  /path/to/model \
  /tmp/pari-v1-word.jsonl \
  --route word_phrase_alternatives \
  --limit 10
```

## OpenAI-compatible V1 runner

Use for llama.cpp, Bonsai-compatible servers, rapid-mlx, or any other local runtime exposing `/v1/chat/completions`:

```bash
python benchmarks/llm-shootout/run_v1_openai_compatible.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model exact-runtime-model-id \
  --out benchmarks/llm-shootout/results/model-v1.jsonl
```

Runtime-specific request fields can be passed without changing the benchmark contract:

```bash
--chat-template-kwargs '{"enable_thinking": false}'
--extra-body '{"seed": 1234}'
```

## Shared task semantics

`v1_runner_common.py` owns:

- paragraph/span/sentence prompt rendering;
- rewrite-strength behavior;
- correlated strength-job expansion;
- candidate-list parsing;
- exact duplicate removal.

This keeps transport changes from silently changing the requested English behavior.

## Legacy paragraph runners

The following remain for old regression compatibility:

- `run_model.py`
- `run_openai_compatible.py`

They use the old paragraph-repair prompt and should **not** be used as the main V1 product shootout.

## Pinned first sweep

See `../english-studio-v3/v1-candidates.json`.

Required initial classes:

1. current Pari incumbent;
2. MiniCPM5-2B MLX 4-bit;
3. Qwen3.5-4B MLX 4-bit;
4. Ministral 3 8B Q4_K_M non-Qwen control;
5. Ternary Bonsai 2 27B aggressive-low-bit experiment.

Ling-3.0-tiny remains optional after the core sweep.

## Quantization

When practical, compare the same model's stronger/reference format with its deployable quantizations.

Do not treat a vendor's generic benchmark-retention percentage as proof that Pari editing quality survived compression.

Measure changes in:

- word/phrase suggestion quality;
- sentence alternatives;
- paragraph draft quality;
- semantic safety;
- candidate diversity;
- register/vocabulary drift;
- latency;
- memory.

## MTP / speculative decoding

MTP/speculation is an optional runtime lane.

Benchmark an **existing implementation first**. Do not train a new MTP head for V1 unless profiling later shows decode is the product bottleneck and no existing path solves it.

Record end-to-end first-useful-option/top-10 latency rather than only tokens/sec.

## Results

Raw generation output is intentionally preserved so candidate scoring/ranking can be replayed without burning model compute again.

Use `../english-studio-v3/v1-result-schema.json` for normalized run reports.

Do not collapse results into one universal score. Report route-specific quality/latency/memory Pareto views.

## Current known blocker

The model download/install plumbing still contains stale Qwen-specific fallback assumptions and `scripts/download-models.mjs` currently contains an orphaned `requiredFiles` fragment. Track/fix this under issue #15 before treating model-install automation as trustworthy.
