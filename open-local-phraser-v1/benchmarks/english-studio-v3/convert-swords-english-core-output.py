"""Convert an English Core model result into official SWORDS `.lsr.json` format.

Usage:
    python convert-swords-english-core-output.py \
        swords-v1.1_test.json.gz model-result.json model.swords.lsr.json \
        --prompt-manifest swords-prompts.jsonl.manifest.json

Then evaluate with the official SWORDS repository at the revision recorded by the
prompt manifest, for example:
    python -m swords.cli eval swords-v1.1_test \
        --result_json_fp model.swords.lsr.json \
        --output_metrics_json_fp model.swords.metrics.json

Prefer the official repository's documented Docker/CLI environment for numbers
that will be compared to published SWORDS results. This converter never replaces
the official evaluator.

Issue #66: the candidate parser below is score-affecting Pari code, not official
SWORDS code. It is therefore frozen as an explicit, versioned conversion protocol
(`pari-swords-candidate-parser` v1, registered in
english_core_converter_provenance.py) and the manifest binds the protocol contract
hash, this script's SHA-256, the full conversion config, and the Pari benchmark
commit/tree that defined the policy. Per-result conversion diagnostics are emitted
so a parser change is auditable rather than silent.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_core_converter_provenance import (  # noqa: E402
    SWORDS_PROTOCOL_ID,
    build_converter_provenance,
    registered_protocol,
)

GIT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
PROTOCOL_VERSION = 1

#: Markers whose presence/absence is scored, so the contract stays auditable.
LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*•]+|\d+[.)]|[A-Za-z][.)])\s*")
QUOTE_CHARS = "`\"' "
META_PREFIXES = ("here are", "substitutes:", "alternatives:", "the best")


def read_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def immutable_git_revision(value: object) -> bool:
    return bool(GIT_COMMIT_RE.fullmatch(str(value or "").strip()))


def parse_candidates_with_diagnostics(text: str) -> tuple[list[str], dict]:
    """Frozen `pari-swords-candidate-parser` v1 plus the audit trail it applied.

    Returns the retained candidates in model order together with per-call counters
    for the issue's required diagnostics: raw line count, empty lines dropped,
    quote/bullet stripping changes, filtered meta-prose lines with reasons,
    casefold-duplicate drops, and the resulting retained list.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    raw_lines: list[str] = []
    empty_lines = 0
    list_prefix_stripped = 0
    quote_strip_changed = 0
    empty_after_strip = 0
    filtered_meta: Counter = Counter()
    deduplicated = 0

    for raw in str(text or "").splitlines():
        raw_lines.append(raw)
        line = raw.strip()
        if not line:
            empty_lines += 1
            continue
        stripped = LIST_PREFIX_RE.sub("", line).strip()
        if stripped != line:
            list_prefix_stripped += 1
        line = stripped
        unquoted = line.strip(QUOTE_CHARS)
        if unquoted != line:
            quote_strip_changed += 1
        line = unquoted
        if not line:
            empty_after_strip += 1
            continue
        # Reject obvious meta prose rather than turning an explanation into a substitute.
        lower = line.lower()
        meta_hit = next((prefix for prefix in META_PREFIXES if lower.startswith(prefix)), None)
        if meta_hit is not None:
            filtered_meta[meta_hit] += 1
            continue
        key = line.casefold()
        if key in seen:
            deduplicated += 1
            continue
        seen.add(key)
        candidates.append(line)

    diagnostics = {
        "rawCandidateLines": raw_lines,
        "rawLineCount": len(raw_lines),
        "emptyLinesDropped": empty_lines,
        "listPrefixStripped": list_prefix_stripped,
        "quoteOrBulletStripChangedText": quote_strip_changed,
        "emptyAfterStripping": empty_after_strip,
        "filteredMetaReasons": dict(sorted(filtered_meta.items())),
        "filteredMetaCount": int(sum(filtered_meta.values())),
        "normalizedDeduplicatedCount": deduplicated,
        "retainedCandidates": list(candidates),
    }
    return candidates, diagnostics


def parse_candidates(text: str) -> list[str]:
    """Frozen `pari-swords-candidate-parser` v1 (candidates only, model order)."""
    return parse_candidates_with_diagnostics(text)[0]
def infer_prompt_manifest(run: dict) -> Path | None:
    task_file = run.get("taskFile")
    if not task_file:
        return None
    task_path = Path(str(task_file))
    candidate = task_path.with_suffix(task_path.suffix + ".manifest.json")
    return candidate if candidate.is_file() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("swords_json")
    ap.add_argument("model_result")
    ap.add_argument("out_lsr_json")
    ap.add_argument("--prompt-manifest", default=None, help="Manifest emitted by build-swords-english-core-prompts.py; inferred from run.taskFile when possible")
    ap.add_argument("--lemmatized", action="store_true", help="Set only if model outputs lemmas rather than context-fitting wordforms")
    ap.add_argument("--max-candidates", type=int, default=40)
    ap.add_argument("--require-promotion-provenance", action="store_true", help="Fail unless benchmark/prompt/run/evaluator provenance is fully cross-checked and every target has a run output record")
    ap.add_argument("--per-target-diagnostics", type=Path, default=None, help="Optional path for the full per-target conversion audit (raw lines, retained order, filter reasons, truncation)")
    args = ap.parse_args()

    if args.max_candidates < 1:
        raise SystemExit("--max-candidates must be >= 1")

    benchmark_path = Path(args.swords_json).resolve()
    run_path = Path(args.model_result).resolve()
    if not benchmark_path.is_file():
        raise SystemExit(f"Missing SWORDS benchmark file: {benchmark_path}")
    if not run_path.is_file():
        raise SystemExit(f"Missing model result: {run_path}")

    benchmark = read_json(benchmark_path)
    targets = benchmark.get("targets", {})
    if not targets:
        raise SystemExit("SWORDS benchmark contains no targets")
    benchmark_hash = sha256(benchmark_path)

    run = json.loads(run_path.read_text())
    run_outputs = run.get("outputs", [])
    if not isinstance(run_outputs, list):
        raise SystemExit("model result outputs is not an array")
    output_ids = [row.get("id") for row in run_outputs if isinstance(row, dict)]
    if len(output_ids) != len(run_outputs):
        raise SystemExit("model result contains a non-object output row")
    if len(output_ids) != len(set(output_ids)):
        raise SystemExit("model result contains duplicate output IDs")
    outputs = {row["id"]: row.get("output", "") for row in run_outputs}

    manifest_path = Path(args.prompt_manifest).resolve() if args.prompt_manifest else infer_prompt_manifest(run)
    prompt_manifest = None
    provenance_errors: list[str] = []
    dataset_id = None
    if manifest_path and manifest_path.is_file():
        prompt_manifest = json.loads(manifest_path.read_text())
        if prompt_manifest.get("sourceSha256") != benchmark_hash:
            provenance_errors.append("prompt_manifest_source_hash_mismatch")
        run_task_hash = run.get("taskFileSha256")
        if prompt_manifest.get("promptFileSha256") != run_task_hash:
            provenance_errors.append("prompt_manifest_prompt_hash_does_not_match_run_task_hash")
        if int(prompt_manifest.get("targets", -1)) != len(targets):
            provenance_errors.append("prompt_manifest_target_count_mismatch")
        dataset_id = prompt_manifest.get("officialDatasetId")
        if not dataset_id:
            provenance_errors.append("official_swords_dataset_id_missing")
        revision = prompt_manifest.get("officialRepositoryRevision")
        if not immutable_git_revision(revision):
            provenance_errors.append("official_swords_repository_revision_not_full_commit")
        if prompt_manifest.get("promotionReadySourceProvenance") is not True:
            provenance_errors.append("prompt_manifest_not_promotion_ready")
    else:
        provenance_errors.append("missing_prompt_manifest")

    run_task_count = run.get("taskCount")
    if run_task_count != len(targets):
        provenance_errors.append("run_task_count_does_not_match_swords_target_count")

    target_ids = set(targets.keys())
    output_id_set = set(output_ids)
    missing = sorted(target_ids - output_id_set)
    extra = sorted(output_id_set - target_ids)
    if extra:
        provenance_errors.append("run_contains_non_swords_output_ids")
    if missing:
        provenance_errors.append("run_missing_swords_target_outputs")

    if args.require_promotion_provenance and provenance_errors:
        raise SystemExit("SWORDS promotion provenance failed:\n- " + "\n- ".join(provenance_errors))

    converted: dict[str, list[list[object]]] = {}
    empty = []
    truncated = []
    per_target: dict[str, dict] = {}
    for target_id in targets:
        if target_id not in outputs:
            converted[target_id] = []
            per_target[target_id] = {
                "rawCandidateLines": [],
                "retainedCandidates": [],
                "retainedOrder": [],
                "missingOutput": True,
                "filteredMetaReasons": {},
                "normalizedDeduplicatedCount": 0,
                "truncatedAtMaxCandidates": False,
                "truncationDropped": 0,
                "quoteOrBulletStripChangedText": 0,
            }
            continue
        parsed, diagnostics = parse_candidates_with_diagnostics(outputs[target_id])
        dropped_by_truncation = max(0, len(parsed) - args.max_candidates)
        candidates = parsed[: args.max_candidates]
        if not candidates:
            empty.append(target_id)
        if dropped_by_truncation:
            truncated.append(target_id)
        n = len(candidates)
        # The official SWORDS format accepts ranked candidate/score pairs. Scores
        # encode only the model's rank order; candidate quality is determined by
        # the official SWORDS evaluator after its documented preprocessing.
        converted[target_id] = [[candidate, float(n - i)] for i, candidate in enumerate(candidates)]
        per_target[target_id] = {
            "rawCandidateLines": diagnostics["rawCandidateLines"],
            "retainedCandidates": diagnostics["retainedCandidates"],
            "retainedOrder": list(candidates),
            "missingOutput": False,
            "filteredMetaReasons": diagnostics["filteredMetaReasons"],
            "filteredMetaCount": diagnostics["filteredMetaCount"],
            "normalizedDeduplicatedCount": diagnostics["normalizedDeduplicatedCount"],
            "truncatedAtMaxCandidates": bool(dropped_by_truncation),
            "truncationDropped": dropped_by_truncation,
            "quoteOrBulletStripChangedText": diagnostics["quoteOrBulletStripChangedText"],
        }

    result = {
        "substitutes_lemmatized": bool(args.lemmatized),
        "substitutes": converted,
    }
    out_path = Path(args.out_lsr_json).resolve()
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    coverage = {
        "targets": len(targets),
        "convertedTargets": len(targets) - len(missing),
        "missingOutputs": len(missing),
        "extraOutputs": len(extra),
        "emptyCandidateOutputs": len(empty),
        "truncatedTargets": len(truncated),
        "retainedCandidateTotal": sum(len(v["retainedOrder"]) for v in per_target.values()),
    }
    conversion_config = {
        "maxCandidates": int(args.max_candidates),
        "substitutesLemmatized": bool(args.lemmatized),
    }
    converter_provenance = build_converter_provenance(
        benchmark="swords",
        protocol_id=SWORDS_PROTOCOL_ID,
        protocol_version=PROTOCOL_VERSION,
        converter_path=Path(__file__),
        conversion_config=conversion_config,
    )
    if not converter_provenance["benchmarkGit"]["available"]:
        provenance_errors.append("benchmark_git_identity_unavailable")

    if args.per_target_diagnostics is not None:
        diag_path = Path(args.per_target_diagnostics)
        diag_path.parent.mkdir(parents=True, exist_ok=True)
        diag_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "benchmark": "SWORDS conversion diagnostics",
                    "converterIdentity": converter_provenance["identity"],
                    "maxCandidates": int(args.max_candidates),
                    "substitutesLemmatized": bool(args.lemmatized),
                    "targets": per_target,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    conversion_manifest = out_path.with_suffix(out_path.suffix + ".manifest.json")
    conversion_manifest.write_text(json.dumps({
        "version": 5,
        "benchmarkFile": str(benchmark_path),
        "benchmarkSha256": benchmark_hash,
        "officialDatasetId": dataset_id,
        "modelResultFile": str(run_path),
        "modelResultSha256": sha256(run_path),
        "runTaskFileSha256": run.get("taskFileSha256"),
        "runTaskCount": run_task_count,
        "promptManifest": str(manifest_path) if manifest_path else None,
        "promptManifestSha256": sha256(manifest_path) if manifest_path and manifest_path.is_file() else None,
        "officialSwordsRepositoryRevision": prompt_manifest.get("officialRepositoryRevision") if prompt_manifest else None,
        "outLsrFile": str(out_path),
        "outLsrSha256": sha256(out_path),
        "coverage": coverage,
        "targets": len(targets),
        "missingOutputs": len(missing),
        "extraOutputs": len(extra),
        "emptyCandidateOutputs": len(empty),
        "truncatedTargets": len(truncated),
        "maxCandidates": args.max_candidates,
        "substitutesLemmatized": bool(args.lemmatized),
        "conversionStatus": "completed" if not provenance_errors else "completed_with_provenance_errors",
        "terminalStatus": "completed",
        "converterProvenance": converter_provenance,
        "conversionContract": registered_protocol("swords", SWORDS_PROTOCOL_ID, PROTOCOL_VERSION)["contract"],
        "promotionProvenanceErrors": provenance_errors,
        "promotionProvenanceReady": not provenance_errors,
        "officialEvaluatorRequired": True,
        "officialRepository": "https://github.com/p-lambda/swords",
        "researchReference": "https://aclanthology.org/2021.naacl-main.345/",
        "notes": [
            "Missing run records and genuinely empty model candidate lists are distinct: missing records are a provenance/completeness error, while an empty candidate list is a model behavior that the official evaluator may score poorly.",
            "Pari rank scores preserve model ordering only; official SWORDS preprocessing/evaluation determines lexical quality.",
            "parse_candidates() is Pari-owned and score-affecting; it is frozen as conversion protocol pari-swords-candidate-parser v1. Changing it requires a new protocol identity and a replay of every compared candidate from preserved raw outputs.",
            "Promotion provenance requires the official SWORDS repository's full 40-hex commit SHA and an official dataset ID bound to the prompt source.",
            "The official evaluator runner cross-checks this dataset ID and benchmark bytes against the pinned checkout before scoring.",
            "Pass --per-target-diagnostics to archive raw candidate lines, retained order, meta-prose filter reasons, dedup counts, and truncation for every target."
        ]
    }, indent=2) + "\n")

    print(json.dumps({
        "converterIdentity": converter_provenance["identity"],
        "converterProtocol": f"{SWORDS_PROTOCOL_ID}@{PROTOCOL_VERSION}",
        "targets": len(targets),
        "officialDatasetId": dataset_id,
        "convertedOutputRecords": len(targets) - len(missing),
        "missingOutputs": len(missing),
        "extraOutputs": len(extra),
        "emptyCandidateOutputs": len(empty),
        "truncatedTargets": len(truncated),
        "promotionProvenanceReady": not provenance_errors,
        "promotionProvenanceErrors": provenance_errors,
        "out": str(out_path),
        "manifest": str(conversion_manifest),
        "nextStep": "Run run-swords-official-eval.py against the pinned official checkout; it verifies dataset identity, executes the official evaluator, and archives provenance."
    }, indent=2))


if __name__ == "__main__":
    main()
