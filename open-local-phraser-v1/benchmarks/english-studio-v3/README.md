# Pari English Studio v3 benchmark

This directory is Pari's evaluation layer.

The product/model decision tree lives in [`PROJECT_PLAN.md`](./PROJECT_PLAN.md). The concrete V1 model/runtime experiment lives in [`V1_SHOOTOUT.md`](./V1_SHOOTOUT.md). Model-to-benchmark routing lives in [`BENCHMARK_MODEL_MAP.md`](./BENCHMARK_MODEL_MAP.md). Dataset provenance lives in [`dataset-ledger.json`](./dataset-ledger.json).

The benchmark has one job:

> measure whether a model or pipeline is useful for a human-controlled rewriting studio without requiring the project owner to be an expert English judge.

No single benchmark and no single scalar score decides the shipping winner.

---

# 0. Base-LLM English selection is a separate research lane

Before comparing RAM, latency or product routing, plausible base LLMs can be screened with **Pari English Core**. English Core asks a narrower question:

> which model shows the strongest evidence for Pari-relevant English capabilities under the current evaluation protocol?

That wording is deliberate. English Core is a **multi-lane evidence profile**, not a universal English-IQ test.

It separates lexical sense, contextual substitution, collocation, grammar, semantic equivalence, register/fluency, controlled generation/editing, and discourse from coding/math/general-agent ability.

Canonical English Core files:

- [`ENGLISH_CORE.md`](./ENGLISH_CORE.md) — construct/dimension overview;
- [`ENGLISH_CORE_RUN.md`](./ENGLISH_CORE_RUN.md) — required execution sequence;
- [`ENGLISH_CORE_RESEARCH_BASIS.md`](./ENGLISH_CORE_RESEARCH_BASIS.md) — primary research evidence and validity notes;
- [`ENGLISH_CORE_ROBUSTNESS.md`](./ENGLISH_CORE_ROBUSTNESS.md) — prompt/order/statistical/distribution rules and claim tiers;
- [`ENGLISH_CORE_NATIVE_PROTOCOLS.md`](./ENGLISH_CORE_NATIVE_PROTOCOLS.md) — native/official versus common prompted adaptations;
- [`ENGLISH_CORE_HUMAN_EVAL.md`](./ENGLISH_CORE_HUMAN_EVAL.md) — independent gold-label and generative human-evaluation protocols;
- [`RESEARCH_GROUNDING_POLICY.md`](./RESEARCH_GROUNDING_POLICY.md) — standing evidence rules for benchmark changes;
- `english-core-config.json` — machine-readable construct/weight/protocol contract;
- `english-core-shadow.seed.json` — current **68-case** fresh Pari shadow set, explicitly `author_labeled_unvalidated` until independent annotation;
- `english-core-public-anchors.json` — established external benchmark/protocol registry;
- `english-core-generative-metric-contract.json` — direction/normalization contract for generative criteria;
- `validate-english-core-run.py` and `build-english-core-repro-manifest.py` — promotion/reproducibility gates.

English Core evidence is intentionally separated into lanes:

1. **public native/official** — benchmark-native protocols and metrics where reproducible;
2. **public prompted full-distribution** — common zero-shot interface on locally scoreable native validation distributions;
3. **public prompted fast** — balanced/subsampled triage only;
4. **fresh shadow** — Pari-authored fresh-surface probes;
5. **robustness diagnostics** — prompt paraphrases, counterbalanced option order, uncertainty/dependence sensitivity, paired comparison, and protocol sensitivity.

Important distinctions:

- **English Core may use a product-weighted composite for candidate selection**, but the exact weights are Pari engineering priorities rather than literature-derived psychometric constants.
- The equal-weight seven-dimension mean and every individual dimension remain visible beside the product-weighted composite.
- **The normal V1 benchmark still makes the shipping/routing decision.** A model with stronger English evidence can still lose a product route because of safety, latency, RAM or specialist performance.
- Public prompted scores are never relabeled as official/native benchmark results.
- The fresh shadow set is not independent human gold until the human-validation protocol is completed.

Research-grounding rules:

- established constructs use primary literature and official benchmark evidence where available;
- common prompted screens are labeled as screens, not official benchmark scores;
- public anchors and fresh shadow tests are reported separately because contamination and benchmark overfitting are real threats;
- close contenders require multi-prompt robustness, **counterbalanced choice-order robustness**, complete aligned paired comparison, and uncertainty analysis rather than winner-by-raw-mean;
- uncertainty reports both item bootstrap and a disclosed **phenomenon/item hierarchical-bootstrap sensitivity**; neither is presented as a universal-English confidence interval;
- general-purpose LLM judges cannot by themselves define official generative scores;
- promotion-quality public sources are pinned to immutable revisions/fingerprints where the tooling supports it;
- strong English claims require native/official anchors, reproducibility, independent shadow validation, and protocol/weight robustness.

Before using English Core, run:

```bash
./self-check-english-core.sh
```

Then follow `ENGLISH_CORE_RUN.md` rather than inventing a shorter evaluation path.

---

# 1. Two-speed product benchmark design

## V1 fast acceptance suite

Use a compact ~200-unique-source suite for frequent local model/runtime iteration.

Target mix:

| Route | Unique cases | Priority |
| --- | ---: | --- |
| word/phrase alternatives | ~60 | highest |
| sentence alternatives | ~35 | high |
| paragraph first draft | ~35 | medium |
| semantic/safety traps | ~30 | mandatory gate |
| rewrite-strength/register | ~25 | mandatory UX |
| protected/edit-containment | ~15 | mandatory control |

Cases can participate in more than one operation, but always report unique-source count separately from task-instance count.

The fast suite exists to answer practical V1 questions such as:

- Is a 2B model already good enough for interactive suggestions?
- Does 4B materially improve the options?
- Is a ternary 27B worth the latency/runtime complexity?
- Does a lower quantization visibly damage word/sentence suggestions?
- Does MTP/speculation reduce end-to-end suggestion latency?

## Release/research validation

Before changing Pari's default route, run the broader relevant suites.

### Existing Pari suites

- `../eval/corpus.json` — adversarial grammar/meaning/safety regression;
- `../quillbot/corpus.frozen.json` — 320-case broken-English/hard-tail suite;
- `../paraphrase-v2/corpus.json` — 72 standards-traced paragraph cases;
- English Studio interactive cases.

These are important regression tests but are not independent proof of human-quality English.

### Independent human/reference suites

Use by route, not indiscriminately:

- **SWORDS / Smart Word Suggestions / TSAR** — contextual lexical substitution/suggestion and ranking;
- **JFLEG** — grammar/fluency using official GLEU where applicable;
- **IteraTeR held-out revisions** — real human revision behavior;
- **EditEval** — modular editing capabilities with official task-level metrics;
- **PAWS** — adversarial semantic/order traps;
- **ASSET** — simplification/compression/split-join where relevant.

WritingBench/Arena/creative-writing leaderboards are model-screening signals only. They do not decide Pari because writing from scratch is different from editing one selected span while keeping everything else stable.

---

# 2. Route-based evaluation

Models get capability profiles rather than one global rank.

## Route A — word/phrase alternatives

This is V1's most important route.

Measure:

- top-3/top-5/top-10 useful coverage where references exist;
- grammaticality after replacement in the full sentence;
- meaning preservation;
- duplicate rate;
- materially different usable candidate count;
- replacement-length distribution (shorter / same / longer);
- time to first 3 and first 10 suggestions;
- peak memory.

A model can win this route while being mediocre at paragraph writing.

## Route B — sentence alternatives

Measure:

- meaning preservation;
- grammar/naturalness;
- register drift;
- structural diversity;
- unnecessary length inflation;
- latency to the first useful batch.

## Route C — paragraph first draft

Measure:

- factual/semantic safety;
- coherence;
- vocabulary/formality inflation;
- rewrite-strength response;
- unnecessary edit rate;
- latency.

For V1 the paragraph draft only needs to be a useful starting point. The interactive editor is the main product.

## Route D — grammar/repair specialist

Measure mainly with JFLEG and existing Pari regression tests.

A grammar specialist does not need to be a good creative writer.

## Route E — simplification/compression/expansion

Measure with ASSET, TSAR and the custom phrase-length cases.

## Route F — post-V1 personalization

Not part of V1 model selection.

When enough user interaction data exists, evaluate whether a ranker predicts the user's choices among candidates that already passed objective quality gates.

---

# 3. Interactive-edit contract

The custom suite must test operations that public benchmarks usually miss:

- word -> word;
- word -> multi-word phrase;
- phrase -> word;
- phrase -> different-length phrase;
- clause -> clause;
- sentence -> sentence;
- sentence split/join;
- local edit containment;
- protected facts next to the edit;
- low/high rewrite-strength behavior;
- register/vocabulary ceiling;
- candidate diversity.

Selected-span generation must use surrounding context for meaning/grammar, but replacing a span must not silently rewrite unrelated text.

Candidate length is free. A good replacement may turn one word into five or five words into one.

---

# 4. Rewrite-strength contract

Strength is a **surface-change budget**, not a vocabulary-sophistication slider.

| Strength | Expected behavior |
| --- | --- |
| ~15 | grammar cleanup + tiny wording changes |
| ~40 | phrase substitutions + light reshaping |
| ~60 | substantial phrase/clause changes |
| ~90 | large surface/syntax change while preserving meaning/register |

Measure edit distance/structural change against:

- semantic preservation;
- readability/vocabulary drift;
- register drift;
- safety failures.

Required behavior:

- change amount rises with strength;
- meaning remains stable;
- formality and rare-word use do **not** automatically rise with strength.

---

# 5. Human-sounding operational definition

Do not optimize for an AI-detector score.

For Pari, "human sounding" means:

- common/natural English rather than gratuitous thesaurus substitutions;
- grammar that fits the surrounding sentence;
- approximate source register preserved unless explicitly changed;
- useful contractions/informal structures kept when appropriate;
- no repetitive stock transition/filler patterns;
- no unnecessary sentence-length or abstraction inflation;
- multiple plausible ways to express the same meaning.

The user then chooses, mixes or manually edits those options.

---

# 6. Hard semantic/safety vetoes

Regardless of any reference metric, reject a candidate that causes:

- contradiction;
- negation flip;
- modality/certainty change;
- quantity/name/date/currency/link/quote corruption;
- actor/patient reversal;
- invented facts/reasons/evidence/outcomes;
- lost cause/contrast/condition relation;
- protected-span corruption;
- unrelated-text mutation outside the selected edit unit.

Use the existing Pari protected-content, grammar, semantic and NLI stack as independent gates.

---

# 7. Quantization/runtime evaluation

A compressed model is compared against the same model's strongest practical reference build.

Report quality **delta** plus runtime:

- lexical suggestion metric delta;
- sentence/paragraph quality delta;
- semantic/safety delta;
- candidate-diversity delta;
- peak unified memory;
- model size;
- cold load;
- prefill;
- decode;
- time to first useful option;
- top-10 suggestion latency;
- paragraph latency.

Generic benchmark-retention percentages do not prove that writing/editing quality survived compression.

---

# 8. MTP/speculative evaluation

MTP/speculation is a runtime lane, not a V1 quality requirement.

For compatible models compare:

- plain decode vs speculative/MTP;
- end-to-end top-10 suggestion latency;
- paragraph latency;
- extra memory;
- runtime stability;
- exact/distribution-preserving behavior where the implementation supports validation.

If the end-user latency improvement is small, omit it even if raw tokens/sec rises.

Do not train a new MTP head for V1 unless normal decode is proven to be the blocking bottleneck.

---

# 9. External reference handling / leakage

The machine-readable source policy is in `dataset-ledger.json`.

Rules:

- V1 does not train the paraphrase generator;
- public test/reference splits never enter training;
- teacher/model-generated text never becomes an independent gold benchmark;
- if post-V1 adaptation uses IteraTeR train, official dev/test remain frozen;
- NC/NC-SA datasets stay evaluation-only unless licensing is explicitly resolved;
- synthetic data is post-V1 augmentation only, never the sole quality authority;
- benchmark-native official metrics remain distinct from common prompted English Core screens;
- fresh shadow items remain evaluation-only and must rotate if repeated optimization begins to target them.

---

# 10. Reporting format

Do not publish one `Pari score`.

For every candidate produce:

1. English Core dimension profile and robustness evidence when base-LLM selection is relevant;
2. word/phrase alternatives table;
3. sentence alternatives table;
4. paragraph first-draft table;
5. hard safety table;
6. strength/register table;
7. latency/RAM table;
8. quantization delta table where applicable;
9. MTP/speculative delta table where applicable.

Then show Pareto views:

- suggestion quality vs latency;
- quality vs memory;
- candidate diversity vs latency;
- paragraph quality vs runtime cost.

The output of V1 benchmarking is a **routing decision**, not a universal model ranking.
