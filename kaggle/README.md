# Kaggle

Kaggle notebooks for Pari's heavy work on 2×T4: running benchmark candidates,
generating data, and fine-tuning. Modal's free credits are overflow for
fine-tuning only. See [`../docs/PLAN.md`](../docs/PLAN.md).

Empty until the benchmark runner lands (#86). Shared benchmark code stays in
`../bench/word-studio/`; notebooks here call it.

Rule: a notebook that fails records the failure. It never substitutes fallback
or "calibrated" numbers.
