# Running Pari English Core

English Core selects candidate base LLMs by English competence before RAM, latency, quantization, MTP/speculation, or route-specific Pari product behavior are considered.

Read first:

- `ENGLISH_CORE_RESEARCH_BASIS.md` — why each construct exists;
- `RESEARCH_GROUNDING_POLICY.md` — evidence/claim rules;
- `ENGLISH_CORE_ROBUSTNESS.md` — prompt, uncertainty, paired-comparison, distribution, and claim-tier rules.

A canonical score alone is not enough to declare a close winner.

## 1. Build the fresh shadow tasks

From `open-local-phraser-v1/benchmarks/english-studio-v3`:

```bash
node build-english-core.mjs
```

This creates model-visible prompts with no gold answers. Gold stays in `english-core-shadow.seed.json`.

## 2. Run a local MLX candidate

For an instruct/chat checkpoint:

```bash
python run-english-core-mlx.py /path/to/model shadow-result.json \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision REVISION \
  --quantization Q4 \
  --benchmark-revision GIT_COMMIT
```

For a base checkpoint with no chat instruction format:

```bash
python run-english-core-mlx.py /path/to/base-model shadow-result.json \
  --checkpoint-type base \
  --prompt-mode plain
```

`auto` may be used for exploration, but promotion-quality comparisons should record the actual adaptation mode and use a protocol appropriate to that checkpoint family.

The runner records the task-file SHA-256, generation seed/settings, MLX runtime version, platform information, and a raw-output hash. Artifact hashes/revisions should be supplied separately when needed for full reproducibility.

## 3. Score the fresh shadow set

```bash
node score-english-core.mjs shadow-result.json > shadow-score.json
```

Forced-choice cases use the private seed answer key with deterministic option-order reconstruction.

Generative cases enter the official composite only when every required metric has structured `metricProvenance`. Accepted primary provenance types include:

- deterministic;
- human reference;
- official benchmark metric;
- blinded human;
- specialist model **only when an explicit human-validation reference is recorded**.

A general LLM judge is a secondary diagnostic and cannot by itself fill the official generative score. A legacy free-form `metricSource` string is no longer sufficient.

## 4. Quantify shadow uncertainty

```bash
node analyze-english-core-statistics.mjs shadow-score.json > shadow-stats.json
```

This reports deterministic stratified item-bootstrap 95% intervals for every dimension and the two composites.

Interpretation limit:

> these intervals quantify resampling uncertainty conditional on the current shadow items; they do not imply the shadow set is a random sample from a universal English distribution.

With only a handful of cases in some dimensions, wide intervals are expected and are evidence against fine-grained winner claims.

## 5. Run multi-prompt robustness

Build three intent-preserving prompt variants per shadow case:

```bash
node build-english-core-prompt-robustness.mjs
```

Run them:

```bash
python run-english-core-mlx.py /path/to/model prompt-result.json \
  --tasks english-core-prompt-robustness.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat
```

Score forced-choice prompt robustness:

```bash
node score-english-core-prompt-robustness.mjs prompt-result.json > prompt-score.json
```

Inspect at least:

- mean prompt accuracy;
- worst-prompt accuracy;
- best-minus-worst prompt spread;
- all-prompts-correct rate;
- answer-consistency rate.

Do **not** inspect several prompt variants and then report only the best one.

Generative prompt robustness requires the same independent scorer/human protocol for each prompt variant and is not automatically fabricated by this script.

## 6. Run the deterministic public-fast screen

Install Hugging Face Datasets if needed:

```bash
pip install datasets
```

Build:

```bash
python build-english-core-public-fast.py
```

Current public-fast screen:

- BLiMP — 10 examples from each of 67 configs;
- WiC — 300 validation examples, label-balanced for the screen;
- CoLA — 300 validation examples, label-balanced for the screen;
- PAWS-Wiki — 300 validation examples, label-balanced for the screen.

Run:

```bash
python run-english-core-mlx.py /path/to/model public-result.json \
  --tasks english-core-public-fast.jsonl
```

Score:

```bash
python score-english-core-public-fast.py public-result.json > public-score.json
```

Inspect per-source, per-dimension, per-phenomenon results and their Wilson 95% intervals. The unweighted overall accuracy is only a convenience diagnostic.

This is a **common prompted screen**, not an official benchmark-native score. Its balanced WiC/CoLA/PAWS distributions intentionally differ from the native benchmark distributions.

## 7. Compare close models with paired statistics

After both candidates have complete `shadow-score.json` files:

```bash
node compare-english-core-models.mjs model-A-score.json model-B-score.json > A-vs-B.json
```

This aligns the same items and reports:

- A/B wins and ties;
- per-dimension paired bootstrap deltas;
- product-weighted paired delta;
- equal-weight paired delta;
- 95% paired bootstrap intervals.

If the paired interval contains zero, the script reports the result as **inconclusive**. Do not force a winner from the raw means.

## 8. Run official SWORDS lexical substitution

SWORDS is a primary lexical anchor for Pari. Use an official SWORDS benchmark file from:

`https://github.com/p-lambda/swords`

Create model prompts:

```bash
python build-swords-english-core-prompts.py /path/to/swords-v1.1_test.json.gz swords-test-prompts.jsonl
```

Run the model:

```bash
python run-english-core-mlx.py /path/to/model swords-result.json \
  --tasks swords-test-prompts.jsonl
```

Convert to the official SWORDS result format:

```bash
python convert-swords-english-core-output.py \
  /path/to/swords-v1.1_test.json.gz \
  swords-result.json \
  model.swords.lsr.json
```

Then run the **official SWORDS evaluator**, preferably in the environment/Docker workflow documented by SWORDS. Pari does not redefine the official lexical-substitution metrics.

Keep the SWORDS version, source hash, evaluator revision, output file, and official metrics with the model report.

## 9. Run official JFLEG fluency evaluation

Use an official JFLEG checkout from:

`https://github.com/keisks/jfleg`

Create prompts:

```bash
python build-jfleg-english-core-prompts.py /path/to/jfleg/dev/dev.src jfleg-dev-prompts.jsonl
```

Run:

```bash
python run-english-core-mlx.py /path/to/model jfleg-result.json \
  --tasks jfleg-dev-prompts.jsonl
```

Convert to a one-hypothesis-per-source-line file:

```bash
python convert-jfleg-english-core-output.py \
  jfleg-dev-prompts.jsonl \
  jfleg-result.json \
  hypothesis.txt
```

Evaluate with JFLEG's official four-reference GLEU script:

```bash
python ./eval/gleu.py \
  -r ./dev/dev.ref[0-3] \
  -s ./dev/dev.src \
  --hyp /path/to/hypothesis.txt
```

Use the official mean/standard-deviation/confidence-interval output rather than inventing a Pari fluency score.

## 10. Run other primary official anchors

Use `english-core-public-anchors.json` as the source registry.

Still separate/native rather than bundled into Pari:

- CoInCo / SemEval lexical substitution;
- EACL 2021 lexical-collocation benchmark;
- GYAFC;
- relevant EditEval tasks and official metrics;
- IteraTeR held-out revisions;
- BeDiscovER focused tasks;
- WritingBench only as secondary open-ended writing evidence.

Do not copy benchmark data into the repo without a source/license audit.

## 11. Interpretation / contamination

Always report public and fresh shadow evidence separately.

Patterns to investigate:

- strong public + strong shadow: consistent evidence;
- strong public + weak shadow: possible contamination/overfitting/protocol mismatch;
- weak public + strong shadow: possible domain/protocol mismatch;
- high canonical + weak multi-prompt: prompt-sensitive model;
- small mean lead + paired CI crossing zero: inconclusive.

Do not average these warnings away.

## 12. Selection order

For serious candidate selection:

1. Shadow per-dimension profile.
2. Shadow uncertainty.
3. Multi-prompt robustness.
4. Public-fast per-source screen.
5. Official SWORDS and other primary anchors relevant to the model role.
6. Official JFLEG/EditEval/other route-appropriate evaluation.
7. Paired comparison among close contenders.
8. Weight-sensitivity check.
9. Reproducibility metadata check.
10. Only then compare quantization damage, RAM, latency and runtime stability.
11. Run the normal Pari V1 product acceptance suite.

The strongest English Core candidate is not automatically the final shipping model. Product safety, latency, memory and specialist routing remain separate decisions.
