# Pari English Core — research-grounding policy

This file is a standing rule for English Core benchmark changes.

## Core requirement

No new benchmark dimension, metric, dataset, judge, scoring rule, or headline claim should be treated as part of English Core merely because it sounds reasonable or improves a preferred model's score.

Every substantive change must be traceable to one of two categories:

1. **Research-backed construct or evaluation method** — supported by primary literature, an established benchmark paper, or a well-documented official benchmark protocol.
2. **Pari-specific engineering choice** — motivated by the product goal and labeled explicitly as such rather than presented as a scientific fact.

## Evidence standard

Prefer evidence in this order:

1. peer-reviewed benchmark/task papers and official benchmark documentation;
2. later replication, robustness, contamination, and validity studies;
3. human-reference datasets with clear annotation procedures;
4. strong preprints when peer-reviewed work is unavailable;
5. model cards, blog posts, leaderboards, or community reports only as secondary operational evidence.

A blog, leaderboard, vendor claim, or one model's self-evaluation is never sufficient by itself to establish a benchmark construct or final quality claim.

## Required record for every benchmark component

For each dimension or external anchor, document:

- construct being measured;
- why that construct is relevant to Pari;
- primary research source(s);
- official task/scoring protocol where available;
- whether Pari modifies that protocol;
- known threats to validity;
- contamination risk;
- license/provenance status;
- whether the component is primary evidence or secondary diagnostic evidence.

## Scoring discipline

- Use official metrics when the benchmark has an accepted official metric.
- Do not silently replace an official protocol with a convenient prompted approximation and call the result an official benchmark score.
- Common prompted screens may be used for model triage, but must be labeled as screens.
- Preserve per-dimension results; do not let one aggregate conceal capability tradeoffs.
- Product weights must be identified as Pari priorities, not literature-derived constants, unless a future study actually validates them.
- Run weight-sensitivity checks before making a strong overall model claim.

## Model-judge discipline

Prefer gold labels, human references, deterministic checks, and independently validated specialist judges. A general-purpose LLM judge is secondary evidence unless human agreement and judge validity have been established for the exact evaluation task.

A candidate model must never grade its own official output.

## Contamination and benchmark artifacts

Public benchmark results must be reported separately from fresh or rotated shadow tests. Shadow items should test the same research-backed phenomena using new surface forms.

Forced-choice evaluations must control answer-position and label-frequency artifacts. If a benchmark's official protocol differs from the common Pari screen, both should be reported when making research-level claims.

## Claim language

Use claim strength proportional to evidence:

- `won the Pari English Core product-weighted composite` is acceptable when that is what was measured;
- `showed stronger lexical-context performance on SWORDS/WiC and the fresh shadow set` is preferable when evidence is dimension-specific;
- `has objectively the best English` is not justified unless the evidence is broad, robust to weighting/protocol choices, and independently replicated.

When rankings flip under reasonable scoring choices, report a capability tradeoff rather than forcing a universal winner.

## Change checklist

Before merging a benchmark change, verify:

- [ ] primary source exists for the construct or the change is explicitly labeled Pari-specific;
- [ ] source supports the exact claim being made;
- [ ] official metric/protocol has been checked;
- [ ] leakage/contamination risk is documented;
- [ ] answer-position/class-balance artifacts are controlled where relevant;
- [ ] per-dimension results remain visible;
- [ ] judge provenance is recorded;
- [ ] weights/sample budgets are not misrepresented as research constants;
- [ ] limitations are written down before model results are inspected whenever practical;
- [ ] no benchmark was added solely because it favors a preferred model.

The detailed evidence map remains in `ENGLISH_CORE_RESEARCH_BASIS.md`.
