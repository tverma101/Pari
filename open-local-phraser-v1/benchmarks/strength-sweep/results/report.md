# Pari strength sweep

Synthetic cases: 40; slider values measured: 101 (0–100).

Automatic diagnostics are not a human-quality score. `eligibleChanged` means the output changed and passed Pari's existing protected-content, rewrite-quality, and meaning-contract checks; a human still decides whether the wording is actually better.

Strength band averages below average per-slider-value measurements, so every setting is represented without printing 101 repetitive rows. Full values and per-case outputs are in `report.json`.

| Band | Slider values | Changed rate | Gate-passing changed rate | Lexical change | Structural change* |
| --- | ---: | ---: | ---: | ---: | ---: |
| Light | 25 | 0.158 | 0.158 | 0.007 | 0 |
| Balanced | 25 | 0.34 | 0.34 | 0.023 | 0 |
| Strong | 25 | 0.425 | 0.425 | 0.039 | 0.066 |
| Deep | 26 | 0.425 | 0.425 | 0.047 | 0.15 |

Boundary checks:

| Strength | Changed | Gate-passing changed | Lexical change | Structural change* |
| ---: | ---: | ---: | ---: | ---: |
| 0 (Light) | 6/40 | 6/40 | 0.007 | 0 |
| 24 (Light) | 7/40 | 7/40 | 0.008 | 0 |
| 25 (Balanced) | 12/40 | 12/40 | 0.016 | 0 |
| 49 (Balanced) | 16/40 | 16/40 | 0.029 | 0 |
| 50 (Strong) | 17/40 | 17/40 | 0.039 | 0 |
| 74 (Strong) | 17/40 | 17/40 | 0.039 | 0.275 |
| 75 (Deep) | 17/40 | 17/40 | 0.047 | 0.15 |
| 100 (Deep) | 17/40 | 17/40 | 0.047 | 0.15 |

*Structural change is a heuristic: sentence-count movement or changed order among shared tokens. It detects restructuring, not improvement. Sentence-count and token-order rates remain separately available in `report.json`.

The blinded pairwise sheet compares adjacent strength-band values (16, 40, 60, 90). Share only the CSV file; the separate internal key maps pair IDs to strengths. For each dimension, record A, B, or Tie.
