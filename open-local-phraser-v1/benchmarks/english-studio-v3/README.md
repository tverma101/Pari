# Pari English Studio Benchmark v3

This directory is the **evaluation layer** for Pari's rewriting studio. The model/training/compute decision tree lives in [`PROJECT_PLAN.md`](./PROJECT_PLAN.md).

The benchmark's job is simple:

> determine whether a model or pipeline produces correct, natural, controllable English edits without requiring the project owner to be an expert English judge.

No single score decides the winner.

---

# 1. Benchmark layers

## Layer A — Pari regression and safety

These existing suites remain unchanged and first-class:

| Suite | Role |
| --- | --- |
| `../eval/corpus.json` | adversarial grammar/meaning/safety regression |
| `../quillbot/corpus.frozen.json` | 320-case broken-English / hard-tail comparison corpus |
| `../paraphrase-v2/corpus.json` | 72 standards-traced paragraph editing cases |

They test product-specific failure modes and prevent old fixes from regressing.

They are **not** independent public gold standards and must never be described as proof of human-quality English by themselves.

## Layer B — independent human-reference suites

These are the main objective quality anchors.

### JFLEG — fluency / grammatical correction

Source: https://github.com/keisks/jfleg

- 754 dev + 747 test sources;
- four human corrections per source;
- official GLEU evaluator;
- CC BY-NC-SA 4.0: benchmark/evaluation use unless licensing permits more.

Report:

- GLEU dev/test;
- protected-content failures if any;
- semantic/negation/modality violations;
- unchanged-rate on already-acceptable material where measurable.

### ASSET — simplification / multi-operation rewriting

Source: https://github.com/facebookresearch/asset

- 2,000 validation + 359 test source sentences;
- ten human simplifications each;
- includes lexical paraphrasing, compression, reordering and splitting;
- CC BY-NC 4.0: evaluation/reference use.

Report:

- SARI;
- add/delete/keep sub-scores where available;
- meaning/safety vetoes;
- sentence-split/join behavior.

Do not interpret SARI alone as complete human quality; the ASSET paper explicitly motivates richer evaluation for multi-operation rewriting.

### Microsoft Smart Word Suggestions — contextual word/phrase alternatives

Source: https://github.com/microsoft/SmartWordSuggestions

- human test set of 1,000 learner-written sentences;
- over 16,000 substitution suggestions annotated by 10 native speakers;
- MIT repository;
- large distantly-supervised training set is **not** part of the gold test.

This is one of the closest public benchmarks to Pari's click-a-word/click-a-phrase UX.

Use the repository's official evaluation framework and preserve its human test split.

### TSAR lexical simplification — ranked alternatives

Source: https://aclanthology.org/2022.tsar-1.31/

Use the English test set and official ranking metrics:

- MAP@3 / 5 / 10;
- Potential@3 / 5 / 10;
- Accuracy@k@top1;
- optional precision/recall@k diagnostics.

The shared-task evaluation data is CC BY-NC-SA 4.0; keep it evaluation-only.

### PAWS — paraphrase / word-order meaning traps

Source: https://github.com/google-research-datasets/paws

Use the human-labeled final splits as an independent adversarial meaning test.

The purpose is not to train Pari to classify PAWS. It is to make sure Pari's semantic gate catches cases where almost the same words express a different relationship because subject/object or word order changed.

### IteraTeR held-out revisions

Source: https://github.com/vipulraheja/iterater

If IteraTeR train is used for adaptation, keep official dev/test completely frozen.

Because revision is one-to-many, report several diagnostics rather than treating one target string as the only correct answer:

- semantic preservation;
- reference overlap/edit similarity;
- grammar/fluency;
- edit amount;
- safety failures.

## Optional GEC suite

Add BEA/ERRANT or CoNLL-style M2/ERRANT evaluation only after data-access and license handling are documented. Do not block the first v3 benchmark on this.

---

# 2. Pari interactive studio suite

Public benchmarks do not cover the entire product interaction model, so `interactive.seed.json` remains a custom product suite.

It covers:

- word -> word;
- word -> multi-word phrase;
- phrase -> word;
- phrase -> phrase;
- clause rewrite;
- full-sentence rewrite;
- split/join;
- local edit containment;
- protected content next to the selected span;
- register/vocabulary ceiling;
- candidate diversity;
- rewrite-strength calibration.

## Expansion policy

Do not create hundreds of near-duplicate templates.

Expand from:

1. hand-authored adversarial cases;
2. localized human edits automatically extracted from IteraTeR revisions;
3. failure cases discovered during real Pari use, after removing personal content.

Track **unique source examples** separately from **task instances**.

The composite builder may apply several distinct operations to one source, but those operations are correlated and must not be counted as independent prose examples.

---

# 3. Rewrite-strength benchmark

Strength controls **surface-change budget**, not intelligence or formality.

| Strength | Expected behavior |
| --- | --- |
| 15 | grammar cleanup + tiny wording changes |
| 40 | phrase substitution + light reshaping |
| 60 | substantial phrase/clause rewrite |
| 90 | large surface/syntax change while preserving meaning/register |

For each source measure:

- token/character edit distance;
- syntactic/structural change proxy;
- semantic preservation;
- vocabulary-frequency/readability drift;
- register drift;
- safety failures.

Pass condition:

- change amount should rise with strength;
- meaning/safety should remain stable;
- vocabulary sophistication must not automatically rise with strength.

Human revision data can also be binned by observed edit distance to create non-synthetic examples of different rewrite amounts.

---

# 4. Alternative-set evaluation

Pari is unusual because it intentionally wants a deep candidate toolbox rather than one machine-selected rewrite.

For each selected span report:

- top-1 validity;
- top-3 / top-5 / top-10 gold coverage where the public suite supports it;
- top-10 precision;
- top-40 safety/grammar pass rate;
- duplicate / near-duplicate rate;
- semantic diversity among surviving candidates;
- local-edit containment failures;
- time to first 5 / 10 / 40 usable candidates.

For lexical simplification, use TSAR-style MAP/Potential/Accuracy metrics rather than inventing a new ranking metric.

For SWS, use its official evaluator.

For custom phrase/clause cases without exhaustive gold alternatives, objective gates determine validity and the suite records diversity/containment rather than pretending there is one exact correct string.

---

# 5. Safety vetoes

Regardless of reference score, a candidate is ineligible when it causes a hard semantic failure:

- contradiction;
- negation flip;
- modality/certainty change;
- quantity/name/date/currency/link/quote corruption;
- actor/patient reversal;
- invented facts/reasons/outcomes/evidence;
- lost cause/contrast/condition relation;
- protected-span corruption.

Use the existing Pari protected-content, grammar, semantic and NLI stack as independent vetoes.

A high reference metric cannot erase a hard safety failure.

---

# 6. Compression benchmark

Every candidate model is evaluated first at its best practical reference precision/format, then at deployable quantizations.

For each quantization report **delta from the same model's reference**, not only raw score:

- JFLEG GLEU delta;
- ASSET SARI delta;
- SWS/TSAR ranking delta;
- PAWS/semantic-safety delta;
- internal hard-failure delta;
- candidate-diversity delta;
- peak memory;
- first-result latency;
- paragraph latency;
- candidates/sec.

The purpose is to identify the smallest representation that retains the editing ability Pari cares about.

Generic benchmark-retention claims are not substitutes for this test.

---

# 7. Personalization benchmark

Personalization runs **after objective filtering**.

The user is never asked to decide whether bad grammar is acceptable. The model first produces a set of objectively safe/grammatical alternatives; personalization only learns which valid expression the user prefers.

Hold out a portion of real interaction events and report:

- chosen-vs-rejected pair accuracy;
- MRR/NDCG of the actually selected candidate;
- revert rate;
- change in objective safety/English scores (must not materially regress).

Do not train and test on the same interaction event.

---

# 8. Leakage rules

Maintain a machine-readable dataset ledger with exact revisions/hashes.

For every dataset classify it as one of:

- `shipping_train`
- `research_train`
- `eval_only`
- `blocked_pending_review`

Rules:

- no external test/reference split enters training;
- no teacher-generated text becomes an external benchmark reference;
- if CoEdIT is used for training, its own validation material is not an independent promotion metric;
- IteraTeR official dev/test remain frozen when IteraTeR train is used;
- NC/NC-SA datasets remain eval-only unless licensing is explicitly resolved.

---

# 9. Reporting

Never collapse v3 to one leaderboard number.

Every model report must contain:

1. **hard safety table**;
2. **grammar/fluency table** (JFLEG + optional ERRANT/M2);
3. **simplification/rewrite table** (ASSET);
4. **word/phrase suggestion table** (SWS + TSAR);
5. **meaning-adversarial table** (PAWS + Pari invariants);
6. **paragraph/internal table** (existing Pari suites);
7. **interactive candidate-set table**;
8. **rewrite-strength calibration table**;
9. **runtime/RAM table**;
10. **personalization table** when enough interaction data exists.

Then produce Pareto views rather than one winner score:

- quality vs memory;
- quality vs latency;
- candidate quality vs candidate depth;
- reference model vs each quantization;
- cold-start vs personalized ranking.

---

# 10. Relationship to the old benchmark work

Nothing here deletes the old work.

The old suites remain valuable regression tests. V3 adds independent gold/reference suites and a product-specific interactive layer so the project no longer mistakes an internal automatic score for proof of English quality.

The training/model strategy is documented separately in [`PROJECT_PLAN.md`](./PROJECT_PLAN.md).
