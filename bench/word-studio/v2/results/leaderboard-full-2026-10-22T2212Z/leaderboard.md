# Word Studio v2 leaderboard: full set

4 candidates on the 200-task full set, pooled from 2 blind judging folder(s). Ranked by top3_at_bar, then usable_per_task (v2/RUBRIC.md). Latency is Kaggle T4, Transformers fp16, not the Mac.

| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Usable / task | Strict JSON | First option p50 | Judged in |
|---|---|---|---|---|---|---|---|
| qwen35-35b-a3b-gptq-int4 | 81.2% | 76.6% to 85.8% | leader | 4.75 | 200/200 | 8.4 s | `2026-10-22T2035Z-full-d4528a3` |
| qwen35-4b | 75.3% | 70.4% to 80.3% | +5.8% (0.8% to 10.8%) | 4.39 | 180/200 | 1.4 s | `2026-10-21T1438Z-full-684c74b` |
| phi4-mini-instruct | 72.5% | 68.8% to 76.2% | +8.7% (4.5% to 12.9%) | 4.11 | 170/200 | 0.5 s | `2026-10-21T1438Z-full-684c74b` |
| smollm3-3b | 69.8% | 65.0% to 74.7% | +11.3% (6.2% to 16.5%) | 3.77 | 120/200 | 0.9 s | `2026-10-21T1438Z-full-684c74b` |

| Judging folder | Judge | Effort | Model verified per call | Anchor agreement |
|---|---|---|---|---|
| `bench/word-studio/v2/judging/2026-10-21T1438Z-full-684c74b` | claude-subagent:claude-opus-5-5 | high | no | no anchors |
| `bench/word-studio/v2/judging/2026-10-22T2035Z-full-d4528a3` | claude-subagent:claude-opus-5-5 | high | no | 10 anchors: same label 92.6%, same side of the bar 95.1%, top-3 shift -3.3% |

Intervals: per-task mean, standard error clustered by source paragraph, t interval with clusters-1 df (Miller 2024, arXiv:2411.00640).

Every number traces to `leaderboard.json` and, through it, to each folder's verified scores and raw outputs.
