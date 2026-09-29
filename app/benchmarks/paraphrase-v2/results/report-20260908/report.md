# Pari Paraphrase Quality Benchmark v2 report

Generated: 2026-09-09T00:56:47.807Z
Corpus: 72 cases, version 2

## Decision boundary

Human ratings supplied: **no**. The automatic leader below is diagnostic only; issue #11's human preference gate remains open.
Automatic diagnostic leader: **qwen3-4b-incumbent**.
Shippable candidate with current installed evidence and zero hard-safety failures: **none**.

## Automatic diagnostics

| Engine | Role | Full gate | Meaning-safe | English-quality | Auto index | Hard safety failures | Median s | Peak GiB | Pareto |
|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| original-reference | no-rewrite-safety-reference | 0.0% | 100.0% | 0.0% | 39.740 | 0 | 0.000 | 0.042 | yes |
| local-safe-engine | deterministic-safety-reference | 30.6% | 100.0% | 30.6% | 56.440 | 0 | 0.003 | 0.168 | yes |
| qwen3-4b-incumbent | production-incumbent | 90.3% | 94.4% | 95.8% | 89.310 | 4 | 1.450 | 2.258 | yes |
| qwen3-4b-incumbent-pari-boundary | production-incumbent | 88.9% | 93.1% | 94.4% | 88.030 | 5 | 1.450 | 2.258 | no |
| qwen35-4b-control | benchmark-control | 88.9% | 88.9% | 100.0% | 88.040 | 8 | 1.685 | 2.520 | no |
| minicpm5-2b | challenger | 29.2% | 98.6% | 30.6% | 55.890 | 1 | 0.868 | 1.536 | no |

The automatic index combines full-gate pass rate, meaning-safe rate, English-quality rate, and the bundled learned judge's English/fluency signals. It is a reproducible diagnostic, not a human-quality score and not a promotion decision.

## Runtime receipts

| Engine | Model/revision | Runtime | License | Installed evidence |
|---|---|---|---|:---:|
| original-reference | — | none | source text | no |
| local-safe-engine | — | Pari TypeScript local-safe engine | project code; see repository license | no |
| qwen3-4b-incumbent | Qwen/Qwen3-4B-MLX-4bit @ 52a5ab34fa604bc8af6d3ce0cac0cab10b7eb495 | mlx-lm | apache-2.0 | no |
| qwen3-4b-incumbent-pari-boundary | Qwen/Qwen3-4B-MLX-4bit @ 52a5ab34fa604bc8af6d3ce0cac0cab10b7eb495 | mlx-lm | apache-2.0 | no |
| qwen35-4b-control | mlx-community/Qwen3.5-4B-MLX-4bit @ 32f3e8ecf65426fc3306969496342d504bfa13f3 | mlx-lm | apache-2.0 | no |
| minicpm5-2b | openbmb/MiniCPM5-2B-MLX @ 014e7591ff4b1b6330cda7f45803b27f46288261 | mlx-lm | apache-2.0 | no |

## Human handoff

Use [pairwise-blinded.csv](pairwise-blinded.csv) for blinded A/B judgments and keep [pairwise-key.json](pairwise-key.json) separate until scoring is complete. [human-scores-template.csv](human-scores-template.csv) is the per-engine 1–5 rubric template.

## Safety and promotion

Every raw output remains available through the score bundle's `results` rows. A hard-safety failure means the candidate is not eligible to win that case. No production model selection or promotion was performed by this report.

## Source score bundles

- original-reference: [original-reference.raw.jsonl](../original-reference.raw.jsonl)
- local-safe-engine: [local-safe-engine.jsonl](../local-safe-engine.jsonl)
- qwen3-4b-incumbent: [qwen3-4b-incumbent.raw.jsonl](../qwen3-4b-incumbent.raw.jsonl)
- qwen3-4b-incumbent-pari-boundary: [qwen3-4b-incumbent.raw.jsonl](../qwen3-4b-incumbent.raw.jsonl)
- qwen35-4b-control: [qwen35-4b.raw.jsonl](../qwen35-4b.raw.jsonl)
- minicpm5-2b: [minicpm5-2b.raw.jsonl](../minicpm5-2b.raw.jsonl)
