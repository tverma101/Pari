# Running Pari English Core

English Core selects candidate base LLMs by English competence before RAM, latency, quantization, MTP/speculation, or route-specific Pari product behavior are considered.

## 1. Build the fresh shadow tasks

From `open-local-phraser-v1/benchmarks/english-studio-v3`:

```bash
node build-english-core.mjs
```

This creates:

- `english-core-shadow.jsonl` — model-visible prompts with no gold answers;
- `english-core-shadow.manifest.json` — case counts and benchmark metadata.

The gold answers remain only in `english-core-shadow.seed.json`.

## 2. Run a local MLX candidate

```bash
python run-english-core-mlx.py /path/to/model shadow-result.json
```

Forced-choice items use deterministic decoding. Generative-expression items preserve raw outputs for independent scoring.

Do not wrap these prompts in the old paragraph-rewrite prompt from `benchmarks/llm-shootout/run_model.py`; doing so changes the task being measured.

## 3. Score the shadow set

```bash
node score-english-core.mjs shadow-result.json > shadow-score.json
```

Forced-choice cases are scored automatically against the seed answer key.

The full weighted shadow composite remains `null` until all generative-expression cases have approved `metricScores` and a `metricSource`. The candidate model is never allowed to grade itself.

Approved generative metric sources include:

- deterministic measurements where applicable;
- frozen human references;
- a specialized independently validated ranker/judge;
- blinded human evaluation.

A general LLM judge may be recorded as a secondary diagnostic but must not be the sole authority for the English Core score.

## 4. Run the deterministic public-fast screen

Install Hugging Face Datasets if needed:

```bash
pip install datasets
```

Build the reproducible public screen:

```bash
python build-english-core-public-fast.py
```

The builder currently draws a deterministic subset from:

- BLiMP — `nyu-mll/blimp`, 10 examples from each of 67 configs;
- WiC — `aps/super_glue`, `wic`, validation;
- CoLA — `nyu-mll/glue`, `cola`, validation;
- PAWS-Wiki — `paws`, `labeled_final`, validation.

Run the same model against those prompts:

```bash
python run-english-core-mlx.py /path/to/model public-result.json \
  --tasks english-core-public-fast.jsonl
```

Score them:

```bash
python score-english-core-public-fast.py public-result.json > public-score.json
```

This public-fast score is a screening diagnostic, not a replacement for each benchmark's official full evaluation. Always inspect the per-source results.

## 5. Run remaining public anchors separately

Use `english-core-public-anchors.json` as the source registry.

The fast builder does not yet automate SWORDS, CoInCo/LS07, the EACL lexical-collocation suite, JFLEG/GLEU, GYAFC, WritingBench/EQ-Bench, or BeDiscovER. Keep those as separate official evaluations rather than copying their data into the Pari repo without a source/license audit.

Report public-anchor results separately from the fresh shadow results. Do not collapse them into a single number until the metric normalization for that anchor is explicitly defined.

The point of the split is contamination detection:

- strong public + strong shadow = credible English competence;
- strong public + weak shadow = possible benchmark memorization/overfitting;
- weak public + strong shadow = inspect prompt/evaluation mismatch before rejecting the model.

## 6. Selection order

1. Compare English Core dimension profiles.
2. Compare the weighted fresh-shadow composite when complete.
3. Check whether public-anchor performance supports the same conclusion.
4. Only then evaluate quantization damage, RAM, latency, MTP/speculation, and runtime stability.
5. Run the normal Pari V1 route-specific acceptance suite.
6. Choose the shipping model/pipeline from the product Pareto frontier.

English Core may identify the strongest English base model. It does not automatically choose the final shipping architecture.
