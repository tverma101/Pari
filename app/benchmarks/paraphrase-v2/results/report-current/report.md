# Pari Paraphrase Quality Benchmark v2 report

Generated: 2026-09-09T01:50:39.154Z
Corpus: 72 cases, version 2

## Decision boundary

Human ratings supplied: **no**. The automatic leader below is diagnostic only; issue #11's human preference gate remains open.
Automatic diagnostic leader: **qwen3-4b-incumbent-bestof4-raw**.
Shippable candidate with current installed evidence and zero hard-safety failures: **none**.

## Automatic diagnostics

| Engine | Role | Full gate | Meaning-safe | English-quality | Auto index | Hard safety failures | Median s | Peak GiB | Pareto |
|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| original-reference | no-rewrite-safety-reference | 0.0% | 100.0% | 0.0% | 39.740 | 0 | 0.000 | 0.042 | yes |
| local-safe-engine | deterministic-safety-reference | 30.6% | 100.0% | 30.6% | 56.440 | 0 | 0.003 | 0.168 | yes |
| qwen3-4b-incumbent-bestof4-raw | production-incumbent | 95.8% | 95.8% | 100.0% | 92.590 | 3 | 5.675 | 2.258 | yes |
| qwen3-4b-incumbent | production-incumbent | 90.3% | 94.4% | 95.8% | 89.170 | 4 | 1.450 | 2.258 | yes |
| qwen35-4b-control | benchmark-control | 90.3% | 90.3% | 100.0% | 88.820 | 7 | 1.685 | 2.520 | no |
| coedit-large-research | research-reference | 70.8% | 80.6% | 87.5% | 76.900 | 14 | 2.051 | 2.962 | no |
| minicpm5-2b | challenger | 33.3% | 98.6% | 34.7% | 58.130 | 1 | 0.865 | 1.536 | yes |

The automatic index combines full-gate pass rate, meaning-safe rate, English-quality rate, and the bundled learned judge's English/fluency signals. It is a reproducible diagnostic, not a human-quality score and not a promotion decision.

## Runtime receipts

| Engine | Model/revision | Runtime | License | Installed evidence |
|---|---|---|---|:---:|
| original-reference | — | none | source text | no |
| local-safe-engine | — | Pari TypeScript local-safe engine | project code; see repository license | no |
| qwen3-4b-incumbent-bestof4-raw | Qwen/Qwen3-4B-MLX-4bit @ 52a5ab34fa604bc8af6d3ce0cac0cab10b7eb495 | mlx-lm | apache-2.0 | no |
| qwen3-4b-incumbent | Qwen/Qwen3-4B-MLX-4bit @ 52a5ab34fa604bc8af6d3ce0cac0cab10b7eb495 | mlx-lm | apache-2.0 | no |
| qwen35-4b-control | mlx-community/Qwen3.5-4B-MLX-4bit @ 32f3e8ecf65426fc3306969496342d504bfa13f3 | mlx-lm | apache-2.0 | no |
| coedit-large-research | grammarly/coedit-large @ 5637bcdf9d8d4419f97c8cfea36f7d35c79232b6 | transformers 5.14.1 / torch 2.12.1 / mps | cc-by-nc-4.0 | no |
| minicpm5-2b | openbmb/MiniCPM5-2B-MLX @ 014e7591ff4b1b6330cda7f45803b27f46288261 | mlx-lm | apache-2.0 | no |

## Human handoff

Use [pairwise-blinded.csv](pairwise-blinded.csv) for blinded A/B judgments and keep [pairwise-key.json](pairwise-key.json) separate until scoring is complete. [human-scores-template.csv](human-scores-template.csv) is the per-engine 1–5 rubric template.

## Required comparison-set status

This status table prevents incomplete or unavailable required candidates from disappearing from the decision record.

| Model | Status | v2 coverage | Old suite | Note |
|---|---|---|---|---|
| qwen3-4b-incumbent | benchmarked | 65/72 raw; 65/72 Pari-finalized | 59/64 | Current production incumbent; no promotion change. |
| qwen3-4b-incumbent-bestof4 | benchmarked | 69/72 raw research selection; 60/72 production-safe selection | — | Best-of-four is an automatic experiment, not the installed production ranker. |
| qwen35-4b-control | benchmarked | 64/72 raw; 65/72 Pari-finalized | 61/64 | Benchmark control only; not promoted. |
| minicpm5-2b | benchmarked | 21/72 raw; 24/72 Pari-finalized | 43/64 | Rejected for promotion on this corpus because quality and gate acceptance declined. |
| coedit-large-research | benchmarked | 51/72 raw and Pari-finalized | — | Research-only reference; official checkpoint is CC-BY-NC-4.0. |
| coedit-xl-research | user-stopped | 55/72 raw rows written; not scored | — | 11.4 GB single-safetensor checkpoint loaded and passed one-paragraph MPS smoke; user stopped the full run before completion. |
| adal-paraphraser-large | invalid-checkpoint | not run | — | Downloaded safetensor contains non-finite NaN values in encoder/decoder tensors; generation is not a valid comparison. |
| dipper-paraphraser-xxl | unavailable | not run | — | Unauthenticated Hub snapshot exposed only README/handler files and no model weights. |
| ling-3.0-tiny | unavailable | not run | — | Pinned conversion requires rapid-mlx; that runtime is not installed, and upstream mlx-lm does not support the bailing_hybrid architecture. |

## Safety and promotion

Every raw output remains available through the score bundle's `results` rows. A hard-safety failure means the candidate is not eligible to win that case. No production model selection or promotion was performed by this report.

## Source score bundles

- original-reference: [original-reference.raw.jsonl](../original-reference.raw.jsonl)
- local-safe-engine: [local-safe-engine.jsonl](../local-safe-engine.jsonl)
- qwen3-4b-incumbent-bestof4-raw: [qwen3-4b-bestof4.raw-winners.jsonl](../qwen3-4b-bestof4.raw-winners.jsonl)
- qwen3-4b-incumbent: [qwen3-4b-incumbent.raw.jsonl](../qwen3-4b-incumbent.raw.jsonl)
- qwen35-4b-control: [qwen35-4b.raw.jsonl](../qwen35-4b.raw.jsonl)
- coedit-large-research: [coedit-large.raw.jsonl](../coedit-large.raw.jsonl)
- minicpm5-2b: [minicpm5-2b.raw.jsonl](../minicpm5-2b.raw.jsonl)
