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

For the Kaggle CUDA/T4 execution target and pinned candidate roster, see
`KAGGLE_2XT4_RUN.md` and `kaggle-candidate-roster.json`.

---

## 0. Validate the benchmark package

Before running a model:

```bash
bash self-check-english-core.sh
```

The package validator cross-checks each shadow generative metric against both
`english-core-generative-metric-contract.json` and the dimension's `metrics`
list in `english-core-config.json`. Keep that list complete when the frozen
seed changes; this is contract validation, not a post-result scoring adjustment.

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

Decoding and prompt adaptation are interpreted through one versioned runtime-neutral registry (`english_core_runtime_semantics.py`, documented in `ENGLISH_CORE_RUNTIME_SEMANTICS.md`). A run's native values are preserved exactly and compared only in their logical form, so vLLM `topK=-1` and llama.cpp `topK=0` both mean top-k disabled without either backend falsifying what it sent, and a registered chat-template implementation (`tokenizer.apply_chat_template` or the llama.cpp embedded template) satisfies the logical `chat_template` contract. Unknown sentinels and unknown adaptation strings fail closed. The validator report records the registry version, the normalized decoding view with raw values intact, and any schema bound it superseded.

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

The analyzer refuses to compute anything until the benchmark snapshot it is about to read is the exact snapshot the score was computed against. Before any statistic runs it hashes the config/weights, the private seed, the model-visible shadow task file, the shadow manifest, and the generative metric contract, and compares each hash to the `benchmarkInputs` block the scorer recorded. A mismatch, or a legacy score that names none of those hashes, is a hard failure — re-running under today's weights or seed would silently change the meaning of the result, so the analysis stops instead.

Useful flags:

- `--benchmark-dir <dir>` — the directory holding the snapshot the score names. Defaults to the analyzer's own directory, which is correct only when the score was produced from that same checkout.
- `--source-score-manifest <file>` — a manifest of expected source score file hashes. Pass this when the score artifact must be provably unedited since scoring; an edited score is refused even if it is otherwise internally consistent.
- `--score-view strict|recoverable_anchored` — analyze a specific issue #64 score view. Only views the score artifact actually declares are accepted, and substituting the primary `recoverable_anchored` view is recorded explicitly in the report rather than done silently.

Every derived report carries a `provenance` block binding the source score file hash, the scorer and analyzer script hashes, the chosen score view, the bootstrap seed and iteration count, and the verified hash of every consumed benchmark input. A derived report can be re-checked or deliberately re-analyzed only against the same bytes it was derived from.

Inspect both:

- **item-bootstrap 95% intervals** — conditional on the current shadow items;
- **phenomenon hierarchical-bootstrap sensitivity** — resamples phenomenon groups and then items within the selected groups to probe dependence among cases sharing linguistic phenomena/templates.

The hierarchical lane is a **sensitivity analysis**, not a population-confidence claim. Pari's phenomena were deliberately designed rather than randomly sampled from all English usage, and the benchmark does not invent a universal minimum number of phenomenon groups.

Neither uncertainty lane turns the hand-authored shadow set into an i.i.d. sample of universal English. Wide intervals or a large item-vs-hierarchical discrepancy weaken fine-grained model claims.

Research context for this treatment is recorded in the analyzer itself, including bootstrap NLP evaluation work and hierarchical/nested-data uncertainty literature. The exact choice to group by Pari `phenomenon` tags remains an application-specific engineering decision and is disclosed as such.

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

This is a **robustness gate**, not an eighth weighted English dimension. The rationale is grounded in published evidence that LLM multiple-choice decisions and leaderboard rankings can change under option-order perturbations.

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

The manifest records the requested revisions, resolved Hugging Face dataset fingerprints, and `datasets` library version. PAWS is loaded from its canonical Hub ID, `google-research-datasets/paws`. A manifest containing `mutable_default_not_pinned` is exploratory evidence only.

For SemanticQA, the builder defaults to the official 305-row
`collocation_categorization_prepared.tsv` member. Do not select the neighboring
collocation-extraction table just because it has the same row count and label
set; the LCC protocol is specifically categorization.

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

### Strict and recoverable forced-choice score views

The prompted forced-choice lanes (public-fast, full-distribution classification, and the
Pari shadow lane) report **two parallel frozen views** of the same preserved raw outputs,
per item and per group:

- **strict** (`strictAccuracyFixedDenominator`, `strictValidOutputCoverage`): the output
  must be the bare allowed option label (`A`, `A.`, `A)`, `A:`, `A-`) inside the task's
  frozen `allowedChoices`;
- **recoverable anchored** (`recoverableAccuracyFixedDenominator`,
  `recoverableValidOutputCoverage`): the already-declared answer wrappers
  (`Answer: A`, `The answer is A`, `Option A`, `I choose A`) and an anchored label followed
  by an explanation are tolerated, still subject to the same frozen allowed set.

Both views come from one parse of the preserved raw output. The gold label is compared
after parsing and is never used to select, accept, or repair a parse, so a correct
recoverable answer can never move strict accuracy and a format-recovery gain is never
reported as a model-generation gain.

Fixed denominator policy `fixed-screening-denominator-v1`: every task instance in the
lane is exactly one unit of the denominator. A protocol failure (invalid label, ambiguity,
non-answer, truncated or missing output) is a zero for its view and stays separately
labelled in the per-item `outcome` and the aggregate `outcomes` counts, so "allowed option
selected incorrectly" (a linguistic/task miss) never collapses into "invalid protocol
output". A runtime-unqualified or short run is excluded from the denominator entirely and
reported under `runtimeQualification`, so infrastructure failure never becomes an English
zero.

The pre-#64 keys `accuracyInvalidAsWrong` and `validOutputCoverage` are kept for existing
consumers and now carry `accuracyInvalidAsWrongScoreView` /
`validOutputCoverageScoreView: "recoverable_anchored"` so they are no longer read as strict
letter-only accuracy. Each score artifact also publishes a `scoreView` block
(`strict-recoverable-choice-views-v1`) binding the contract version, denominator policy,
allowed-label contract version, both metric keys, the selected/primary view, and the
SHA-256 of the contract and parser bytes. `analyze-english-core-statistics.mjs` and
`compare-english-core-models.mjs` read that block and refuse a comparison whose two sides
name different views.

Native/official benchmark lanes (for example SemanticQA LCC with its `answerProtocol:
"label"` rows) keep their own official evaluator contract and are not routed through these
letter-protocol views.

---

## 8. Run full-distribution prompted WiC / CoLA / PAWS

This lane keeps the locally scoreable public validation distributions instead of the fast screen's balancing.

This is a **finalist preparation lane**, separate from the balanced 1,943-case
common screen. Its full-distribution rows are never added to that screen, and
`prepare-kaggle-benchmark.py` does not build it.

### 8.1 Source identity is frozen, not remembered

`english_core_public_sources.py` owns one canonical Hub repository ID, config,
and split per source, and both public lanes read that table, so the screen and
this lane cannot name different repositories for the same source. In particular
PAWS is `google-research-datasets/paws`, config `labeled_final`, split
`validation`. The bare `paws` name is an HTTP 307 redirect to that repository,
so it has no independent commit history and is never loaded.

Every requested revision — including an omitted default, a branch, or a tag —
is resolved **once** through `HfApi.dataset_info(repo_id, revision=ref).sha` to
a full 40-hex commit, that commit is proved to live in the named repository, and
the load then uses the commit rather than the moving ref. A source that moves
after resolution cannot change an in-flight build. The manifest records
`requestedRevision` and `resolvedRevision` separately, plus the `datasets`
fingerprint and the data-prep environment identity.

The frozen revisions live in a versioned file,
`english-core-public-full-sources.json`, rather than in CLI memory:

| Source | Hub repo | Config | Split | Frozen commit | Validation rows |
| --- | --- | --- | --- | --- | --- |
| WiC | `aps/super_glue` | `wic` | `validation` | `3de24cf8022e94f4ee4b9d55a6f539891524d646` | 638 |
| CoLA | `nyu-mll/glue` | `cola` | `validation` | `bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c` | 1043 |
| PAWS | `google-research-datasets/paws` | `labeled_final` | `validation` | `161ece9501cf0a11f3e48bd356eaa82de46d6a09` | 8000 |

The WiC, CoLA, and PAWS commits are the same ones the common screen already
uses, so a pinned public-fast run and a pinned finalist run read the same bytes.

### 8.2 Prepare the lane and freeze its receipt

Run preparation in the locked data-preparation environment (#52). It builds the
lane with `--promotion --lock-sources-to-config`, hashes the task, answer, and
manifest files, freezes the ordered task-ID digest, binds the checkout through
the runner's git identity contract (#40), and writes a receipt:

```bash
python prepare-english-core-public-full.py \
  --benchmark-revision BENCHMARK_GIT_COMMIT
```

Verify an existing receipt without rebuilding:

```bash
python prepare-english-core-public-full.py --verify-only \
  --receipt english-core-public-full-classification.preparation.json \
  --benchmark-revision BENCHMARK_GIT_COMMIT
```

The receipt refuses to be promotion-eligible when the locked data-prep hash
lock cannot be verified for the current profile or the benchmark tree is not
clean. Off the qualified Kaggle profile, `--allow-unlocked-environment` and
`--allow-dirty-tree` produce a working receipt that is explicitly **not**
promotion evidence.

For a promotion build with explicit commits:

```bash
python build-english-core-public-full-classification.py \
  --super-glue-revision SUPER_GLUE_DATASET_COMMIT \
  --glue-revision GLUE_DATASET_COMMIT \
  --paws-revision PAWS_DATASET_COMMIT \
  --promotion
```

`--promotion` fails closed **before loading anything** if a revision is omitted,
is a moving ref, is non-canonical, does not resolve to a full commit, or belongs
to another repository. Omitting `--promotion` still builds, but the manifest is
marked `promotionEligible: false` and names its own reasons; a matching
task-file hash alone never upgrades it.

### 8.3 Run and score

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

For finalist evidence, score with `--promotion` so a mutable or ambiguous
source manifest is refused:

```bash
python score-english-core-public-full-classification.py public-full-result.json \
  --promotion > public-full-score.json
```

The exact gate the scorer must apply is specified in `SCORER_SOURCE_GATE.md`.

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

The comparator binds both source score files to the benchmark snapshot before it pairs anything, and accepts the same `--benchmark-dir`, `--source-score-manifest`, and `--score-view` flags as the analyzer. A headline comparison also requires both models to declare the *same* score view: pairing a strict-view score against a `recoverable_anchored`-view score is refused, because the difference would partly measure protocol strictness rather than model quality.

The comparator reports per-dimension and composite paired bootstrap differences. If the paired interval includes zero, the result is **inconclusive**. It will not manufacture a headline comparison from a partial intersection. The report's `provenance` block records both score file hashes, the scorer and comparator hashes, the shared score view, the bootstrap seed/iterations, and the consumed benchmark input hashes.

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
- materially different item-vs-hierarchical intervals — dependence/coverage warning;
- ranking flip under product/equal weights — product-prior sensitive;
- native/prompted ranking flip — adaptation/protocol sensitive.

---

## 16. Required selection order

For serious base-model selection:

1. Package/self-check.
2. Canonical shadow profile.
3. Shadow item-bootstrap + phenomenon hierarchical-bootstrap sensitivity.
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
