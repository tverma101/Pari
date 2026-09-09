# Pari remaining work — canonical execution plan

**Last reorganized:** 2026-09-07

This is the canonical tracker for unfinished Pari quality work. Research notes explain *why* a technique is interesting; benchmark READMEs explain *how* to run experiments; this document records **what remains, in what order, and what counts as done**.

## Product target

Pari's target is deliberately narrow:

> Paste a paragraph, receive one coherent and grammatical rewrite that preserves the writer's facts and intent, then manually adjust wording through contextually sane synonym/phrase suggestions.

The product is not trying to maximize edit distance or imitate thesaurus-style paraphrasing. A conservative sentence that still makes sense is preferable to a more different sentence that drifts in meaning.

Priority order for quality decisions:

1. meaning / factual preservation;
2. whole-paragraph coherence and sentence relationships;
3. grammatical, natural English;
4. useful reconstruction of broken prose;
5. requested rewrite strength;
6. lexical variety.

## Current truth — do not conflate these roles

| Role | Current state |
| --- | --- |
| Production local paragraph generator | **Qwen3-4B MLX 4-bit** via the external native model path |
| General-model benchmark control | **Qwen3.5-4B** |
| New must-test challenger | **MiniCPM5-2B** — tracked in [issue #10](https://github.com/tverma101/Pari/issues/10) |
| Deterministic fallback | `local-safe-engine`; intentionally conservative |
| Manual synonym generation | local DistilBERT + DistilRoBERTa candidate generation with contextual ranking |
| Semantic / safety referee | local protected-span, grammar, discourse, semantic and approval gates |
| Remote model routing | **research/optional only; not the shipping default** |

Generic benchmark leadership is evidence to test a model, not evidence to promote it. MiniCPM5-2B currently has unusually strong small-model results and a much smaller footprint than the 4B control, but Pari must decide on its own paragraph-rewrite corpus.

## Issue #11 benchmark checkpoint — 2026-09-08

The standards-traced v2 benchmark is implemented and the feasible local
comparison set has been exercised. The 72-case corpus, source trace, schema
validator, MLX runner, Transformers/MPS seq2seq runner, raw/postprocessed
scorer, blinded pairwise sheet, runtime receipts, and required-model status
manifest are under `benchmarks/paraphrase-v2/`.

Current automatic results are diagnostic only: Qwen3-4B scored 65/72 raw and
65/72 after Pari finalization; Qwen3 best-of-four scored 69/72 as a raw
research selection and 60/72 after the production-safe selector; Qwen3.5-4B
scored 64/72 raw and 65/72 finalized; MiniCPM5-2B scored 21/72 raw and 24/72
finalized; and CoEdIT-large scored 51/72 with 14 hard-safety failures. No
candidate meets the promotion gates, so Qwen3 remains the incumbent.

CoEdIT-XL loaded successfully for an MPS smoke test, but its 11.4 GB
single-weight full-corpus run was **user-stopped** after 55/72 raw rows when
memory pressure became unacceptable. Its partial JSONL is retained only for
recoverable inspection/resume and is not scored. ADAL was rejected as an
invalid NaN-containing checkpoint; DIPPER had no downloadable weights in the
available snapshot; and Ling requires an unavailable `rapid-mlx` runtime.

Issue #11 remains open for its formal human preference ratings, target-app
installed-runtime evidence for the benchmark decision, and any future
runtime-enabled candidate. The automatic report must not be used to claim
QuillBot superiority or to promote a model.

## Recently completed quality work

- ConCat-style synonym context and whole-sentence semantic reranking were added in `6602d84`.
- Production candidate selection now enforces the benchmark-aligned semantic floor for ordinary rewrites, with a looser reconstruction floor only for structurally broken input (`e506474`).
- Contextual-synonym research, licensing cautions and implementation principles are documented in `research/contextual-synonyms.md` (`e56720d`).
- The model shootout already supports direct MLX and OpenAI-compatible local runtimes and preserves raw outputs for replayable scoring.
- Native and deterministic finalization now repair the high-confidence
  note-style “is pending … status” noun stack without adding a cause, actor,
  or outcome; the native fixture and installed bundle cover this path.
- Rewrite amount now uses a continuous 0–100 slider with debounced
  regeneration for unedited drafts, while preserving manual output edits; the
  installed UI and screenshot-paragraph native flow cover the interaction.
- High/Deep Rewrite amounts now request paragraph-level sentence restructuring
  from the native worker. The offline fallback also moves only bounded,
  relationship-preserving fronted clauses or context phrases so high amount has
  a structural effect without weakening the meaning gate.

These items are implemented but still require target-Mac validation before they should be treated as fully proven.

## 2026-09-07 readiness checkpoint

Pari is **not yet ready to claim a broadly reliable, QuillBot-class paraphraser**. The current local path is a strong safety-first prototype: Qwen3-4B scored 61/64 (95%) raw and 64/64 after Pari finalization on the original automatic 64-case corpus, and the native worker, grammar gates, packaging, and installed native/missing-model/custom-mode checks pass. The automatic judge is not a substitute for human quality review.

This checkpoint added source-aware repairs for standalone causal, waiting, and note fragments, plus stricter anti-invention instructions and regression fixtures. A follow-up maintenance pass also normalizes a dense “pending … status” noun stack in both native and fallback finalization. Qwen3 remains the production incumbent; the refreshed raw-model run did not justify a promotion or a FreeLLMAPI default. Before calling the product ready, complete P0.1/P0.2/P0.4: save a blind human spot-check on real paragraphs, compare against the same default/conservative QuillBot inputs, and verify that Pari wins or ties on sense, meaning preservation, and grammar across a larger held-out set.

The automatic challenger portion of P0.1 has now been exercised: temporary
MiniCPM5-2B-MLX scored 43/64 raw and 51/64 after Pari finalization, while the
retained Qwen3 path remains 64/64 after finalization. MiniCPM is therefore
rejected for promotion on this corpus. P0.1 remains open for the required
target-Mac memory/latency record and blind quality spot-check, and P0.2/P0.4
still require human in-app synonym and QuillBot comparisons.

The expanded 2026-09-07 frozen holdout contains 300 cases and is a harder
automatic check than the original 64-case set. Qwen3 scored 222/300 raw and
228/300 after the current Pari finalizer. A production-schedule best-of-four
replay scored 236/300 when selected only against the normalized benchmark
judge, but fell to 227/300 when the exact protected-content gate was required;
that result is not a production promotion. The remaining hard failures are
mostly strict negation/NLI rejections on typo-heavy repairs and identity or
cautious outputs on vague/ambiguity cases. The product should keep failing
closed on those safety boundaries until a better generator or a reviewed rule
can improve them without weakening protection.

---

# P0 — prove the core local product

P0 is the shortest route to a trustworthy "better than default QuillBot for pasted paragraphs" product. Do these before adding more architecture.

## P0.1 — MiniCPM5-2B vs Qwen controls

**Tracking:** [#10 — Benchmark MiniCPM5-2B vs Qwen3.5-4B](https://github.com/tverma101/Pari/issues/10)

Run one frozen corpus and one prompt contract against:

- MiniCPM5-2B;
- Qwen3.5-4B benchmark control;
- Qwen3-4B production incumbent;
- deterministic/original fallback where useful as a safety reference.

Record:

- grammar/syntax;
- natural collocations;
- paragraph coherence;
- broken-prose reconstruction;
- semantic preservation / unsupported inventions;
- protected spans, negation, modality, quantity and actor-role safety;
- overcorrection;
- production-gate acceptance rate;
- first-token and end-to-end latency;
- tokens/sec where available;
- peak memory on the target 16-GB Apple-Silicon Mac;
- model disk footprint;
- installed-app/runtime reliability.

**Done when:** the raw outputs, automatic scores and a blind human spot-check are saved, and a model decision is written down. Do not change the shipping model in the benchmark commit itself.

**Promotion rule:** the challenger must introduce zero new hard-safety regressions and either improve rewrite quality or deliver a meaningful memory/latency reduction at comparable quality. If generic benchmarks improve but Pari paragraph quality declines, keep Qwen.

## P0.2 — validate contextual synonym quality on the actual app

The synonym architecture is now in place; validation remains.

Test at least these classes:

- common verbs/adjectives where many dictionary synonyms exist;
- tense and number-sensitive replacements;
- words inside strong collocations;
- academic/student prose;
- informal prose;
- words near negation or protected spans;
- phrase-like expressions where replacing only one token would sound wrong.

For each clicked target verify:

- 6–10 suggestions appear when enough safe candidates exist;
- the original remains available;
- the top suggestions fit the **whole sentence**, not merely the dictionary sense;
- wrong POS/inflection, antonyms, garbage subwords and meaning-changing choices are demoted or absent;
- manual replacement, sentence revert and undo still behave correctly.

**Done when:** a human spot-check shows the top 6–10 choices are routinely usable within the broader manual palette, and installed-app QA has no interaction regressions.

## P0.3 — rerun the complete safety/quality regression after the new semantic floor

Run the existing suites before further model work:

```bash
npm ci
npm run models:check
npm run qa:approval
npm run qa:grammar:harper
npm run qa:grammar:ewt
npm run qa:native:prompt
npm run qa:native:model
npm run benchmark:quality
```

Any new hard safety failure blocks model promotion.

## P0.4 — target-Mac installed-app validation

Build and exercise the real packaged application:

```bash
npm run build:desktop
npm run qa:installed
npm run qa:installed:missing-model
npm run qa:installed:connected
```

Then paste a representative set of real messy paragraphs into the visible app. The important human question is not "did it change enough?" but **"does the result make more sense while still saying the same thing?"**

For a QuillBot comparison, use the same source paragraphs and default/conservative QuillBot behavior. Pari should show a clear majority of wins/ties on coherence and meaning preservation before claiming superiority; isolated cherry-picked wins do not count.

---

# P1 — strengthen the referee and widen the candidate pool

Only begin these once P0 identifies the best local general generator and establishes a stable baseline.

## P1.1 — wire the winning local model cleanly

If #10 produces a new winner:

- update the external native model installer/discovery path;
- keep migration/backward compatibility where practical;
- update model manifests and checksums;
- update the installed-app connected test;
- update README wording so production backend and benchmark control remain distinct concepts;
- rerun every P0 regression.

One model promotion per commit/PR. Do not combine it with unrelated ranking changes.

## P1.2 — grammar-specialist shootout

Test compact grammar/editing models as **candidate generators or repairers**, not trusted authorities:

- GECToR;
- DeCoGLM;
- a license-compatible BART-family GEC checkpoint;
- CoEdIT-large as a research/reference comparison only unless licensing permits shipping.

Compare specialist-only, general-model-only and specialist+general cascades. Reward precision and meaning preservation, not edit count.

**Keep the ensemble only if it beats the single-model path enough to justify extra latency/memory.**

## P1.3 — stronger entailment / contradiction gate

MiniLM cosine is useful but can miss negation, role and causal reversals. Evaluate a compact local NLI/entailment model as an additional veto signal.

Requirements:

- local/offline;
- small enough for the 16-GB target;
- no unacceptable false rejection of legitimate paraphrases;
- measurable improvement on adversarial negation/role/quantity fixtures.

Do not add the model merely because NLI is theoretically attractive; it must reduce real Pari failures.

## P1.4 — CI quality floors

Add a CI job that runs the replayable evaluation corpus against committed fixture outputs and fails on hard safety-floor regressions. Hardware-specific MLX speed/memory tests remain local and should not make ordinary CI nondeterministic.

---

# P1 optional — online multi-provider candidate routing

Remote routing is a **quality-ceiling experiment**, not a prerequisite for the local product.

Potential sources should be investigated provider-by-provider rather than treating OpenRouter as the only API source. Direct provider keys can provide independent quotas and model catalogs.

Design boundary:

```text
local candidate -----------\
remote provider candidate --+--> local Pari safety/meaning/grammar referee --> winner
remote provider candidate --/
```

Rules:

- local/offline mode must remain fully functional;
- remote mode must be explicit opt-in;
- clearly disclose that pasted text leaves the device and identify the selected provider;
- never silently route personal text to a free endpoint;
- keep provider adapters isolated behind an OpenAI-compatible/general transport boundary where possible;
- handle quota exhaustion, 429s, outages and model removal without breaking local generation;
- do not evade provider quotas through duplicate accounts;
- do not let a remote candidate bypass local safety gates;
- benchmark quality per provider/model rather than assuming a larger cloud model is better at conservative rewriting.

This track becomes production-worthy only if it gives a consistent, meaningful quality win over the best local model and the privacy/availability UX is acceptable.

---

# P2 — personalization and optimization after correctness

## P2.1 — approval-derived style improvements

Continue using bounded approved examples and explicit preference memory. Do not fine-tune on unapproved drafts.

## P2.2 — LoRA/distillation only with enough evidence

Do not train a Pari-specific checkpoint until there is a sufficiently large, clean approval set (the existing research threshold is roughly 200+ useful approved pairs) and the desired behavior is stable enough to justify training.

A future distillation target is reasonable only if the multi-model/cascade path proves a quality advantage worth compressing.

## P2.3 — polish rather than architecture churn

After quality is stable, optimize:

- startup/model discovery;
- memory pressure;
- latency;
- synonym-popup responsiveness;
- model download/install UX;
- clearer diagnostics when the native model is missing or rejected.

---

# Work split: what can be done remotely vs. what requires the target Mac

## Can be done from GitHub / remote tooling

- research and model/license triage;
- benchmark harness changes;
- prompt/ranker/safety logic;
- provider adapters;
- fixture expansion;
- documentation;
- replaying already-generated candidate files;
- CI/static tests.

## Requires the target M4/16-GB Mac

- downloading/running Apple-Silicon model conversions;
- proving `mlx-lm`/alternate runtime compatibility;
- first-token and total-generation latency;
- real peak unified-memory measurements;
- packaged `.app` + Swift/WKWebView + native-worker integration;
- visible synonym/editor interaction checks;
- final human judgment on real paragraphs.

The desired local loop is:

```text
GitHub change -> pull/build on target Mac -> run scripted QA -> try real paragraphs
             -> save logs/outputs -> diagnose/fix in repo -> rerun
```

The Mac-side role should mostly be execution and observation, not manual debugging.

---

# Definition of "ready"

Pari is ready for the narrow v1 quality goal when all of the following are true:

- one local generator has won the frozen product-specific shootout;
- hard protected-content / meaning-safety fixtures have no regressions;
- ordinary and badly broken paragraphs produce coherent, grammatical output more reliably than the current baseline;
- the semantic/grammar gates reject unsafe fluent nonsense rather than merely ranking it lower;
- contextual synonym suggestions are routinely useful in sentence context;
- installed-app connected, disconnected and missing-model modes pass on the target Mac;
- a blind real-paragraph comparison shows Pari clearly competitive with or better than default QuillBot on **sense, meaning preservation and grammar**, not merely lexical difference;
- model choice, runtime requirements and privacy boundaries are accurately documented.

## Supporting documents

- `research/quality-roadmap.md` — quality-system principles and specialist-model research.
- `research/contextual-synonyms.md` — contextual lexical-substitution research and licensing notes.
- `benchmarks/llm-shootout/README.md` — model experiment runners and promotion rules.
- `docs/engine-upgrade-plan.md` — historical SOTA-push plan; retained for context but superseded by this file for execution order.
