# Pari English Studio v3 benchmark

This directory is Pari's evaluation layer.

The product/model decision tree lives in [`PROJECT_PLAN.md`](./PROJECT_PLAN.md). The concrete V1 model/runtime experiment lives in [`V1_SHOOTOUT.md`](./V1_SHOOTOUT.md). Model-to-benchmark routing lives in [`BENCHMARK_MODEL_MAP.md`](./BENCHMARK_MODEL_MAP.md). Dataset provenance lives in [`dataset-ledger.json`](./dataset-ledger.json).

The benchmark has one job:

> measure whether a model or pipeline is useful for a human-controlled rewriting studio without requiring the project owner to be an expert English judge.

No single benchmark and no single scalar score decides the winner.

---

# 1. Two-speed benchmark design

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

- **Smart Word Suggestions** — contextual word/phrase suggestion;
- **TSAR** — lexical alternative ranking;
- **JFLEG** — grammar/fluency;
- **IteraTeR held-out revisions** — real human revision behavior;
- **EditEval** — modular editing capabilities;
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

Do not train a new MTP head for V1 unless normal decoding is proven to be the blocking bottleneck.

---

# 9. External reference handling / leakage

The machine-readable source policy is in `dataset-ledger.json`.

Rules:

- V1 does not train the paraphrase generator;
- public test/reference splits never enter training;
- teacher/model-generated text never becomes an independent gold benchmark;
- if post-V1 adaptation uses IteraTeR train, official dev/test remain frozen;
- NC/NC-SA datasets stay evaluation-only unless licensing is explicitly resolved;
- synthetic data is post-V1 augmentation only, never the sole quality authority.

---

# 10. Reporting format

Do not publish one `Pari score`.

For every candidate produce:

1. word/phrase alternatives table;
2. sentence alternatives table;
3. paragraph first-draft table;
4. hard safety table;
5. strength/register table;
6. latency/RAM table;
7. quantization delta table where applicable;
8. MTP/speculative delta table where applicable.

Then show Pareto views:

- suggestion quality vs latency;
- quality vs memory;
- candidate diversity vs latency;
- paragraph quality vs runtime cost.

The output of V1 benchmarking is a **routing decision**, not a universal model ranking.
