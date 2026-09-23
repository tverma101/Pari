# Running Pari English Core

English Core screens candidate base LLMs for Pari-relevant English capabilities before RAM, latency, quantization, MTP/speculation, or route-specific product behavior are considered.

Read first:

- `ENGLISH_CORE_RESEARCH_BASIS.md` — why each construct exists;
- `RESEARCH_GROUNDING_POLICY.md` — evidence/claim rules;
- `ENGLISH_CORE_ROBUSTNESS.md` — prompt, uncertainty, paired-comparison, distribution, and claim-tier rules;
- `ENGLISH_CORE_HUMAN_EVAL.md` — independent label/generative evaluation protocol.

A canonical score alone is not enough to declare a close winner.

## 0. Audit the fresh shadow dataset

Before generating prompts or running any model:

```bash
node audit-english-core-shadow.mjs > shadow-audit.json
```

The audit checks:

- duplicate IDs and duplicate task payloads;
- malformed or non-unique gold choices;
- missing dimensions/tasks/phenomenon tags;
- cases-per-dimension and phenomena-per-dimension;
- binary-label distribution diagnostics;
- suspiciously similar within-dimension items;
- minimum generative scoring-contract structure.

Hard structural errors produce a failing exit code. Distribution/similarity concerns are warnings for review.

This **does not validate the English labels**. The current 68-case shadow set remains `author_labeled_unvalidated` until the independent annotation/adjudication protocol in `ENGLISH_CORE_HUMAN_EVAL.md` and issue #16 is completed.

## 1. Build the fresh shadow tasks

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

The runner records the task-file SHA-256, generation settings, MLX runtime version, platform information, and raw-output hash. Exact model artifact hashes/revisions should be preserved for promotion-quality evidence.

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
- specialist model **only with explicit human-validation evidence**.

A general LLM judge is a secondary diagnostic and cannot by itself fill the official generative score. A free-form legacy `metricSource` string is insufficient.

## 4. Quantify shadow uncertainty

```bash
node analyze-english-core-statistics.mjs shadow-score.json > shadow-stats.json
```

The analyzer reports deterministic stratified item-bootstrap 95% intervals for every dimension and both composites.

Interpretation limit:

> these intervals quantify resampling uncertainty conditional on the current shadow items; they do not imply that the shadow set is an i.i.d. sample from a universal population of English.

With small dimensions, wide intervals are expected and are evidence against fine-grained winner claims.

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

Do **not** inspect several prompt variants and then report only the best one. Generative prompt robustness requires the same independent scorer/human protocol for each prompt variant.

## 6. Run the deterministic public-fast screen

Install Hugging Face Datasets if needed:

```bash
pip install datasets
```

Build:

```bash
python build-english-core-public-fast.py
```

Current common prompted screen:

- BLiMP — 10 examples from each of 67 configs;
- WiC — 300 validation examples, label-balanced for this screen;
- CoLA — 300 validation examples, label-balanced for this screen;
- PAWS-Wiki — 300 validation examples, label-balanced for this screen.

Run:

```bash
python run-english-core-mlx.py /path/to/model public-result.json \
  --tasks english-core-public-fast.jsonl
```

Score:

```bash
python score-english-core-public-fast.py public-result.json > public-score.json
```

Inspect per-source, per-dimension and per-phenomenon results plus Wilson 95% intervals. The unweighted overall accuracy is only a convenience diagnostic.

This is a **common prompted screen**, not an official benchmark-native score. Its balanced WiC/CoLA/PAWS distributions intentionally differ from native benchmark distributions.

## 7. Compare close models with paired statistics

After both candidates have complete `shadow-score.json` files:

```bash
node compare-english-core-models.mjs model-A-score.json model-B-score.json > A-vs-B.json
```

The comparison aligns identical items and reports:

- A/B wins and ties;
- per-dimension paired bootstrap deltas;
- product-weighted paired delta;
- equal-weight paired delta;
- 95% paired bootstrap intervals.

If the paired interval contains zero, report the comparison as **inconclusive** rather than forcing a winner from raw means.

## 8. Run official SWORDS lexical substitution

SWORDS is the highest-priority external lexical anchor for Pari.

Use an official SWORDS benchmark file from the project repository and preserve its version/hash.

Create model prompts:

```bash
python build-swords-english-core-prompts.py \
  /path/to/swords-v1.1_test.json.gz \
  swords-test-prompts.jsonl
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

Then run the **official SWORDS evaluator** in the environment/workflow documented by SWORDS. Pari does not redefine its lexical-substitution metrics.

Keep the SWORDS version, source hash, evaluator revision, model output and official metrics with the report.

## 9. Run official JFLEG fluency evaluation

Use an official JFLEG checkout.

Create prompts:

```bash
python build-jfleg-english-core-prompts.py \
  /path/to/jfleg/dev/dev.src \
  jfleg-dev-prompts.jsonl
```

Run:

```bash
python run-english-core-mlx.py /path/to/model jfleg-result.json \
  --tasks jfleg-dev-prompts.jsonl
```

Convert to one hypothesis per source line:

```bash
python convert-jfleg-english-core-output.py \
  jfleg-dev-prompts.jsonl \
  jfleg-result.json \
  hypothesis.txt
```

Evaluate with JFLEG's official four-reference GLEU workflow. Use its official output rather than inventing a Pari replacement metric.

## 10. Run other primary/native anchors

Use `english-core-public-anchors.json` as the source registry.

Relevant separate/native evaluations include:

- CoInCo / SemEval lexical substitution;
- EACL 2021 lexical-collocation benchmark;
- GYAFC;
- EditEval relevant tasks and official metrics;
- IteraTeR held-out revisions;
- BeDiscovER focused tasks.

WritingBench and EQ-Bench creative-writing diagnostics remain **secondary evidence**, not primary editing anchors.

Do not copy benchmark data into Pari without a source/license audit.

## 11. Human validation/evaluation

For strong claims, follow `ENGLISH_CORE_HUMAN_EVAL.md`.

Keep two jobs separate:

1. **objective shadow-label validation** — annotators do not see the author's answer or model outputs; ambiguous gold items are adjudicated/removed;
2. **subjective generative comparison** — blinded randomized model outputs, criterion-specific ratings/pairwise judgments, ties preserved, raw disagreement retained.

Do not force stylistic preference into a fake categorical gold label.

## 12. Interpretation / contamination

Always report public/native, public-prompted, and fresh-shadow evidence separately.

Patterns to investigate:

- strong public + strong shadow: consistent evidence;
- strong public + weak shadow: possible contamination/overfitting/protocol mismatch;
- weak public + strong shadow: possible domain/protocol mismatch;
- high canonical + weak multi-prompt: prompt-sensitive model;
- small mean lead + paired CI crossing zero: inconclusive;
- ranking flip under equal/product weighting: weight-sensitive capability tradeoff.

Do not average these warnings away.

## 13. Selection order

For serious candidate selection:

1. Shadow dataset audit.
2. Canonical shadow per-dimension profile.
3. Shadow uncertainty.
4. Multi-prompt robustness.
5. Public-fast per-source screen.
6. Official SWORDS and other primary anchors relevant to the role.
7. Official JFLEG/EditEval/other route-appropriate evaluation.
8. Paired comparison among close contenders.
9. Weight/protocol sensitivity.
10. Reproducibility metadata check.
11. Only then evaluate quantization damage, RAM, latency and runtime stability.
12. Run the separate Pari V1 product acceptance suite.

English Core narrows the candidate field. The final shipping model/router remains a product Pareto decision across linguistic quality, semantic safety, latency, memory and specialist routing.