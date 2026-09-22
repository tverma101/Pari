# Strength-sweep result index

Each run keeps per-request rows, a run manifest, and a derived summary where
available. Treat automatic metrics as diagnostics, not human-quality scores.

- [`report.md`](report.md) and [`report.json`](report.json) are the earlier
  deterministic fallback sweep: 40 synthetic cases at all 101 slider values
  (4,040 rows). It is not an LLM result.
- [`native-brutal-v2/`](native-brutal-v2/) contains the 31-case target-only
  native-model stress run.
- [`qwen35-mtp-brutal-v2/`](qwen35-mtp-brutal-v2/) contains 217 MTP-only rows
  across the seven representative slider values. Its `judge-*` subfolders are
  incomplete/invalid offline judge attempts retained for audit; they do not
  contribute to any reported score.
- [`qwen35-mtp-pilot-brutal-v2/`](qwen35-mtp-pilot-brutal-v2/) contains 30
  matched target-only/MTP timings with both models already loaded.
- [`qwen35-mtp-cold-pilot-v1/`](qwen35-mtp-cold-pilot-v1/) contains six
  matched fresh-worker timings, including model startup and load.
- [`human-review.csv`](human-review.csv) is the blinded pairwise review sheet.
  Its answer key is intentionally excluded and ignored by Git.

Absolute machine-local paths have been replaced in manifests and raw rows with
portable model labels. The recorded model revisions, source hashes, corpus
hashes, runtime versions, and output rows are preserved. The MTP runs were
captured from a dirty local checkout; see the parent benchmark report for the
exact provenance limitation before treating them as reproducible from the
current branch.
