# Word Studio v2 leaderboard: screen set

6 candidates on the 40-task screen set, pooled from 2 blind judging folder(s). Ranked by top3_at_bar, then usable_per_task (v2/RUBRIC.md). Latency is Kaggle T4, Transformers fp16, not the Mac.

| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Usable / task | Strict JSON | First option p50 | Judged in |
|---|---|---|---|---|---|---|---|
| qwen35-35b-a3b-gptq-int4 | 84.2% | 79.1% to 89.3% | leader | 4.65 | 40/40 | 8.6 s | `2026-10-22T2005Z-screen-ad5a469` |
| qwen35-4b | 80.8% | 71.7% to 90.0% | +3.3% (-8.2% to 14.9%), not separable | 4.83 | 39/40 | 1.2 s | `2026-10-16T1933Z-screen-0dd011b` |
| smollm3-3b | 78.3% | 72.6% to 84.1% | +5.8% (-0.4% to 12.1%), not separable | 4.65 | 27/40 | 0.9 s | `2026-10-16T1933Z-screen-0dd011b` |
| phi4-mini-instruct | 70.8% | 62.4% to 79.2% | +13.3% (8.2% to 18.5%) | 4.35 | 34/40 | 0.5 s | `2026-10-16T1933Z-screen-0dd011b` |
| minicpm5-2b | 48.3% | 34.1% to 62.5% | +35.8% (19.8% to 51.9%) | 2.33 | 39/40 | 0.7 s | `2026-10-16T1933Z-screen-0dd011b` |
| qwen35-2b | 44.2% | 33.9% to 54.5% | +40.0% (32.7% to 47.3%) | 2.85 | 34/40 | 0.7 s | `2026-10-16T1933Z-screen-0dd011b` |

| Judging folder | Judge | Effort | Model verified per call | Anchor agreement |
|---|---|---|---|---|
| `bench/word-studio/v2/judging/2026-10-16T1933Z-screen-0dd011b` | claude:claude-opus-5-5 | high | yes | no anchors |
| `bench/word-studio/v2/judging/2026-10-22T2005Z-screen-ad5a469` | claude-subagent:claude-opus-5-5 | high | no | 10 anchors: same label 91.7%, same side of the bar 98.3%, top-3 shift +0.0% |

**Mixed judges.** The folders were judged by different judge setups. Gaps between candidates from different folders also include any judge difference; see the anchor agreement.

Intervals: per-task mean, standard error clustered by source paragraph, t interval with clusters-1 df (Miller 2024, arXiv:2411.00640).

Every number traces to `leaderboard.json` and, through it, to each folder's verified scores and raw outputs.
