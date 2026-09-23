"""Convert an English Core JFLEG run to the hypothesis file expected by JFLEG.

Usage:
    python convert-jfleg-english-core-output.py jfleg-dev-prompts.jsonl model-result.json hypothesis.txt \
      --prompt-manifest jfleg-dev-prompts.jsonl.manifest.json

Then, from the pinned official JFLEG checkout:
    python ./eval/gleu.py -r ./dev/dev.ref[0-3] -s ./dev/dev.src --hyp /path/to/hypothesis.txt

The official script reports the benchmark GLEU result and uncertainty; Pari does
not replace it with a custom fluency metric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

UNPINNED = {"", "unknown", "unrecorded_not_pinned", "main", "master", "latest", "default"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def known_revision(value: object) -> bool:
    return str(value or "").strip().lower() not in UNPINNED


def normalize_one_line(text: str) -> str:
    # JFLEG expects one hypothesis per source line. Preserve sentence content while
    # collapsing model formatting/newlines that are not part of the benchmark I/O.
    return " ".join(str(text or "").strip().split())


def infer_prompt_manifest(prompt_path: Path) -> Path | None:
    candidate = prompt_path.with_suffix(prompt_path.suffix + ".manifest.json")
    return candidate if candidate.is_file() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_jsonl")
    ap.add_argument("model_result")
    ap.add_argument("out_hypothesis")
    ap.add_argument("--prompt-manifest", default=None, help="Manifest emitted by build-jfleg-english-core-prompts.py; inferred from prompt_jsonl when available")
    ap.add_argument("--require-promotion-provenance", action="store_true", help="Fail unless source/references/prompt/run/evaluator provenance is complete and every task has an output record")
    args = ap.parse_args()

    prompt_path = Path(args.prompt_jsonl).resolve()
    run_path = Path(args.model_result).resolve()
    out_path = Path(args.out_hypothesis).resolve()
    if not prompt_path.is_file():
        raise SystemExit(f"Missing JFLEG prompt file: {prompt_path}")
    if not run_path.is_file():
        raise SystemExit(f"Missing model result: {run_path}")

    tasks = [json.loads(line) for line in prompt_path.read_text().splitlines() if line.strip()]
    if not tasks:
        raise SystemExit("JFLEG prompt file contains no tasks")
    task_ids = [task.get("id") for task in tasks]
    if any(not task_id for task_id in task_ids):
        raise SystemExit("JFLEG prompt file contains a task without an ID")
    if len(task_ids) != len(set(task_ids)):
        raise SystemExit("JFLEG prompt file contains duplicate task IDs")

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

    manifest_path = Path(args.prompt_manifest).resolve() if args.prompt_manifest else infer_prompt_manifest(prompt_path)
    prompt_manifest = None
    provenance_errors: list[str] = []
    prompt_hash = sha256(prompt_path)
    if manifest_path and manifest_path.is_file():
        prompt_manifest = json.loads(manifest_path.read_text())
        if prompt_manifest.get("promptFileSha256") != prompt_hash:
            provenance_errors.append("prompt_manifest_prompt_hash_mismatch")
        if prompt_manifest.get("promptFileSha256") != run.get("taskFileSha256"):
            provenance_errors.append("prompt_hash_does_not_match_run_task_hash")
        if int(prompt_manifest.get("cases", -1)) != len(tasks):
            provenance_errors.append("prompt_manifest_case_count_mismatch")
        if int(prompt_manifest.get("sourceLines", -1)) != len(tasks):
            provenance_errors.append("prompt_manifest_source_line_count_mismatch")
        references = prompt_manifest.get("references") or []
        if len(references) != 4:
            provenance_errors.append("jfleg_four_reference_bundle_not_pinned")
        else:
            for index, ref in enumerate(references):
                if not ref.get("sha256") or not ref.get("path"):
                    provenance_errors.append(f"jfleg_reference_{index}_missing_hash_or_path")
                if int(ref.get("lines", -1)) != len(tasks):
                    provenance_errors.append(f"jfleg_reference_{index}_line_count_mismatch")
        if not known_revision(prompt_manifest.get("officialRepositoryRevision")):
            provenance_errors.append("official_jfleg_repository_revision_not_pinned")
    else:
        provenance_errors.append("missing_prompt_manifest")

    if run.get("taskCount") != len(tasks):
        provenance_errors.append("run_task_count_does_not_match_jfleg_cases")

    task_id_set = set(task_ids)
    output_id_set = set(output_ids)
    missing = sorted(task_id_set - output_id_set)
    extra = sorted(output_id_set - task_id_set)
    if missing:
        provenance_errors.append("run_missing_jfleg_outputs")
    if extra:
        provenance_errors.append("run_contains_non_jfleg_output_ids")

    if args.require_promotion_provenance and provenance_errors:
        raise SystemExit("JFLEG promotion provenance failed:\n- " + "\n- ".join(provenance_errors))

    hypotheses = []
    empty = []
    for task in tasks:
        task_id = task["id"]
        if task_id not in outputs:
            hypotheses.append("")
            continue
        text = normalize_one_line(outputs[task_id])
        if not text:
            empty.append(task_id)
        hypotheses.append(text)

    out_path.write_text("\n".join(hypotheses) + "\n")
    conversion_manifest = out_path.with_suffix(out_path.suffix + ".manifest.json")
    conversion_manifest.write_text(json.dumps({
        "version": 2,
        "promptFile": str(prompt_path),
        "promptFileSha256": prompt_hash,
        "promptManifest": str(manifest_path) if manifest_path else None,
        "promptManifestSha256": sha256(manifest_path) if manifest_path and manifest_path.is_file() else None,
        "sourceFile": prompt_manifest.get("sourceFile") if prompt_manifest else None,
        "sourceSha256": prompt_manifest.get("sourceSha256") if prompt_manifest else None,
        "references": prompt_manifest.get("references") if prompt_manifest else None,
        "officialJflegRepositoryRevision": prompt_manifest.get("officialRepositoryRevision") if prompt_manifest else None,
        "modelResultFile": str(run_path),
        "modelResultSha256": sha256(run_path),
        "runTaskFileSha256": run.get("taskFileSha256"),
        "runTaskCount": run.get("taskCount"),
        "outHypothesis": str(out_path),
        "outHypothesisSha256": sha256(out_path),
        "cases": len(tasks),
        "missingOutputs": len(missing),
        "extraOutputs": len(extra),
        "emptyOutputs": len(empty),
        "promotionProvenanceErrors": provenance_errors,
        "promotionProvenanceReady": not provenance_errors,
        "officialEvaluatorRequired": True,
        "officialRepository": "https://github.com/keisks/jfleg",
        "officialMetric": "GLEU using eval/gleu.py with the four pinned references",
        "researchReference": "https://aclanthology.org/E17-2037/",
        "notes": [
            "Missing model-result records are provenance/completeness errors; a present but empty model output is retained as model behavior and should score accordingly.",
            "Only whitespace/newline formatting is normalized to JFLEG's one-hypothesis-per-line interface; Pari does not otherwise rewrite model hypotheses before official scoring.",
            "For promotion-quality evidence, archive the official GLEU output produced from this exact hypothesis file, the pinned source, all four pinned references, and the pinned repository revision."
        ]
    }, indent=2) + "\n")

    print(json.dumps({
        "cases": len(tasks),
        "hypotheses": len(hypotheses),
        "missingOutputs": len(missing),
        "extraOutputs": len(extra),
        "emptyOutputs": len(empty),
        "promotionProvenanceReady": not provenance_errors,
        "promotionProvenanceErrors": provenance_errors,
        "out": str(out_path),
        "manifest": str(conversion_manifest),
        "nextStep": "Run the official pinned JFLEG eval/gleu.py with the four references recorded in the prompt manifest."
    }, indent=2))


if __name__ == "__main__":
    main()
