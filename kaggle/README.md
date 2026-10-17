# Kaggle

Kaggle notebooks for Pari's heavy work on 2×T4: running benchmark candidates,
generating data, and fine-tuning. Modal's free credits are overflow for
fine-tuning only. See [`../docs/PLAN.md`](../docs/PLAN.md).

Shared benchmark code stays in `../bench/word-studio/`; kernels here call it.

## Word Studio v2 (`word-studio/`)

- `launch.py` fills in `kernel.py` and pushes it as a private 2×T4 kernel
  (`<user>/pari-word-studio-v2`). The kernel clones this repository at one
  pushed commit and runs `v2.run_candidate` once per candidate, each in its own
  process with a time limit. `--dry-run` writes the kernel folder without
  pushing.
- `fetch.py` copies the kernel's `runs/<run-id>/` into
  `../bench/word-studio/v2/runs/<run-id>/`. It never overwrites a run.

See [`../bench/word-studio/v2/README.md`](../bench/word-studio/v2/README.md) for
the whole workflow.

Rule: a notebook that fails records the failure. It never substitutes fallback
or "calibrated" numbers.
