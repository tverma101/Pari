# Official-anchor converter provenance (#66)

Pari delegates the final SWORDS, JFLEG, and SemanticQA LCC metrics to pinned
official evaluators. The step between a model run and those evaluators is not
official code, and it is score-affecting. That step is the **conversion layer**, and
this document is the contract that makes it auditable.

The goal is one immutable chain per official score:

```
raw model result
  -> converter protocol + converter source + conversion config
  -> converted artifact (hash)
  -> pinned official evaluator + official data
  -> evaluator interpreter and packages
  -> archived metric
```

No promotion-ready official result may rely on a self-described policy string, and
`promotionProvenanceReady: true` in a conversion manifest is never accepted as proof
on its own.

## Where the contract lives

`english_core_converter_provenance.py` is the single definition used by all three
converters and all three official-evaluator wrappers, so the two sides cannot drift.

Each conversion manifest records a `converterProvenance` block with three
independent identities:

| Field | Question it answers | Failure it catches |
| --- | --- | --- |
| `protocol.id` + `protocol.version` | Which registered conversion policy ran? | A parser or normalizer that has no registered contract |
| `protocol.contractSha256` | Does the policy still match its frozen description? | A silent edit to a regex, marker, or normalization rule |
| `converterSource.sha256` | Which exact converter bytes ran? | A one-byte edit to the converter |
| `conversionConfig` | Which conversion-affecting values were in effect? | `--max-candidates` / `--lemmatized` drift |
| `benchmarkGit.commit` / `benchmarkGit.tree` | Which Pari benchmark revision defined that policy? | Evidence that cannot be tied to a reconstructable tree |
| `identity` | Which artifact came out of this exact chain? | Manifest tampering, and mixing two chains in one headline |

`verify_converter_provenance()` re-hashes the converter actually on disk, recomputes
the contract hash and the conversion identity, and returns error codes. All three
official-evaluator wrappers call it and refuse to score on a non-empty result.

## Registered conversion protocols

These are Pari contracts, not official benchmark semantics. Changing one is a
protocol revision.

| Benchmark | Protocol id | Frozen behavior |
| --- | --- | --- |
| SWORDS | `pari-swords-candidate-parser` v1 | split on lines; strip list prefixes and backtick/quote/space characters; drop meta prose (`here are`, `substitutes:`, `alternatives:`, `the best`); casefold first-occurrence-wins dedup; truncate to `maxCandidates`; assign descending rank scores that encode model order only |
| JFLEG | `pari-jfleg-one-line-normalizer` v1 | `" ".join(str(text or "").strip().split())` per hypothesis, emitting exactly one line per prompt task |
| SemanticQA LCC | `pari-semanticqa-lcc-postprocess` v1 | whitespace normalization, then `if "is: "` / `elif "Output:"`, taking the suffix after the **last** occurrence and stripping only that suffix |

A future parser improvement must add a new protocol version rather than mutate an
existing one. That produces a different `identity`, and
`compare_conversion_identities()` refuses to pool the old and new artifacts into one
headline comparison, so every compared candidate must be replayed from preserved raw
outputs first.

## Conversion audit trails

The issue requires the conversion itself to be inspectable, not just bound.

- **SWORDS.** `parse_candidates_with_diagnostics()` returns the retained candidates
  plus per-call counters: raw lines, empty lines dropped, list prefixes stripped,
  quote/bullet stripping changes, filtered meta-prose counts *by reason*, and
  casefold-dedup count. `convert-swords-english-core-output.py
  --per-target-diagnostics FILE` archives that trail per target, together with
  retained order, whether truncation dropped candidates at `maxCandidates`, and the
  case/target coverage counters in the manifest's `coverage` block.
- **JFLEG.** The manifest keeps `rawHypotheses` (raw and normalized text per task,
  with `changedByNormalization`) and reports `normalizedChangedRows`, so it is
  visible exactly which rows the normalizer rewrote.
- **SemanticQA LCC.** The manifest reports `postprocessChangedOutputs`,
  `isMarkerRows`, and `outputMarkerRows` alongside the postprocessor provenance and
  full coverage block.

All three manifests also record `conversionStatus` and `terminalStatus`.

## SemanticQA postprocess fidelity

The local implementation is a mirror, not the proof. The verified official source is
`jacklanda/SemanticQA` at commit `56c82a587f4a6cef609255cd10af372d8c76600a`, file
`semantic_qa/data_utils.py` (sha256
`52ad7f1642484972cd44a96546e3aa339179db4c5a15eceec1ed66b71c8ce09a`), lines
1163-1173:

```python
s = " ".join(s.split())
if task == "collocation-categorization":
    if "is: " in s:
        s = s.split("is: ")[-1].strip()
    elif "Output:" in s:
        s = s.split("Output:")[-1].strip()
    return s
```

Note the `elif`: a text containing **both** markers takes the `is: ` branch, and
`split(...)[-1]` takes the last occurrence. Matching is case-sensitive, no quote or
bullet stripping happens, and `eval.py`'s `lcc` branch compares prediction and label
with plain `==`.

Because prose is not executable provenance, `convert-semanticqa-lcc-official-output.py`
**imports the pinned official postprocessor** from a verified checkout supplied via
`--semanticqa-checkout`. That path refuses anything that is not a clean checkout of
the pinned commit, then records `postprocessor.kind = "official-pinned-import"` with
the checkout path, commit, and module hash. Without `--semanticqa-checkout` the
converter still produces exploratory artifacts, but the manifest records
`postprocessor.kind = "local-mirror"` and is *not* promotion-ready.

`run-semanticqa-lcc-official-eval.py --promotion` rejects any conversion whose
postprocessor is not an official pinned import whose commit matches the evaluator
checkout. The `predictionPolicy` string is retained for readability and explicitly
labelled documentation only.

Adversarial fixtures for repeated `is: ` / `Output:` markers, mixed whitespace,
newlines, casing, empty output, Unicode whitespace, and strings containing both
markers live in `test_official_converter_provenance.py`.

## Evaluator interpreter and environment

All three official wrappers accept `--python` and must describe the interpreter that
actually ran the official evaluator.

SWORDS and JFLEG already probed the selected interpreter. SemanticQA previously read
`platform.python_version()` and `importlib.metadata` from the **wrapper** process,
which misdescribed the environment whenever `--python` pointed elsewhere. That is
fixed: `run-semanticqa-lcc-official-eval.py` now resolves `--python` to an executable
path, spawns it with a probe script, and records the resolved executable, Python
version and implementation, platform, machine, ABI flags, and the versions of NumPy,
scikit-learn, `evaluate`, nltk, pandas, sacrebleu, and datasets **as seen by that
interpreter**. The probe runs with the evaluator checkout on `PYTHONPATH` so imported
packages are the ones the official evaluator will see.

If the probe fails, the wrapper exits rather than falling back to wrapper Python.

## Fail-closed cases

`test_official_converter_provenance.py` runs on CPU with no network and covers the
issue's required failures:

1. converter source changes by one byte while the manifest claims ready;
2. conversion config changes without a new protocol identity;
3. a SWORDS parser change alters retained order, so old and new artifacts cannot enter
   one headline comparison;
4. the local postprocess mirrors the pinned official function on the edge taxonomy;
5. the SemanticQA `--python` probe reports the selected interpreter, and a bogus
   executable surfaces an error instead of silently using wrapper Python;
6. a tampered manifest fails identity verification;
7. a wrong-commit or dirty official checkout is refused before any postprocess import;
8. the exact frozen chain verifies and yields a reproducible conversion identity;
9. a replay under a new protocol identity is a clearly separate evidence identity.

## Historical evidence

Official-anchor artifacts produced before this contract lack converter-code identity.
They remain valid as exploratory/reference evidence but are **not promotion-comparable**
until the converter chain can be reconstructed from the exact historical benchmark
commit, or the candidates are replayed from preserved raw outputs under the new frozen
protocol. A conversion run whose benchmark Git identity cannot be resolved records
`benchmarkGit.available = false` and fails promotion verification with
`benchmark_git_identity_unavailable`; this is deliberate. It is better to have no
promotion-ready score than one whose converter identity cannot be proven.
