# Issue #56 - weight-sensitivity and paired-uncertainty lane

This lane answers one part of issue #56: whether the ordering of close
contenders on the Pari English Core composite is stable under the Pari-specific
dimension weights, and what the paired uncertainty on a shared, complete item
set actually supports.

The prompt-robustness and answer-order lanes are owned elsewhere
(`build/score-english-core-prompt-robustness.mjs` and
`build/score-english-core-choice-order-robustness.mjs`). This document covers
only the weight/paired lane so the two stay separately auditable.

## Files

- `kaggle-weight-sensitivity-grid.json` - the frozen, hashable weight grid.
- `kaggle_weight_sensitivity.py` - the analysis (grid validation, provenance
  fail-closed checks, per-vector ranking, paired dimension bootstrap,
  leave-one-dimension check).
- `test_kaggle_weight_sensitivity.py` - CPU-only tests for the above.

## The frozen grid

The grid is versioned and hashed. Its SHA-256 is recorded in every report, so
editing the grid after results exist invalidates any plan that pinned the old
hash. No vector may be added, dropped, or reweighted once contender results are
visible; the analysis only ever evaluates the vectors in the file.

It contains, in this order:

1. `product` - the existing Pari product weights
   (`lexical_context 25 / collocation_naturalness 20 / grammar_syntax 15 /
   paraphrase_semantics 15 / fluency_register 10 / generative_expression 10 /
   discourse 5`), which are a product prior, not a literature constant;
2. `equal_weight` - the equal-weight dimension mean (the secondary composite);
3. three predeclared alternatives (`paraphrase_first`, `fluency_first`,
   `structure_first`) that each embody one plausible reading of the product
   job;
4. seven `leave_out_<dimension>` variants, derived programmatically from the
   product vector by zeroing one dimension and renormalizing the rest to 100.

Every vector must sum to exactly 100 or the grid is rejected. The leave-one-out
variants are derived, not hand-edited, so they cannot drift from the base
weighting and cannot be tuned per model.

Bootstrap seed and the default iteration count are part of the grid
(`0x70a1b00b`, 10000 iterations), matching the existing paired-comparison
convention so this lane does not introduce a second randomness convention.

## What the analysis does

For a frozen contender set it:

- validates the grid against `english-core-config.json` so the dimensions cannot
  silently drift from the product config;
- requires every contender's score report to carry the same
  `benchmarkInputs` fingerprint (`configSha256`, `shadowSeedSha256`,
  `shadowTaskSha256`, `shadowManifestSha256`,
  `generativeMetricContractSha256`) and the canonical shadow task-file hash;
- requires every dimension to be completely scored, and honors the frozen
  expected per-dimension case counts when the contender set declares them;
- excludes a candidate explicitly marked `runtimeQualified: false`, so a
  runtime-unqualified candidate never enters linguistic paired statistics;
- ranks every candidate under every frozen vector and reports
  leader/order stability across the whole grid;
- reports the product-vs-equal-weight leader and whether they differ, plus the
  paired conclusion under each;
- reports a leave-one-dimension driver: the largest single-dimension
  contribution to the lead and which leave-one-out vectors flip its sign.

It fails closed (`status: "withheld"`, no rankings) when the contender set
cannot supply at least two provenance-clean, fully-scored score reports on a
shared benchmark identity, or when a declared hash/case-count does not match.
A withheld report is a blocker, not a negative result.

## How to read the output

- `rankingStability.leaderStableAcrossGrid: false` means the ordering is
  weight-dependent; report it as a trade-off, not a winner.
- A paired interval containing zero is `inconclusive`, never a forced winner.
- `leaveOneDimensionDriver.leaveOneOutSignFlips` non-empty means one dimension
  carries (or reverses) the entire product-weighted lead.
- `excluded[].reasons` names every contender that was withheld and why.

## Scope of the paired bootstrap here

The paired bootstrap in this lane resamples the seven aligned *dimensions*
(collapsing duplicates and renormalizing the drawn weights). A score report
exposes per-dimension aggregates, not per-item scores, so this is a coarse
weight-grid sensitivity diagnostic. It is not a replacement for the per-item
paired bootstrap in `compare-english-core-models.mjs`, which remains the
authoritative item-level paired inference on identical complete coverage. The
issue's "larger raw percentage is not decisive without paired support" rule is
enforced by the zero-crossing check, and the item-level lane enforces the
identical-complete-coverage requirement.

## Verified behavior (CPU tests)

`python3 test_kaggle_weight_sensitivity.py` covers, with synthetic score-report
doubles only (no model, no GPU, no private data):

- grid validity against the config, and rejection of vectors that do not sum to
  100 or that omit a dimension;
- leave-one-out derivation from the product vector;
- a clean pair producing a `computed` report;
- provenance mismatch, missing score file, incomplete dimension, expected-case
  mismatch, runtime-unqualified candidate, single contender, duplicate ids, and
  undersized bootstrap all failing closed;
- a ranking flip under equal weights being reported instead of a winner;
- a leave-one-out sign flip when one dimension carries the lead;
- tied competitors staying `inconclusive`;
- the bootstrap being deterministic for a frozen seed.

The synthetic fixtures prove the analysis logic. They are not evidence about
any real model.

## Limits and blockers for the full issue

- The lane analyzes **existing** score reports. It does not generate prompt or
  order variants and does not spend Kaggle T4 time; only genuinely new
  generations belong in the prompt/order lanes.
- It needs a **frozen contender set plus real comparable Q4 score reports**
  (#34) and phase/task identity (#33/#39/#40/#48) to produce anything other
  than a `withheld` blocker. Those are upstream dependencies of #56 and are not
  satisfied by this file alone.
- It never opens raw model outputs or the private gold key.
