# Pari

## Current plan

Start from [`docs/PLAN.md`](docs/PLAN.md), mirrored in pinned issue #93 (2026-10-15). It supersedes #71 and the 2026-10-07 plan.

- Pari is a Mac writing assistant for essays: a tap-word popover and a Word Lab panel. The writer picks every final word.
- Kaggle (2×T4) runs the benchmark, data generation and fine-tuning. Modal's free credits are only overflow for fine-tuning. The final runtime is a quantized model on the 16 GB Mac, so local-generator work is allowed again.
- Choose the model with the Word Studio benchmark in `bench/`. Claude judges it blind in-session: candidate names hidden, every score citing a task id and a raw output file.
- Evidence rule: no number goes into a results file unless a real run produced it and its raw outputs are kept. No fallback or "calibrated" values. A failed run is recorded as failed. PR #82 broke this rule; its results were removed.
- Issues labelled `owner-only` (distillation data from big LLMs) are run by the owner. Agents may prepare formats, prompts and validation scripts, but never generate that data.
- Keep the studio's pick log (#74) working so personal fine-tuning data builds up. Never commit that log: this repository is public.
- Issues labelled `parked` were closed on purpose. Don't reopen them to unblock the tracks.
- Take work from open `agent-ready` issues. Priority follows the labels: `track:benchmark` (P0), then `track:studio` (P1), then `track:fine-tune` (P2).

## Layout

| Folder | Purpose |
|---|---|
| `app/` | Mac app. Rules in `app/AGENTS.md`. |
| `bench/` | Word Studio tasks, runners and scoring. |
| `kaggle/` | Kaggle notebooks: candidate runs, data generation, training. |
| `model/` | Quantize (and, only if ever needed, distill) models to MLX for the Mac. |
| `docs/` | The plan and the decisions log. |

Old experiments (`lab/`, the old `app/benchmarks` suites, `app/research/`, superseded planning docs) are on branch `archive/2026-10` and tag `archive-2026-10`.
