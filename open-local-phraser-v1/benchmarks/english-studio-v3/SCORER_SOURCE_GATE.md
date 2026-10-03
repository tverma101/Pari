# Scorer source-provenance gate contract (#67)

`score-english-core-public-full-classification.py` is owned by issue #64 and is
not edited here. This file is the hook contract the #67 builder and preparation
step were built against, so the gate can be wired without re-deriving the
source-identity rules.

Everything below is enforced by `english_core_public_sources.py` today; the
scorer only needs to call it.

## Where the gate belongs

In `main()`, immediately after the existing manifest case-count check (the
`if int(manifest.get("cases", -1)) != len(tasks)` block) and before any metric
is computed:

```python
from english_core_public_sources import (
    SOURCE_CONTRACT_VERSION,
    source_manifest_gate_report,
)

# ...
promotion = "--promotion" in flags
if promotion:
    contract_version = manifest.get("sourceContractVersion")
    if contract_version != SOURCE_CONTRACT_VERSION:
        raise SystemExit(
            f"Public-full manifest source contract {contract_version!r} is not "
            f"understood by this scorer (expected {SOURCE_CONTRACT_VERSION})"
        )
    if not manifest.get("promotionEligible"):
        raise SystemExit(
            "Public-full promotion scoring requires a promotion-eligible manifest; "
            "this build is exploratory and its gate findings are: "
            + json.dumps(
                (manifest.get("promotion") or {}).get("gateErrors", [])
                + (manifest.get("promotion") or {}).get("gateWarnings", [])
            )
        )
    errors, warnings = source_manifest_gate_report(
        manifest.get("sources"),
        manifest.get("resolvedDatasetFingerprints"),
        promotion=True,
    )
    if errors or warnings:
        raise SystemExit(
            "Public-full promotion scoring refused; source provenance gate failed:\n- "
            + "\n- ".join(errors + warnings)
        )
```

`source_manifest_gate_report(..., promotion=True)` already promotes the
mutable-request and missing-fingerprint findings from warnings to errors, so the
single call covers every promotion requirement below.

## What promotion mode must refuse

`english_core_public_sources.source_manifest_gate_report` reports one problem
per line. Under `promotion=True` the scorer must exit non-zero when any appear.

For each of `WiC`, `CoLA`, and `PAWS`:

1. **Canonical repository.** `sources[name].dataset` must equal the canonical
   repo ID in `PUBLIC_SOURCE_IDENTITIES`. A different ID fails, unless the
   versioned source manifest declares a `protocolOverrides` entry naming that
   exact non-canonical ID plus a `reviewedIn` reference.
2. **No retired alias.** `sources[name].dataset` must not be a key of
   `RETIRED_SOURCE_ALIASES`. The bare `paws` identifier is a 307 redirect to
   `google-research-datasets/paws`, so it has no independent commit history. An
   override never permits it.
3. **Config and split.** `sources[name].config` and `sources[name].split` must
   equal the canonical values: `wic`/`validation`, `cola`/`validation`,
   `labeled_final`/`validation`.
4. **Full resolved commit.** `sources[name].resolvedRevision` must match
   `^[0-9a-f]{40}$`.
5. **Immutable requested ref.** `sources[name].requestedRevision` must be
   present and must not be a moving ref: `""`, `main`, `master`, `head`,
   `latest`, `default`, `unknown`, `mutable_default_not_pinned`, or absent.
   A branch or tag name is also refused, even though the build resolved it
   correctly, because a moving name cannot be re-verified later.
6. **One-shot resolution recorded.** `sources[name].revisionResolution` must
   equal `"hf-api-dataset-info-sha-once"`.
7. **Resolved fingerprint.** `resolvedDatasetFingerprints[name]` must be a
   non-empty string (or a dict whose values are all non-empty).

Plus, for the manifest as a whole:

8. `sources` must be a non-empty object containing all three of WiC, CoLA, and
   PAWS.
9. No other source may name a retired alias.

## What the scorer must NOT do

- **Do not accept a task-file hash match as promotion evidence.** The existing
  `taskFileSha256` check proves the result was produced against these exact task
  bytes. It says nothing about where those bytes came from. Promotion mode must
  apply this gate *in addition to* the hash check, never instead of it.
- **Do not upgrade an exploratory build.** A manifest with
  `promotionEligible: false` is refused outright, even if every other field is
  perfect and the fingerprints are present.
- **Do not re-resolve refs at scoring time.** Scoring must read the recorded
  `resolvedRevision`. Re-resolving would reintroduce the moving-ref race the
  builder already closed.
- **Do not widen the gate to the public-fast scorer.** The two lanes have
  different contracts; `score-english-core-public-fast.py` has its own manifest
  and its own issues.

## Provenance to copy into the score artifact

The scorer already copies `manifestSources`, `resolvedDatasetFingerprints`, and
`datasetsLibraryVersion` into `inputs` (the `inputs` block near the end of
`main()`). For #65 analysis provenance to bind the finalist lane, add:

```python
"sourceContractVersion": manifest.get("sourceContractVersion"),
"promotionEligible": manifest.get("promotionEligible"),
"preparationReceipt": manifest.get("preparationReceipt"),
```

where `preparationReceipt` is the block below. Every value is a 64-hex
SHA-256, so `english-core-snapshot-binding.mjs`'s `verifyFrozenScoreHashes`
harvesting will pick it up when a `--source-score-manifest` is supplied.

## Preparation-receipt binding

`prepare-english-core-public-full.py` writes
`english-core-public-full-classification.preparation.json` with:

| Key | Meaning |
| --- | --- |
| `schema` | `pari.english-core.public-full-preparation-receipt` |
| `version` | `1` |
| `protocolVersion` | `pari.english-core.public-full-finalist-1` |
| `sourceContractVersion` | must equal `SOURCE_CONTRACT_VERSION` |
| `promotionEligible` | false when the env lock or tree binding is unverified |
| `files` | `{filename: {sha256, bytes, cases?}}` for task, answer, and manifest |
| `orderedTaskIdsSha256` | the same canonical digest convention as the prepared stage register |
| `manifestSha256` | SHA-256 of the built manifest file |
| `frozenSources` | `{file, sha256, sources: {name: {dataset, config, split, resolvedRevision}}}` |
| `benchmarkTree` | `{head, tree, branch, promotionEligible}` from `verify_git_identity` (#40) |
| `isolatedDataEnvironment` | includes the verified `dependencyLock.sha256` (#52) |
| `laneSeparation` | `commonScreenArtifact`, `commonScreenCases: 1943`, and the separation rule |
| `scorerContract` | the contract reproduced in this file |

A scorer in promotion mode should additionally require, when a receipt is
supplied, that `receipt.protocolVersion` equals its own protocol version and
that `receipt.promotionEligible` is true.

## Lane separation

The finalist lane is **not** part of the balanced 1,943-case common screen.
`prepare-kaggle-benchmark.py` and `verify-kaggle-benchmark-preparation.py` are
deliberately unchanged, `kaggle-stage-manifest.json` gains no new stage, and
`EXPECTED` in either file is not extended. Nothing in the receipt path writes
`english-core-fixed-screen.jsonl`. If a future change adds full-distribution
rows to the common screen, that is a protocol change, not a preparation change,
and it is out of scope for #67.

## Local verification

```bash
python3 test_english_core_public_full_sources.py
```

30 synthetic cases cover mutable refs, wrong repository, wrong-repository
commit, post-resolution drift, reproducibility, and the receipt bindings. They
need no network, no `datasets`, and no GPU.

The registry entry for this work is `finalist-source-identity` in
`kaggle-runbook-contract.json`, executed by `self-check-english-core.sh`.

To verify a receipt produced on another machine:

```bash
python3 prepare-english-core-public-full.py --verify-only \
  --receipt english-core-public-full-classification.preparation.json \
  --benchmark-revision BENCHMARK_GIT_COMMIT
```

It prints a `status` of `verified` or `unqualified` with a `failures` list, and
exits `2` when unqualified.
