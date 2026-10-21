# Word Studio v2 results: 2026-10-21T1438Z-full-684c74b

Set `full`, 200 tasks judged blind (recorded_run_tasks; complete task set: true) by claude-subagent:claude-opus-5-5 via `claude-code-subagent` (model not verified per call) at `high` effort (session `batch:27164ceea4968fd537d5d9fc7d665b4cfc1dcc0b2c2a07bf1611d684b6321a3c`). Ranked by top3_at_bar, then usable_per_task (v2/RUBRIC.md). Latency is Kaggle T4, Transformers fp16, not the Mac.

| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Top-1 at bar | Top-3 strong | Usable / task | Strict JSON | First option p50 | Third option p50 | Complete set |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen35-4b | 75.3% | 70.4% to 80.3% | leader | 82.0% | 33.0% | 4.39 | 180/200 | 1.4 s | 3.2 s | yes |
| phi4-mini-instruct | 72.5% | 68.8% to 76.2% | +2.8% (-2.5% to 8.1%), not separable | 80.0% | 28.8% | 4.11 | 170/200 | 0.5 s | 1.3 s | yes |
| smollm3-3b | 69.8% | 65.0% to 74.7% | +5.5% (-0.5% to 11.5%), not separable | 79.0% | 25.7% | 3.77 | 120/200 | 0.9 s | 2.0 s | yes |

Not judged (run failed):

- control-missing-revision: failed at load: 404 Client Error. (Request ID: Root=1-6ad8dae5-0507c56b2ddc39e8567e6098;ec39195d-413c-438a-b01a-cd28561b3112)

Intervals: per-task mean, standard error clustered by source paragraph, t interval with clusters-1 df (Miller 2024, arXiv:2411.00640). "Not separable" means the paired gap's interval includes 0, so this task set cannot tell that candidate from the leader.

Every number above traces to `results.json`, which lists each task id, output ref, raw output path and sha256 it came from.
