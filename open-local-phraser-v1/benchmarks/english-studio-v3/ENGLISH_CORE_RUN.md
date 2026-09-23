# Running Pari English Core

English Core screens candidate LLMs for Pari-relevant English capabilities before RAM, latency, quantization, MTP/speculation, or route-specific product behavior are considered.

Read first:

- `ENGLISH_CORE_RESEARCH_BASIS.md` — why each construct exists;
- `RESEARCH_GROUNDING_POLICY.md` — evidence/claim rules;
- `ENGLISH_CORE_ROBUSTNESS.md` — prompt, uncertainty, paired-comparison, distribution, and claim-tier rules;
- `ENGLISH_CORE_NATIVE_PROTOCOLS.md` — native/official versus prompted protocol separation;
- `ENGLISH_CORE_HUMAN_EVAL.md` — independent label/generative evaluation protocol.

A canonical score alone is not enough to declare a close winner.

## 0. Validate the benchmark package and shadow dataset

Run the package-level consistency validator:

```bash
node validate-english-core.mjs > english-core-package-validation.json
```

It checks weights, dimensions, referenced files, public-anchor metadata, result-schema provenance support, and shadow/config consistency. A pass means the package is internally coherent; it does **not** validate linguistic labels.

Then audit the shadow dataset itself:

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

Neither script validates the English labels. The current 68-case shadow set remains `author_labeled_unvalidated` until the independent annotation/adjudication protocol in `ENGLISH_CORE_HUMAN_EVAL.md` and issue #16 is completed.

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

`auto` may be used for exploration, but promotion-quality comparisons must record the actual adaptation mode and use a protocol appropriate to that checkpoint family.

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

Current inexpensive common prompted screen:

- BLiMP — 10 examples from each of 67 configs;
- WiC — 300 validation examples, label-balanced for this screen;
- CoLA — 300 validation examples, label-balanced for this screen;
- PAWS-Wiki — 300 validation examples, label-balanced for this screen.

Run and score:

```bash
python run-english-core-mlx.py /path/to/model public-fast-result.json \
  --tasks english-core-public-fast.jsonl

python score-english-core-public-fast.py public-fast-result.json \
  > public-fast-score.json
```

Inspect per-source, per-dimension and per-phenomenon results plus Wilson 95% intervals. The unweighted overall accuracy is only a convenience diagnostic.

This is a **common prompted screen**, not an official/native benchmark score. Its balanced WiC/CoLA/PAWS distributions intentionally differ from native benchmark distributions.

## 7. Run full-distribution prompted WiC / CoLA / PAWS

The fast screen intentionally changes class distributions. Before stronger public-classification claims, preserve the complete locally scoreable validation distribution:

```bash
python build-english-core-public-full-classification.py
```

Run the same candidate:

```bash
python run-english-core-mlx.py /path/to/model public-full-result.json \
  --tasks english-core-public-full-classification.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat
```

Score:

```bash
python score-english-core-public-full-classification.py \
  public-full-result.json \
  > public-full-score.json
```

Headline metrics in this lane:

- **WiC:** accuracy;
- **CoLA:** Matthews correlation coefficient (MCC);
- **PAWS:** accuracy, with additional classification diagnostics retained.

This lane preserves the public validation distribution but still uses a **zero-shot prompted generative-model adaptation**. Do not imply that this is identical to the supervised model adaptation in the original benchmark literature. The adaptation and the metric are separate pieces of provenance.

Invalid/missing model responses are never silently removed to improve MCC/F1.

## 8. Run native BLiMP likelihood evaluation

BLiMP's published causal-LM protocol compares the probability/likelihood of the acceptable versus unacceptable sentence rather than asking a chat A/B question.

Current MLX-LM integrates with `lm-evaluation-harness`, whose `blimp` group covers all 67 BLiMP tasks.

For a native likelihood lane:

```bash
python -m mlx_lm.evaluate \
  --model /path/to/model \
  --tasks blimp \
  --output-dir blimp-native \
  --no-apply-chat-template \
  --seed 123
```

Record the MLX-LM revision/version, lm-evaluation-harness revision/version, tokenizer/model revision, quantization and per-task/group results.

For a base causal LM, native likelihood BLiMP is the preferred grammar anchor. For an instruct/chat checkpoint, report both native likelihood and the common prompted screen. If they disagree, report **protocol sensitivity** rather than averaging them together.

See `ENGLISH_CORE_NATIVE_PROTOCOLS.md`.

## 9. Compare close models with paired statistics

After both candidates have complete shadow score files:

```bash
node compare-english-core-models.mjs \
  model-A-score.json \
  model-B-score.json \
  > A-vs-B.json
```

The comparison aligns identical items and reports:

- A/B wins and ties;
- per-dimension paired bootstrap deltas;
- product-weighted paired delta;
- equal-weight paired delta;
- 95% paired bootstrap intervals.

If the paired interval contains zero, report the comparison as **inconclusive** rather than forcing a winner from raw means.

## 10. Run official SWORDS lexical substitution

SWORDS is the highest-priority external lexical anchor for Pari.

Use an official SWORDS benchmark file and preserve its version/hash.

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

## 11. Run official JFLEG fluency evaluation

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

Evaluate with JFLEG's official four-reference GLEU workflow. Use the official evaluator output rather than inventing a Pari replacement metric.

## 12. Run other primary/native anchors

Use `english-core-public-anchors.json` as the protocol-aware source registry.

Relevant separate/native evaluations include:

- CoInCo / SemEval lexical substitution;
- EACL 2021 lexical-collocation benchmark;
- GYAFC;
- EditEval relevant tasks and documented task metrics;
- IteraTeR held-out revisions;
- BeDiscovER focused tasks.

WritingBench and EQ-Bench creative-writing diagnostics remain **secondary evidence**, not primary editing anchors.

Do not copy benchmark data into Pari without a source/license audit.

## 13. Human validation/evaluation

For strong claims, follow `ENGLISH_CORE_HUMAN_EVAL.md`.

Keep two jobs separate:

1. **objective shadow-label validation** — annotators do not see the author's answer or model outputs; ambiguous gold items are adjudicated/removed;
2. **subjective generative comparison** — blinded randomized model outputs, criterion-specific ratings/pairwise judgments, ties preserved, raw disagreement retained.

Do not force stylistic preference into a fake categorical gold label.

## 14. Interpretation / contamination

Always report four evidence lanes separately where available:

1. public native/official;
2. public full-distribution prompted;
3. public fast prompted;
4. fresh shadow.

Patterns to investigate:

- strong public + strong shadow: consistent evidence;
- strong public + weak shadow: possible contamination/overfitting/protocol mismatch;
- weak public + strong shadow: possible domain/protocol mismatch;
- native vs prompted disagreement: protocol/adaptation sensitivity;
- high canonical + weak multi-prompt: prompt-sensitive model;
- small mean lead + paired CI crossing zero: inconclusive;
- ranking flip under equal/product weighting: weight-sensitive capability tradeoff.

Do not average these warnings away.

## 15. Selection order

For serious candidate selection:

1. Package validation + shadow audit.
2. Canonical shadow per-dimension profile.
3. Shadow uncertainty.
4. Multi-prompt robustness.
5. Public-fast per-source screen.
6. Full-distribution prompted WiC/CoLA/PAWS.
7. Native BLiMP likelihood evaluation.
8. Official SWORDS and other primary anchors relevant to the role.
9. Official JFLEG/EditEval/other route-appropriate evaluation.
10. Paired comparison among close contenders.
11. Weight/protocol sensitivity.
12. Reproducibility metadata check.
13. Only then evaluate quantization damage, RAM, latency and runtime stability.
14. Run the separate Pari V1 product acceptance suite.

English Core narrows the candidate field. The final shipping model/router remains a product Pareto decision across linguistic quality, semantic safety, latency, memory and specialist routing.