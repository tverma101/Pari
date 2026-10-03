# Word Studio blinded human/product evaluation pipeline

GitHub issue #69. The methodology is `ENGLISH_CORE_HUMAN_EVAL.md`; this document
covers the executable chain that implements it.

**Status: pipeline implemented and tested on synthetic fixtures. No human ratings
exist.** Every number this tooling has ever produced describes synthetic fixture
ratings, never product quality. Real ratings require independent human raters and
remain uncompleted.

## What this is not

- Not an LLM-as-judge. No model scores any output here.
- Not a winner picker. There is no universal champion and no opaque product
  scalar. `analyze()` returns `collapsedScalar: null` on purpose.
- Not a packet distributor. Nothing in this chain uploads, emails or otherwise
  sends a packet. `build-word-studio-human-eval.py` writes local files only.

## Files

| File | Role |
| --- | --- |
| `word_studio_human_eval.py` | The whole frozen chain: provenance, preregistration, blinding, rating validation, analysis |
| `build-word-studio-human-eval.py` | CLI: freeze the preregistration and build per-rater packets |
| `validate-word-studio-human-eval-ratings.py` | CLI: strict rating validation, emits normalized documents |
| `analyze-word-studio-human-eval.py` | CLI: criterion-specific paired analysis; reveals the mapping last |
| `word-studio-human-eval-rating-schema.json` | Standalone JSON Schema for rater submissions (also emitted by the builder) |
| `test_word_studio_human_eval.py` | Synthetic CPU-only fixtures; registered in `self-check-english-core.sh` |

The candidate texts in a packet come from the one canonical
`word_studio_output_parser.py` contract, so "usable candidate" means the same
thing offline and in the review packet.

## Step 1 — freeze (build)

```bash
python3 build-word-studio-human-eval.py \
  --tasks word-studio-transform.jsonl \
  --results finalist-a.result.json --results finalist-b.result.json \
  --out-dir /private/eval/run-1 \
  --seed "<frozen seed>" \
  --raters r-alpha,r-beta,r-gamma
```

Inputs are provenance-qualified or refused. Each result artifact must declare
the exact `taskFileSha256` of a frozen task file, and must carry a raw output for
every task in that file. A result bound to a different task file, a task file
whose bytes drifted, or a partial finalist artifact all fail closed rather than
being reconciled.

Output layout:

```
<out-dir>/
  preregistration.json                          frozen policy, digests, seed
  packets/<raterId>.json                        reviewer-visible, blinded
  PRIVATE/human-eval.private-mapping.json       A/B -> finalist mapping
  rating-schema.json                            strict rater schema
  packet-manifest.json                          digests of everything above
```

`--private-mapping` is refused inside the packet directory, so the mapping cannot
ship with the packets by accident.

### Preregistration contents

Compared task IDs, routes and semantic modes; task-file and result-artifact
digests; rubric and criterion wording; pair-generation policy; randomization
seed; candidate-depth policy (`3,5,10` by default); rater eligibility and
preregistered exclusion rules; minimum annotations per item; the tie and
both-unacceptable policy; the primary analysis plan; and the
disagreement/adjudication policy. It records the finalist **count** and the
result **digests**, never the finalist names. Changing any of these fields after
ratings begin means a new evaluation version, not an edit to the old manifest.

### Author-expectation keys

Default `--author-expectation-mode=not_used`: the private review key is never
opened and its text cannot reach a packet. With
`--author-expectation-mode=reviewer_checklist --reviewer-checklist <key.json>`,
author requirements may appear in a packet only as reviewer checklist text
labelled "author-written checklist, not human-validated gold". Either way they
are never model input, never presented as validated gold, and independent rater
responses stay separately recorded.

## Step 2 — blinding and randomization

Each packet shows source context, the selected span, the operation, the criterion
wording, and two anonymous sides `A` and `B` with their ordered candidates.

- A/B side is **balanced then shuffled**: each finalist appears on side `A` and
  side `B` counts within one of each other, per rater.
- Item order is shuffled per rater from the frozen seed.
- Randomization streams are derived as `HMAC-SHA256(seed, label path)`, so every
  packet is exactly reproducible from the seed.
- Item IDs are opaque `pair-<hmac>` / `src-<hmac>` / `pkt-<hmac>` values.
- Two independent scans gate the build: a structural check over forbidden field
  names (`model`, `revision`, `runtime`, `latencySeconds`, `hardware`, …) and a
  lexical check over runtime words (`vllm`, `cuda`, `nvidia`, `gguf`, …) plus
  every finalist id, revision, file name and path from the result artifacts. A
  hit refuses to write the packet.

## Step 3 — rating ingestion

`word-studio-human-eval-rating-schema.json` is closed (`additionalProperties:
false`) at every level. Rater identity is an anonymous id matching
`^r-[A-Za-z0-9_-]{1,64}$`; no personally identifying information is required or
permitted. Three row kinds:

```json
{
  "schemaVersion": 1,
  "packetId": "pkt-...", "packetSha256": "...",
  "preregistrationSha256": "...", "rubricSha256": "...",
  "raterId": "r-alpha",
  "pairRatings":      [{"pairId": "pair-...", "criterion": "edit_usefulness", "label": "A|B|tie|both_unacceptable"}],
  "candidateRatings": [{"pairId": "pair-...", "side": "A", "candidateId": "1", "label": "usable|not_usable|unclear"}],
  "strengthRatings":  [{"sourceGroupId": "src-...", "requestedStrength": 15,
                        "edit_usefulness": "usable", "semantic_register_stable": "yes",
                        "intensity_increased": "no"}]
}
```

```bash
python3 validate-word-studio-human-eval-ratings.py \
  --preregistration <out-dir>/preregistration.json \
  --private-mapping <out-dir>/PRIVATE/human-eval.private-mapping.json \
  --packets <out-dir>/packets \
  --ratings r-alpha.json --ratings r-beta.json \
  --out-dir <private>/normalized
```

Rejected: unknown pair/item/candidate/source-group IDs; duplicate
rater/pair/criterion or rater/pair/side/candidate rows; a `packetSha256` that is
not the frozen packet (outdated packets); impossible labels; a missing required
criterion for an assigned item; and any private-mapping content that leaks into
reviewer data, including inside a free-text note.

## Step 4 — analysis

```bash
python3 analyze-word-studio-human-eval.py \
  --preregistration <out-dir>/preregistration.json \
  --private-mapping <out-dir>/PRIVATE/human-eval.private-mapping.json \
  --ratings <private>/normalized/r-alpha.ratings.normalized.json \
  --ratings <private>/normalized/r-beta.ratings.normalized.json \
  --out <private>/analysis.json
```

Analysis refuses to pair ratings whose `preregistrationSha256`/`rubricSha256`
disagree, whose binding differs from the frozen preregistration, or whose private
mapping digest does not match its contents.

Reports, per criterion: raw A/tie/B/both-unacceptable counts, annotation and
rater counts, a directional mean with both-unacceptable rows excluded (never
converted to a winner), and a deterministic seeded percentile bootstrap interval.
Per route and per semantic mode. Top-3/5/10 useful-candidate coverage per
finalist, reconstructed from the leading run of `usable` labels. Disagreement
rate plus the highest-divergence opaque pair IDs. Percent agreement and Fleiss'
kappa with their assumptions stated, and a per-source strength trajectory that
reports non-monotonic usefulness, stability drops and intensity inflation rather
than averaging them away. Exclusions carry their reason and a `preregistered` /
`exploratory` status. `blindingReveal` appears last and retains the mapping
digest; `--no-reveal` analyzes blind.

### Criterion selection

Every route gets contextual naturalness, register/intensity preservation, edit
usefulness, structural/lexical diversity and unnecessary inflation. Preservation
routes add meaning/fact preservation. `intentional_compression` tasks **replace**
meaning preservation with `compression_quality` — strict full-paraphrase
equivalence is never applied to them. Tasks declaring protected content, or
sitting in the `protected_context` category, add
`protected_content_correctness`.

### Strength slider

The four slider variants of a source are repeated measures. The packet shows one
`strength_trajectory` item per source with the 15/40/60/90 variants in order,
each with its lead candidate and deterministic change diagnostics
(character similarity, length ratio, token delta). Reviewers judge usefulness,
semantic/register stability, and whether the variant inflated claim intensity.
Change diagnostics are never treated as quality on their own.

## Frozen refusal policy

| Condition | Outcome |
| --- | --- |
| Result artifact bound to a different task file | refused |
| Task file bytes drifted from the frozen hash | refused |
| Finalist artifact missing a task's raw output | refused |
| Fewer than two qualified finalists | refused |
| Packet would carry model/runtime/latency/size metadata | refused, nothing written |
| Author expectation mode not preregistered | refused |
| Mapping placed inside the packet directory | refused |
| Rating doc on an outdated packet hash | rejected |
| Ratings across different rubric/preregistration bindings | refused |
| Tampered private mapping | refused |

## Tests

`python3 test_word_studio_human_eval.py` covers the twelve cases named in the
issue — determinism, output-hash invalidation, metadata blinding, side
counterbalancing, author-expectation containment, unknown/duplicate row
rejection, the compression criterion contract, strength grouping and ordering,
tie and both-unacceptable first-class treatment, mixed-hash refusal, exploratory
post-hoc exclusion, and last-step mapping reveal — plus provenance refusals and
the private-mapping-content rejection. All fixtures are synthetic and local. The
suite runs in `self-check-english-core.sh`.

## Evidence states

- `implemented`: pipeline modules, CLIs, schema and tests.
- `tested`: 16 synthetic fixture tests plus a full local build → validate →
  analyze run over generated fixtures.
- `not installed`, `not live`: nothing is scheduled, uploaded or sent.
- `user-confirmed`: **not reached**. No human rater has submitted a rating. No
  finalist product-quality claim can cite this pipeline yet.

## What is deliberately absent

Shadow-label validation for the author-written forced-choice gold
(`ENGLISH_CORE_HUMAN_EVAL.md` section A) is a separate workstream. This pipeline
covers the generative-output pairwise lane only, as issue #69 scopes it.
