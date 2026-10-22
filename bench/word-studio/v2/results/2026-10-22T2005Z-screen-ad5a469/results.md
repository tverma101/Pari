# Word Studio v2 results: 2026-10-22T2005Z-screen-ad5a469

Set `screen`, 40 tasks judged blind (recorded_run_tasks; complete task set: true) by claude-subagent:claude-opus-5-5 via `claude-code-subagent` (model not verified per call) at `high` effort (session `batch:4b80dcd67108f6abd5cae5de0f10ccc65c9c2e12e255c1f141be42f3a46331b6`). Ranked by top3_at_bar, then usable_per_task (v2/RUBRIC.md). Latency is Kaggle T4, Transformers fp16, not the Mac.

| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Top-1 at bar | Top-3 strong | Usable / task | Strict JSON | First option p50 | Third option p50 | Complete set |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen35-35b-a3b-gptq-int4 | 84.2% | 79.1% to 89.3% | leader | 95.0% | 49.2% | 4.65 | 40/40 | 8.6 s | 15.6 s | yes |

Drift anchors: 10 already-judged outputs were judged again blind. Same label on 91.7% of 60 options, same side of the bar on 98.3%; top-3 at bar moved +0.0% on average.

Intervals: per-task mean, standard error clustered by source paragraph, t interval with clusters-1 df (Miller 2024, arXiv:2411.00640). "Not separable" means the paired gap's interval includes 0, so this task set cannot tell that candidate from the leader.

Every number above traces to `results.json`, which lists each task id, output ref, raw output path and sha256 it came from.
