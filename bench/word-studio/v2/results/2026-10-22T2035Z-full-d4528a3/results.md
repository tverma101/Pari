# Word Studio v2 results: 2026-10-22T2035Z-full-d4528a3

Set `full`, 200 tasks judged blind (recorded_run_tasks; complete task set: true) by claude-subagent:claude-opus-5-5 via `claude-code-subagent` (model not verified per call) at `high` effort (session `batch:279d8788a4ed49261278dc2530b8539fc52bf66bbc82b3473b120dd973f93548`). Ranked by top3_at_bar, then usable_per_task (v2/RUBRIC.md). Latency is Kaggle T4, Transformers fp16, not the Mac.

| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Top-1 at bar | Top-3 strong | Usable / task | Strict JSON | First option p50 | Third option p50 | Complete set |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen35-35b-a3b-gptq-int4 | 81.2% | 76.6% to 85.8% | leader | 89.0% | 37.2% | 4.75 | 200/200 | 8.4 s | 15.4 s | yes |

Drift anchors: 10 already-judged outputs were judged again blind. Same label on 92.6% of 81 options, same side of the bar on 95.1%; top-3 at bar moved -3.3% on average.

Intervals: per-task mean, standard error clustered by source paragraph, t interval with clusters-1 df (Miller 2024, arXiv:2411.00640). "Not separable" means the paired gap's interval includes 0, so this task set cannot tell that candidate from the leader.

Every number above traces to `results.json`, which lists each task id, output ref, raw output path and sha256 it came from.
