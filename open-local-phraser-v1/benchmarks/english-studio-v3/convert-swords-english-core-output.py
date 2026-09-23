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
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

UNPINNED = {"", "unknown", "unrecorded_not_pinned", "main", "master", "latest", "default"}


def read_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def known_revision(value: object) -> bool:
    return str(value or "").strip().lower() not in UNPINNED


def parse_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*•]+|\d+[.)]|[A-Za-z][.)])\s*", "", line).strip()
        line = line.strip("`\"' ")
        if not line:
            continue
        # Reject obvious meta prose rather than turning an explanation into a substitute.
        lower = line.lower()
        if lower.startswith(("here are", "substitutes:", "alternatives:", "the best")):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(line)
    return candidates


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
    if manifest_path and manifest_path.is_file():
        prompt_manifest = json.loads(manifest_path.read_text())
        if prompt_manifest.get("sourceSha256") != benchmark_hash:
            provenance_errors.append("prompt_manifest_source_hash_mismatch")
        run_task_hash = run.get("taskFileSha256")
        if prompt_manifest.get("promptFileSha256") != run_task_hash:
            provenance_errors.append("prompt_manifest_prompt_hash_does_not_match_run_task_hash")
        if int(prompt_manifest.get("targets", -1)) != len(targets):
            provenance_errors.append("prompt_manifest_target_count_mismatch")
        if not known_revision(prompt_manifest.get("officialRepositoryRevision")):
            provenance_errors.append("official_swords_repository_revision_not_pinned")
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
    for target_id in targets:
        if target_id not in outputs:
            converted[target_id] = []
            continue
        candidates = parse_candidates(outputs[target_id])[: args.max_candidates]
        if not candidates:
            empty.append(target_id)
        n = len(candidates)
        # The official SWORDS format accepts ranked candidate/score pairs. Scores
        # encode only the model's rank order; candidate quality is determined by
        # the official SWORDS evaluator after its documented preprocessing.
        converted[target_id] = [[candidate, float(n - i)] for i, candidate in enumerate(candidates)]

    result = {
        "substitutes_lemmatized": bool(args.lemmatized),
        "substitutes": converted,
    }
    out_path = Path(args.out_lsr_json).resolve()
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    conversion_manifest = out_path.with_suffix(out_path.suffix + ".manifest.json")
    conversion_manifest.write_text(json.dumps({
        "version": 2,
        "benchmarkFile": str(benchmark_path),
        "benchmarkSha256": benchmark_hash,
        "modelResultFile": str(run_path),
        "modelResultSha256": sha256(run_path),
        "runTaskFileSha256": run.get("taskFileSha256"),
        "runTaskCount": run_task_count,
        "promptManifest": str(manifest_path) if manifest_path else None,
        "promptManifestSha256": sha256(manifest_path) if manifest_path and manifest_path.is_file() else None,
        "officialSwordsRepositoryRevision": prompt_manifest.get("officialRepositoryRevision") if prompt_manifest else None,
        "outLsrFile": str(out_path),
        "outLsrSha256": sha256(out_path),
        "targets": len(targets),
        "missingOutputs": len(missing),
        "extraOutputs": len(extra),
        "emptyCandidateOutputs": len(empty),
        "maxCandidates": args.max_candidates,
        "substitutesLemmatized": bool(args.lemmatized),
        "promotionProvenanceErrors": provenance_errors,
        "promotionProvenanceReady": not provenance_errors,
        "officialEvaluatorRequired": True,
        "officialRepository": "https://github.com/p-lambda/swords",
        "researchReference": "https://aclanthology.org/2021.naacl-main.345/",
        "notes": [
            "Missing run records and genuinely empty model candidate lists are distinct: missing records are a provenance/completeness error, while an empty candidate list is a model behavior that the official evaluator may score poorly.",
            "Pari rank scores preserve model ordering only; official SWORDS preprocessing/evaluation determines lexical quality.",
            "For promotion-quality evidence, evaluate this exact .lsr.json with the official repository at officialSwordsRepositoryRevision and archive the evaluator output as a separate artifact."
        ]
    }, indent=2) + "\n")

    print(json.dumps({
        "targets": len(targets),
        "convertedOutputRecords": len(targets) - len(missing),
        "missingOutputs": len(missing),
        "extraOutputs": len(extra),
        "emptyCandidateOutputs": len(empty),
        "promotionProvenanceReady": not provenance_errors,
        "promotionProvenanceErrors": provenance_errors,
        "out": str(out_path),
        "manifest": str(conversion_manifest),
        "nextStep": "Run the official SWORDS evaluator at the pinned revision; do not substitute a Pari-invented lexical score for the official metrics."
    }, indent=2))


if __name__ == "__main__":
    main()
