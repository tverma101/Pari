# Running Pari English Core

English Core compares candidate LLMs on Pari-relevant English capabilities before RAM, latency, quantization, MTP/speculation, or route-specific product behavior are allowed to decide the shipping model.

It is a **multi-lane evidence profile**, not one universal English-IQ test.

Read first:

- `ENGLISH_CORE_RESEARCH_BASIS.md` — construct evidence;
- `RESEARCH_GROUNDING_POLICY.md` — evidence/claim rules;
- `ENGLISH_CORE_ROBUSTNESS.md` — prompt/order/statistical/distribution rules;
- `ENGLISH_CORE_NATIVE_PROTOCOLS.md` — official/native versus prompted adaptations;
- `ENGLISH_CORE_HUMAN_EVAL.md` — independent label and generative evaluation.

A canonical score alone is not enough to declare a close winner.

---

## 0. Validate the benchmark package

Before running a model:

```bash
./self-check-english-core.sh
```

This runs the package validator, shadow structural audit, JS/Python choice-parser regression tests, rebuilds the shadow/prompt/order task files, and verifies that model-visible JSONL does not expose gold fields.

The structural checks **do not validate the English labels**. The current 68-case shadow seed remains `author_labeled_unvalidated` until the independent procedure in `ENGLISH_CORE_HUMAN_EVAL.md` is completed.

---

## 1. Build the canonical fresh shadow tasks

```bash
node build-english-core.mjs
```

The generated `english-core-shadow.jsonl` contains model prompts without gold answers. Gold remains private in `english-core-shadow.seed.json`.

---

## 2. Run a local MLX candidate

For an instruct/chat checkpoint:

```bash
python run-english-core-mlx.py /path/to/model shadow-result.json \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization q4 \
  --benchmark-revision BENCHMARK_GIT_COMMIT
```

For a base checkpoint:

```bash
python run-english-core-mlx.py /path/to/base-model shadow-result.json \
  --checkpoint-type base \
  --prompt-mode plain \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization full \
  --benchmark-revision BENCHMARK_GIT_COMMIT
```

`--prompt-mode auto` is allowed for exploration only. Promotion-quality comparisons require explicit adaptation and complete artifact metadata.

The runner records task hash/count, model/runtime metadata, tokenizer identity, chat-template hash where available, prompt-adaptation path, decoding settings, hardware, cold load, and raw-output hash.

Validate the run metadata:

```bash
python validate-english-core-run.py shadow-result.json
```

For a result that will support promotion/model selection:

```bash
python validate-english-core-run.py shadow-result.json --promotion
```

Promotion validation rejects ambiguous adaptation, unknown model revision/quantization/checkpoint type, missing artifact/task hashes, incomplete decoding provenance, mixed prompt adaptation, and other reproducibility failures.

---

## 3. Score the fresh shadow set

```bash
node score-english-core.mjs shadow-result.json > shadow-score.json
```

Forced-choice cases use the private seed plus deterministic option-order reconstruction.

Generative cases enter the shadow composite only when every required criterion has a normalized `metricScores` observation and approved structured `metricProvenance`.

The direction of each generative criterion is defined in `english-core-generative-metric-contract.json`. Failure rates such as `stock_phrase_rate` and `length_inflation` are preserved as raw rates and converted to higher-is-better utility only by the scorer. Do not manually invert them upstream.

A general-purpose LLM judge is secondary evidence and cannot by itself fill the official generative component.

---

## 4. Quantify uncertainty

```bash
node analyze-english-core-statistics.mjs shadow-score.json > shadow-stats.json
```

Inspect both:

- **item-bootstrap 95% intervals** — conditional on the current shadow items;
- **phenomenon-cluster sensitivity intervals** — a dependence sensitivity check for cases sharing linguistic phenomena/templates.

The cluster interval is explicitly exploratory when there are few phenomenon clusters. Neither interval turns the hand-authored shadow set into an i.i.d. sample of universal English.

Wide intervals or a large item-vs-cluster discrepancy weaken fine-grained model claims.

---

## 5. Run multi-prompt robustness

Build three intent-preserving prompt variants:

```bash
node build-english-core-prompt-robustness.mjs
```

Run:

```bash
python run-english-core-mlx.py /path/to/model prompt-result.json \
  --tasks english-core-prompt-robustness.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization q4 \
  --benchmark-revision BENCHMARK_GIT_COMMIT
```

Score:

```bash
node score-english-core-prompt-robustness.mjs prompt-result.json > prompt-score.json
```

Inspect mean prompt accuracy, worst-prompt accuracy, spread, all-prompts-correct rate, and answer consistency. Never select the best prompt after observing model results and report only that one.

Generative prompt robustness must use the same independent metric/human protocol across variants; it is not automatically fabricated by the forced-choice scorer.

---

## 6. Run counterbalanced choice-order robustness

A single randomized order is not enough for close contenders. Build two different option-position presentations per forced-choice shadow item:

```bash
node build-english-core-choice-order-robustness.mjs
```

Run:

```bash
python run-english-core-mlx.py /path/to/model order-result.json \
  --tasks english-core-choice-order-robustness.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization q4 \
  --benchmark-revision BENCHMARK_GIT_COMMIT
```

Score:

```bash
node score-english-core-choice-order-robustness.mjs order-result.json > order-score.json
```

Primary diagnostics:

- `bothOrdersCorrectRate`;
- `semanticAnswerConsistencyRate`;
- `oneCorrectOneWrongRate`;
- per-presentation accuracy.

This is a **robustness gate**, not an eighth weighted English dimension.

---

## 7. Run the public-fast screen

Install Hugging Face Datasets if needed:

```bash
pip install datasets
```

For exploration:

```bash
python build-english-core-public-fast.py
```

For promotion-quality evidence, pin immutable source revisions/commits:

```bash
python build-english-core-public-fast.py \
  --blimp-revision BLIMP_DATASET_COMMIT \
  --super-glue-revision SUPER_GLUE_DATASET_COMMIT \
  --glue-revision GLUE_DATASET_COMMIT \
  --paws-revision PAWS_DATASET_COMMIT
```

The manifest records the requested revisions, resolved Hugging Face dataset fingerprints, and `datasets` library version. A manifest containing `mutable_default_not_pinned` is exploratory evidence only.

Current fast screen:

- BLiMP — 10 examples from each of 67 configurations;
- WiC — 300 label-balanced validation examples;
- CoLA — 300 label-balanced validation examples;
- PAWS-Wiki — 300 label-balanced validation examples.

Run and score:

```bash
python run-english-core-mlx.py /path/to/model public-fast-result.json \
  --tasks english-core-public-fast.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization q4 \
  --benchmark-revision BENCHMARK_GIT_COMMIT

python score-english-core-public-fast.py public-fast-result.json > public-fast-score.json
```

This is a balanced **common prompted screen**, not an official benchmark-native score. Source/dimension/phenomenon results matter more than the convenience overall accuracy.

---

## 8. Run full-distribution prompted WiC / CoLA / PAWS

This lane keeps the locally scoreable public validation distributions instead of the fast screen's balancing.

For promotion-quality runs, pin the same immutable dataset revisions:

```bash
python build-english-core-public-full-classification.py \
  --super-glue-revision SUPER_GLUE_DATASET_COMMIT \
  --glue-revision GLUE_DATASET_COMMIT \
  --paws-revision PAWS_DATASET_COMMIT
```

Run and score:

```bash
python run-english-core-mlx.py /path/to/model public-full-result.json \
  --tasks english-core-public-full-classification.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization q4 \
  --benchmark-revision BENCHMARK_GIT_COMMIT

python score-english-core-public-full-classification.py public-full-result.json > public-full-score.json
```

Report:

- WiC accuracy;
- CoLA Matthews correlation coefficient when all predictions are valid;
- PAWS accuracy;
- valid-output coverage and confusion information.

This is still **zero-shot prompted adaptation**, not the supervised adaptation used in the original benchmark papers. Name the adaptation explicitly.

---

## 9. Run native BLiMP grammar evaluation

BLiMP's primary grammar evidence is sentence/minimal-pair likelihood, not a chat question. Current MLX-LM integrates with `lm-evaluation-harness`, which exposes the 67-task BLiMP group.

Use the native lane described in `ENGLISH_CORE_NATIVE_PROTOCOLS.md`. For a base model, avoid applying a chat template unless a separate protocol explicitly requires it.

A typical MLX-LM/lm-eval invocation is conceptually:

```bash
python -m mlx_lm.evaluate \
  --model /path/to/model \
  --tasks blimp \
  --no-apply-chat-template \
  --output-dir ./blimp-native-results
```

Record exact MLX-LM/lm-eval versions, model revision/artifact, source revision, and output files. The prompted BLiMP fast screen and native BLiMP result must remain separate.

---

## 10. Run official SWORDS lexical substitution

SWORDS is the highest-priority public lexical anchor for Pari.

Create model prompts from an official SWORDS benchmark file:

```bash
python build-swords-english-core-prompts.py \
  /path/to/swords-v1.1_test.json.gz \
  swords-test-prompts.jsonl
```

Run the model, convert to official result format, then use the **official SWORDS evaluator**:

```bash
python run-english-core-mlx.py /path/to/model swords-result.json \
  --tasks swords-test-prompts.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization q4 \
  --benchmark-revision BENCHMARK_GIT_COMMIT

python convert-swords-english-core-output.py \
  /path/to/swords-v1.1_test.json.gz \
  swords-result.json \
  model.swords.lsr.json
```

Pari does not redefine SWORDS metrics. Preserve SWORDS source/version/hash, evaluator revision, candidate output, and official metrics.

---

## 11. Run official JFLEG fluency evaluation

Create prompts from an official JFLEG checkout:

```bash
python build-jfleg-english-core-prompts.py \
  /path/to/jfleg/dev/dev.src \
  jfleg-dev-prompts.jsonl
```

Run, convert, and evaluate with the official four-reference GLEU workflow:

```bash
python run-english-core-mlx.py /path/to/model jfleg-result.json \
  --tasks jfleg-dev-prompts.jsonl \
  --checkpoint-type instruct \
  --prompt-mode chat \
  --model-revision MODEL_REVISION \
  --artifact-sha256 MODEL_ARTIFACT_SHA256 \
  --quantization q4 \
  --benchmark-revision BENCHMARK_GIT_COMMIT

python convert-jfleg-english-core-output.py \
  jfleg-dev-prompts.jsonl \
  jfleg-result.json \
  hypothesis.txt
```

Then run JFLEG's official GLEU evaluator. Preserve its native mean/uncertainty output rather than inventing a replacement Pari fluency metric.

---

## 12. Other primary anchors

`english-core-public-anchors.json` is the canonical protocol-aware source registry.

Still pending/native-external lanes include:

- CoInCo / SemEval lexical substitution;
- EACL 2021 lexical-collocation benchmark;
- GYAFC;
- EditEval relevant editing tasks;
- IteraTeR held-out revisions;
- BeDiscovER focused discourse tasks.

`english-core-sources.json` is only a compact compatibility/status view.

WritingBench and EQ-Bench creative-writing diagnostics remain **secondary evidence**. They cannot overrule editing/lexical anchors for Pari.

Do not copy benchmark data into the repo without source/license review.

---

## 13. Compare close models with paired statistics

Both score files must come from identical benchmark inputs and identical model-visible task files, and both models must have complete aligned scoring.

```bash
node compare-english-core-models.mjs \
  model-A-shadow-score.json \
  model-B-shadow-score.json \
  > A-vs-B.json
```

The comparator reports per-dimension and composite paired bootstrap differences. If the paired interval includes zero, the result is **inconclusive**. It will not manufacture a headline comparison from a partial intersection.

---

## 14. Human validation/evaluation

For stronger claims, follow `ENGLISH_CORE_HUMAN_EVAL.md`.

Keep two jobs separate:

1. objective shadow-label validation — annotators do not see author gold or model outputs; ambiguous gold items are adjudicated/removed;
2. subjective generative comparison — blinded/randomized outputs, criterion-specific pairwise judgments, ties preserved, raw disagreement retained.

The current shadow set remains internal/fresh-surface evidence until that validation gate is completed.

---

## 15. Interpretation and contamination

Always report these lanes separately:

1. public-native / official evidence;
2. full-distribution public prompted evidence;
3. balanced public-fast screen;
4. fresh Pari shadow evidence;
5. prompt/order/statistical robustness diagnostics.

Patterns to investigate rather than average away:

- strong public + strong shadow — consistent evidence;
- strong public + weak shadow — possible contamination, benchmark overfitting, or protocol mismatch;
- weak public + strong shadow — possible domain/protocol mismatch;
- strong canonical + weak multi-prompt — prompt-sensitive;
- strong single-order + weak both-orders-correct — option-position sensitive;
- small mean lead + paired CI crossing zero — inconclusive;
- materially different item-vs-cluster intervals — dependence/coverage warning;
- ranking flip under product/equal weights — product-prior sensitive;
- native/prompted ranking flip — adaptation/protocol sensitive.

---

## 16. Required selection order

For serious base-model selection:

1. Package/self-check.
2. Canonical shadow profile.
3. Shadow item + cluster-sensitive uncertainty.
4. Multi-prompt robustness.
5. Counterbalanced option-order robustness.
6. Public-fast screen.
7. Full-distribution prompted public classification.
8. Native BLiMP.
9. Official SWORDS.
10. Official JFLEG and relevant EditEval/IteraTeR/other primary anchors as available.
11. Paired comparisons for close contenders.
12. Product-weight versus equal-weight and protocol sensitivity review.
13. Promotion-run metadata validation and reproducibility manifest.
14. Only then evaluate quantization damage, RAM, latency, and runtime stability.
15. Run the separate Pari V1 route-specific product acceptance suite.

English Core narrows the candidate field. It does not automatically choose the shipping model/router.
