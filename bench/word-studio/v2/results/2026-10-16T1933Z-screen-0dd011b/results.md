# Word Studio v2 results: 2026-10-16T1933Z-screen-0dd011b

Set `screen`, 40 tasks judged blind (legacy_unspecified; complete task set: true) by claude:claude-opus-5-5 via `claude-code` at `high` effort (session `batch:9b4fa710b3ccac9d08a03d0d5af9de95c7702367e3fdc20ad6585a20da36b9ed`). Ranked by top3_at_bar, then usable_per_task (v2/RUBRIC.md). Latency is Kaggle T4, Transformers fp16, not the Mac.

| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Top-1 at bar | Top-3 strong | Usable / task | Strict JSON | First option p50 | Third option p50 | Complete set |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen35-4b | 80.8% | 71.7% to 90.0% | leader | 85.0% | 45.8% | 4.83 | 39/40 | 1.2 s | 2.9 s | yes |
| smollm3-3b | 78.3% | 72.6% to 84.1% | +2.5% (-8.6% to 13.6%), not separable | 92.5% | 37.5% | 4.65 | 27/40 | 0.9 s | 2.1 s | yes |
| phi4-mini-instruct | 70.8% | 62.4% to 79.2% | +10.0% (-4.3% to 24.3%), not separable | 82.5% | 38.3% | 4.35 | 34/40 | 0.5 s | 1.1 s | yes |
| minicpm5-2b | 48.3% | 34.1% to 62.5% | +32.5% (15.3% to 49.7%) | 55.0% | 20.0% | 2.33 | 39/40 | 0.7 s | 1.5 s | yes |
| qwen35-2b | 44.2% | 33.9% to 54.5% | +36.7% (19.3% to 54.0%) | 55.0% | 22.5% | 2.85 | 34/40 | 0.7 s | 1.6 s | yes |

Not judged (run failed):

- control-missing-revision: failed at load: 404 Client Error. (Request ID: Root=1-6ad280f7-5621c9316fcdc9ce1981b602;b4171813-d9b5-4314-a14f-59fa71853f1b)

Intervals: per-task mean, standard error clustered by source paragraph, t interval with clusters-1 df (Miller 2024, arXiv:2411.00640). "Not separable" means the paired gap's interval includes 0, so this task set cannot tell that candidate from the leader.

Every number above traces to `results.json`, which lists each task id, output ref, raw output path and sha256 it came from.
