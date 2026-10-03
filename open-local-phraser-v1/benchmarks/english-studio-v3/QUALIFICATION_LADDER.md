# Frozen stage identity and the Q1-Q6 qualification ladder

This covers issues #48 and #49. One register,
`kaggle-stage-manifest.json`, is the single source of truth; every wrapper,
validator and the candidate matrix read it through `kaggle_stage_identity.py`
instead of restating hashes, counts or subset rules.

## Stage identity (issue #48)

Each registered stage pins:

- stage ID and the qualification gate it satisfies;
- the canonical artifact path and its frozen SHA-256;
- the expected task count;
- the ordered task-ID digest, so a reordered suite cannot satisfy the contract;
- the parser contract and batch policy;
- `subsetRule`, which defines any subset explicitly so it stays hashable.

`resolve_stage_tasks(stage, override)` has three outcomes:

- **canonical** — the registered artifact, bound to its frozen count and hashes;
- **canonical-subset** — a registered frozen prefix, used by Q3;
- **exploratory** — an unregistered `--tasks` path, explicitly non-promotion and
  non-comparable, still carrying its own hash so the evidence stays auditable.

A registered path whose bytes or ID order drifted is a hard contract error. An
arbitrary filesystem path cannot become promotion-valid merely by recording its
own hash; in promotion mode it raises, and only `--exploratory-tasks` (dispatcher)
or `promotion_run=False` (library) resolves it as exploratory.

## Qualification ladder (issue #49)

| Gate | Receipt key | Stage | Requires | Meaning |
| --- | --- | --- | --- | --- |
| q0 | `q0-preflight` | — | — | environment preflight |
| q1 | `q1-load` | — | q0 | exact load, GPU placement, no silent CPU fallback, trivial generation, runtime alive |
| q2 | `q2-protocol` | `smoke` | q1 | frozen response-protocol smoke |
| q3 | `q3-benchmark-smoke` | `benchmark-smoke` | q2 | bounded frozen English benchmark smoke |
| q4 | `q4-full` | `full` | q3 | complete 1,943-case screen; promotion-quality |
| q5 | `q5-product` | `word-studio` | q4 | finalist strength suite |
| q6 | `q6-transform` | `transform` | q4 | finalist transform suite |

The ladder is sequential. `run-kaggle-candidate.py --stage <s>` resolves the
stage's gate before any model or runtime work and refuses to launch when a
required prior receipt is missing or unfinished. Pass completed receipts with
`--prior-receipts receipts.json`; `--allow-unmet-prerequisites` proceeds but marks
the run explicitly non-comparable. Earlier receipts always stay visible in the
per-gate summary files and in the returned gate evidence.

Q4 (`full`) therefore cannot launch without completed Q1 -> Q2 -> Q3 evidence.

## Q3 is a registered frozen subset

Q3 consumes the first `subsetPrefixCount` ordered task IDs of the canonical
`english-core-fixed-screen.jsonl`. That prefix rule is recorded in the register
and its digest is computed from the ordered IDs, so `--limit N` is not the
definition and cannot drift with whatever the artifact's first N rows happen to
be. Q3 is bounded English evidence and pipeline qualification, not the complete
comparison.

The existing Q2 routing is preserved: `run-kaggle-candidate.py` still routes the
frozen 16-case `kaggle-protocol-smoke.jsonl` into `--stage smoke` for both the
vLLM and Prism paths. That wiring was not rebuilt or duplicated.

## Reporting

`build-kaggle-candidate-matrix.py` emits a `qualification` block per candidate
with the per-gate receipts, `gatesCompleted`, `highestGateReached` and
`gatesNotCompleted`, so a single ambiguous `smoke` cell can no longer hide a
Q1-only or Q3-only result. It also records `stageManifestSha256`, which #33 and
#30 can bind alongside the existing task-manifest hashes.

## Verifying

```
python3 test_kaggle_stage_ladder.py
python3 kaggle_stage_identity.py --print-register
python3 kaggle_stage_identity.py --print-ladder --receipts receipts.json
```

## Limits

The fixed English screen and Word Studio suites are generated, so their task
files are absent from a clean checkout. Word Studio keeps checked-in task
identity hashes. The full screen and Q3 benchmark-smoke instead declare
`identitySource: prepared-register`: the preparation step writes
`kaggle-stage-manifest.prepared.json` with each generated artifact's hash,
count, byte length, and ordered-ID digest (plus the Q3 prefix digest). The
preparation receipt binds that register and the exact benchmark revision. The
verifier checks both bindings and the task bytes before the runner accepts the
register. Without the generated register and valid receipt, promotion-stage
resolution fails closed; the checked-in manifest's unresolved entries do not
stand in for prepared task identity.
