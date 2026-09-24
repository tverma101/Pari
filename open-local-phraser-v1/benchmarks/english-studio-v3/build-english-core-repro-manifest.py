"""Build a frozen reproducibility manifest for an English Core evaluation.

The manifest is evidence bookkeeping, not a quality metric. It records exact
artifacts and identifies missing provenance that blocks promotion-quality claims.

Example:
    python build-english-core-repro-manifest.py \
      --run shadow-result.json \
      --score shadow-score.json \
      --artifact shadow-stats=shadow-stats.json \
      --artifact prompt-score=prompt-score.json \
      --artifact order-score=order-score.json \
      --public-manifest public-fast=english-core-public-fast.manifest.json \
      --official-evidence swords=swords-official-result.json \
      --official-evidence jfleg=jfleg-gleu-result.json \
      --official-evidence semanticqa=semanticqa-lcc-official-score.json \
      --output repro-manifest.json \
      --require-promotion-ready

Use repeated --artifact LABEL=PATH for generic frozen diagnostics whose bytes
should be preserved but whose semantics are not validated here.
Use repeated --public-manifest LABEL=PATH for Hugging Face-derived builder
manifests whose revisions/fingerprints must be immutable for promotion use.
Use repeated --official-evidence LABEL=PATH for supported official benchmark
result JSONs. Those files are semantically inspected rather than merely hashed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MUTABLE_REVISIONS = {"", "unknown", "mutable_default_not_pinned", "main", "master", "latest", "default"}
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SWORDS_CORE_METRICS = (
    "lenient_a_f@10",
    "lenient_c_f@10",
    "strict_a_f@10",
    "strict_c_f@10",
    "strict_c_p@1",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_outputs_sha256(outputs: list[dict]) -> str:
    payload = json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256_bytes(payload)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def git_value(args: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=HERE, text=True, stderr=subprocess.DEVNULL
        ).strip() or None
    except Exception:
        return None


def parse_labeled_file(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("value must be LABEL=PATH")
    label, raw_path = value.split("=", 1)
    label = label.strip()
    if not label:
        raise argparse.ArgumentTypeError("label cannot be empty")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"not a file: {path}")
    return label, path


def is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def is_git_sha(value: object) -> bool:
    return isinstance(value, str) and bool(GIT_SHA_RE.fullmatch(value))


def known(value) -> bool:
    return str(value or "").strip().lower() not in MUTABLE_REVISIONS


def fingerprint_complete(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value) and all(fingerprint_complete(v) for v in value.values())
    return False


def public_manifest_blockers(label: str, data: dict) -> list[str]:
    blockers: list[str] = []
    if not data.get("datasetsLibraryVersion"):
        blockers.append(f"{label}:missing_datasets_library_version")
    sources = data.get("sources") or {}
    if not sources:
        blockers.append(f"{label}:missing_sources")
    fingerprints = data.get("resolvedDatasetFingerprints") or {}
    for source_name, source in sorted(sources.items()):
        revision = source.get("requestedRevision")
        if not known(revision):
            blockers.append(f"{label}:{source_name}:unpinned_source_revision")
        if not fingerprint_complete(fingerprints.get(source_name)):
            blockers.append(f"{label}:{source_name}:missing_dataset_fingerprint")
    return blockers


def unique_metric_provenance(score: dict | None) -> list[dict]:
    if not score:
        return []
    seen = set()
    result = []
    for row in score.get("detail", []):
        provenance = row.get("metricProvenance")
        if not isinstance(provenance, dict):
            continue
        canonical = json.dumps(provenance, sort_keys=True, ensure_ascii=False)
        if canonical in seen:
            continue
        seen.add(canonical)
        result.append(provenance)
    return result


def looks_like_official_evidence(data: dict) -> bool:
    benchmark = str(data.get("benchmark") or "").lower()
    purpose = str(data.get("purpose") or "").lower()
    return any(
        (
            "semanticqa lcc" in benchmark,
            "swordsrepositoryrevision" in {str(k).lower() for k in data},
            "jflegrepositoryrevision" in {str(k).lower() for k in data},
            "swords' official evaluator" in purpose,
            "jfleg's official gleu evaluator" in purpose,
        )
    )


def detect_official_evidence_kind(data: dict) -> str | None:
    benchmark = str(data.get("benchmark") or "").lower()
    if "semanticqa lcc official" in benchmark:
        return "semanticqa_lcc"
    if "swordsRepositoryRevision" in data or "swordsRepository" in data:
        return "swords"
    if "jflegRepositoryRevision" in data or "jflegRepository" in data:
        return "jfleg"
    return None


def official_evidence_blockers(label: str, data: dict) -> tuple[str | None, list[str], dict]:
    kind = detect_official_evidence_kind(data)
    blockers: list[str] = []
    summary: dict = {}

    if kind is None:
        return None, [f"{label}:official_evidence_unrecognized"], summary

    if kind == "semanticqa_lcc":
        commit = data.get("sourceCommit")
        metrics = data.get("metrics") or {}
        evaluator = data.get("officialEvaluator") or {}
        conversion = data.get("conversion") or {}
        converted = data.get("convertedResult") or {}
        if data.get("promotionReady") is not True:
            blockers.append(f"{label}:semanticqa_not_promotion_ready")
        if data.get("promotionEvaluation") is not True:
            blockers.append(f"{label}:semanticqa_not_run_in_promotion_mode")
        if not is_git_sha(commit):
            blockers.append(f"{label}:semanticqa_source_commit_not_full_sha")
        if data.get("checkoutDirty") is not False:
            blockers.append(f"{label}:semanticqa_checkout_not_clean")
        if int(metrics.get("cases", -1)) != 305:
            blockers.append(f"{label}:semanticqa_case_count_not_305")
        if metrics.get("accuracy") is None:
            blockers.append(f"{label}:semanticqa_missing_accuracy")
        if not is_sha256(evaluator.get("sha256")):
            blockers.append(f"{label}:semanticqa_missing_evaluator_sha256")
        if not is_sha256(conversion.get("manifestSha256")):
            blockers.append(f"{label}:semanticqa_missing_conversion_manifest_sha256")
        if int(conversion.get("manifestVersion") or 0) < 2:
            blockers.append(f"{label}:semanticqa_conversion_manifest_too_old")
        if not is_sha256(converted.get("sha256")):
            blockers.append(f"{label}:semanticqa_missing_converted_result_sha256")
        policy = str(conversion.get("predictionPolicy") or "")
        if not all(fragment in policy for fragment in ("whitespace normalization", "is: ", "Output:")):
            blockers.append(f"{label}:semanticqa_missing_official_postprocess_provenance")
        summary = {
            "sourceCommit": commit,
            "cases": metrics.get("cases"),
            "accuracy": metrics.get("accuracy"),
            "officialEvaluatorSha256": evaluator.get("sha256"),
            "conversionManifestSha256": conversion.get("manifestSha256"),
            "convertedResultSha256": converted.get("sha256"),
        }

    elif kind == "swords":
        revision = data.get("swordsRepositoryRevision")
        metrics = data.get("metrics") or {}
        module_hashes = data.get("officialModuleSha256") or {}
        if not is_git_sha(revision):
            blockers.append(f"{label}:swords_revision_not_full_sha")
        if data.get("swordsWorktreeDirty") is not False:
            blockers.append(f"{label}:swords_checkout_not_clean")
        if not str(data.get("officialDatasetId") or "").strip():
            blockers.append(f"{label}:swords_missing_dataset_id")
        for key, value in (
            ("official_dataset", data.get("officialDatasetSha256")),
            ("lsr", data.get("lsrSha256")),
            ("conversion_manifest", data.get("conversionManifestSha256")),
            ("metrics_json", data.get("metricsJsonSha256")),
        ):
            if not is_sha256(value):
                blockers.append(f"{label}:swords_missing_{key}_sha256")
        if not module_hashes or any(not is_sha256(v) for v in module_hashes.values()):
            blockers.append(f"{label}:swords_missing_official_module_hashes")
        for metric in SWORDS_CORE_METRICS:
            if metrics.get(metric) is None:
                blockers.append(f"{label}:swords_missing_core_metric:{metric}")
        summary = {
            "sourceCommit": revision,
            "officialDatasetId": data.get("officialDatasetId"),
            "officialDatasetSha256": data.get("officialDatasetSha256"),
            "lsrSha256": data.get("lsrSha256"),
            "coreMetrics": {name: metrics.get(name) for name in SWORDS_CORE_METRICS},
        }

    elif kind == "jfleg":
        revision = data.get("jflegRepositoryRevision")
        protocol = data.get("protocol") or {}
        refs = data.get("references") or []
        stdout = str(data.get("stdout") or "")
        if not is_git_sha(revision):
            blockers.append(f"{label}:jfleg_revision_not_full_sha")
        if data.get("jflegWorktreeDirty") is not False:
            blockers.append(f"{label}:jfleg_checkout_not_clean")
        for key, value in (
            ("evaluator", data.get("evaluatorSha256")),
            ("source", data.get("sourceSha256")),
            ("hypothesis", data.get("hypothesisSha256")),
            ("conversion_manifest", data.get("conversionManifestSha256")),
            ("stdout", data.get("stdoutSha256")),
        ):
            if not is_sha256(value):
                blockers.append(f"{label}:jfleg_missing_{key}_sha256")
        if len(refs) != 4:
            blockers.append(f"{label}:jfleg_requires_four_references")
        else:
            hashes = [row.get("sha256") for row in refs if isinstance(row, dict)]
            if len(hashes) != 4 or any(not is_sha256(v) for v in hashes):
                blockers.append(f"{label}:jfleg_invalid_reference_hashes")
            elif len(set(hashes)) != 4:
                blockers.append(f"{label}:jfleg_reference_hashes_not_unique")
        if int(protocol.get("iterations", -1)) != 500:
            blockers.append(f"{label}:jfleg_nonofficial_iteration_count")
        if int(protocol.get("referencesUsed", -1)) != 4:
            blockers.append(f"{label}:jfleg_protocol_not_four_reference")
        if "official JFLEG GLEU" not in str(protocol.get("metric") or ""):
            blockers.append(f"{label}:jfleg_metric_not_official_gleu")
        if not stdout.strip():
            blockers.append(f"{label}:jfleg_empty_evaluator_stdout")
        summary = {
            "sourceCommit": revision,
            "evaluatorSha256": data.get("evaluatorSha256"),
            "sourceSha256": data.get("sourceSha256"),
            "hypothesisSha256": data.get("hypothesisSha256"),
            "referenceSha256": [row.get("sha256") for row in refs if isinstance(row, dict)],
            "protocol": protocol,
            "stdoutSha256": data.get("stdoutSha256"),
        }

    return kind, blockers, summary


def inspect_run_integrity(run: dict) -> tuple[list[str], dict]:
    blockers: list[str] = []
    outputs = run.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        blockers.append("run_has_no_outputs")
        outputs = []

    declared_count = run.get("taskCount")
    if not isinstance(declared_count, int) or isinstance(declared_count, bool) or declared_count < 1:
        blockers.append("missing_or_invalid_task_count")
    elif declared_count != len(outputs):
        blockers.append("task_count_output_count_mismatch")

    declared_raw_hash = (run.get("reproducibility") or {}).get("rawOutputSha256")
    actual_raw_hash = canonical_outputs_sha256(outputs) if outputs else None
    if not is_sha256(declared_raw_hash):
        blockers.append("missing_raw_output_hash")
    elif actual_raw_hash != str(declared_raw_hash).lower():
        blockers.append("raw_output_hash_mismatch")

    output_ids = [row.get("id") for row in outputs if isinstance(row, dict)]
    if len(output_ids) != len(outputs):
        blockers.append("non_object_output_row")
    elif any(not str(value or "").strip() for value in output_ids):
        blockers.append("missing_output_id")
    elif len(output_ids) != len(set(output_ids)):
        blockers.append("duplicate_output_ids")

    task_path = Path(str(run.get("taskFile") or ""))
    task_file_resolved = task_path.is_file()
    task_hash_verified = False
    task_ids_verified = False
    resolved_task_count = None
    if task_file_resolved:
        task_bytes = task_path.read_bytes()
        actual_task_hash = sha256_bytes(task_bytes)
        task_hash_verified = actual_task_hash == run.get("taskFileSha256")
        if not task_hash_verified:
            blockers.append("task_file_hash_mismatch")
        try:
            tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]
            task_ids = [row.get("id") for row in tasks]
            resolved_task_count = len(task_ids)
            if len(task_ids) != len(set(task_ids)):
                blockers.append("duplicate_task_ids")
            if declared_count != resolved_task_count:
                blockers.append("task_count_task_file_mismatch")
            if set(task_ids) != set(output_ids):
                blockers.append("task_output_id_set_mismatch")
            else:
                task_ids_verified = True
        except Exception:
            blockers.append("task_file_parse_failed")
    else:
        blockers.append("task_file_not_locally_resolvable_for_integrity_check")

    return blockers, {
        "declaredTaskCount": declared_count,
        "outputCount": len(outputs),
        "resolvedTaskCount": resolved_task_count,
        "rawOutputHashVerified": bool(outputs and is_sha256(declared_raw_hash) and actual_raw_hash == str(declared_raw_hash).lower()),
        "taskFileLocallyResolved": task_file_resolved,
        "taskFileHashVerified": task_hash_verified,
        "taskOutputIdsVerified": task_ids_verified,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--score", type=Path)
    ap.add_argument("--artifact", action="append", default=[], type=parse_labeled_file)
    ap.add_argument("--public-manifest", action="append", default=[], type=parse_labeled_file)
    ap.add_argument("--official-evidence", action="append", default=[], type=parse_labeled_file)
    ap.add_argument("--model-artifact-sha256", help="override/supply exact model artifact hash")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument(
        "--require-promotion-ready",
        action="store_true",
        help="Exit non-zero when required reproducibility evidence is missing.",
    )
    args = ap.parse_args()

    run_path = args.run.expanduser().resolve()
    if not run_path.is_file():
        raise SystemExit(f"Missing run result: {run_path}")
    score_path = args.score.expanduser().resolve() if args.score else None
    if score_path and not score_path.is_file():
        raise SystemExit(f"Missing score result: {score_path}")

    run = load_json(run_path)
    score = load_json(score_path) if score_path else None

    current_commit = git_value(["rev-parse", "HEAD"])
    status = git_value(["status", "--porcelain"])
    dirty = bool(status)

    artifacts = [
        {
            "label": "run",
            "path": str(run_path),
            "sha256": sha256_file(run_path),
            "bytes": run_path.stat().st_size,
        }
    ]
    if score_path:
        artifacts.append(
            {
                "label": "score",
                "path": str(score_path),
                "sha256": sha256_file(score_path),
                "bytes": score_path.stat().st_size,
            }
        )

    used_labels = {row["label"] for row in artifacts}
    generic_artifact_blockers: list[str] = []
    for label, path in args.artifact:
        if label in used_labels:
            raise SystemExit(f"Duplicate artifact label: {label}")
        used_labels.add(label)
        artifact_row = {"label": label, "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        artifacts.append(artifact_row)
        try:
            data = load_json(path)
        except Exception:
            data = None
        if isinstance(data, dict) and looks_like_official_evidence(data):
            generic_artifact_blockers.append(f"{label}:official_evidence_must_use_official_evidence_flag")

    public_manifests = []
    public_blockers = []
    for label, path in args.public_manifest:
        if label in used_labels:
            raise SystemExit(f"Duplicate artifact label: {label}")
        used_labels.add(label)
        data = load_json(path)
        blockers_for_source = public_manifest_blockers(label, data)
        public_blockers.extend(blockers_for_source)
        public_manifests.append({
            "label": label,
            "path": str(path),
            "sha256": sha256_file(path),
            "datasetsLibraryVersion": data.get("datasetsLibraryVersion"),
            "sources": data.get("sources"),
            "resolvedDatasetFingerprints": data.get("resolvedDatasetFingerprints"),
            "promotionBlockers": blockers_for_source,
        })
        artifacts.append({"label": label, "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})

    official_evidence = []
    official_blockers: list[str] = []
    for label, path in args.official_evidence:
        if label in used_labels:
            raise SystemExit(f"Duplicate artifact label: {label}")
        used_labels.add(label)
        data = load_json(path)
        kind, blockers_for_evidence, summary = official_evidence_blockers(label, data)
        official_blockers.extend(blockers_for_evidence)
        row = {
            "label": label,
            "kind": kind,
            "path": str(path),
            "sha256": sha256_file(path),
            "promotionReady": not blockers_for_evidence,
            "promotionBlockers": blockers_for_evidence,
            "summary": summary,
        }
        official_evidence.append(row)
        artifacts.append({"label": label, "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})

    model = run.get("model") or {}
    decoding = run.get("decoding") or {}
    reproducibility = run.get("reproducibility") or {}
    model_hash = args.model_artifact_sha256 or model.get("artifactSha256")
    declared_benchmark_revision = reproducibility.get("benchmarkRevision")

    blockers = []
    if not is_sha256(model_hash):
        blockers.append("missing_or_invalid_model_artifact_sha256")
    if not known(model.get("revision")):
        blockers.append("missing_exact_model_revision")
    if not known(model.get("quantization")):
        blockers.append("missing_quantization_identity")
    if model.get("checkpointType") in (None, "unknown"):
        blockers.append("missing_checkpoint_type")
    if not known(model.get("runtimeVersion")):
        blockers.append("missing_runtime_version")
    if not known(model.get("tokenizerName")):
        blockers.append("missing_tokenizer_identity")
    if run.get("promptModeRequested") == "auto":
        blockers.append("auto_prompt_adaptation_not_promotion_safe")
    if run.get("promptModeRequested") not in {"plain", "chat"}:
        blockers.append("missing_explicit_prompt_adaptation")

    adaptation_modes = set(run.get("promptAdaptationModesObserved") or [])
    if len(adaptation_modes) != 1:
        blockers.append("mixed_or_missing_prompt_adaptation_modes")
    if run.get("promptModeRequested") == "plain" and adaptation_modes != {"plain"}:
        blockers.append("plain_prompt_mode_adaptation_mismatch")
    if run.get("promptModeRequested") == "chat" and adaptation_modes != {"chat_template"}:
        blockers.append("chat_prompt_mode_adaptation_mismatch")
    if model.get("checkpointType") == "base" and run.get("promptModeRequested") == "chat":
        blockers.append("base_checkpoint_chat_adaptation_requires_separate_justification")
    if model.get("checkpointType") in {"chat", "instruct"} and run.get("promptModeRequested") == "plain":
        blockers.append("chat_or_instruct_checkpoint_plain_adaptation_requires_separate_justification")
    if "chat_template" in adaptation_modes and not is_sha256(model.get("chatTemplateSha256")):
        blockers.append("missing_chat_template_hash_for_chat_run")

    if not is_sha256(run.get("taskFileSha256")):
        blockers.append("missing_task_file_hash")
    for key in ("temperature", "topP", "topK", "maxNewTokens", "forcedChoiceMaxNewTokens", "seed"):
        if key not in decoding:
            blockers.append(f"missing_decoding_{key}")
    if not known(declared_benchmark_revision):
        blockers.append("missing_benchmark_revision")

    integrity_blockers, integrity = inspect_run_integrity(run)
    blockers.extend(integrity_blockers)

    if not current_commit:
        blockers.append("unable_to_resolve_current_git_commit")
    elif known(declared_benchmark_revision) and declared_benchmark_revision != current_commit:
        blockers.append("declared_benchmark_revision_mismatch_current_checkout")
    if dirty:
        blockers.append("benchmark_worktree_is_dirty")

    if score is None:
        blockers.append("missing_shadow_score_artifact")
    else:
        required_hashes = ("configSha256", "shadowSeedSha256", "generativeMetricContractSha256")
        benchmark_inputs = score.get("benchmarkInputs") or {}
        for key in required_hashes:
            if not is_sha256(benchmark_inputs.get(key)):
                blockers.append(f"missing_score_benchmark_hash_{key}")
        if score.get("taskFileSha256") != run.get("taskFileSha256"):
            blockers.append("score_run_task_hash_mismatch")
        if score.get("complete") is not True:
            blockers.append("incomplete_shadow_score")

    blockers.extend(public_blockers)
    blockers.extend(generic_artifact_blockers)
    blockers.extend(official_blockers)
    blockers = list(dict.fromkeys(blockers))

    manifest = {
        "version": 5,
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "purpose": "Frozen provenance manifest for English Core evidence; not a quality metric.",
        "promotionReady": not blockers,
        "promotionBlockers": blockers,
        "runIntegrity": integrity,
        "model": {**model, "artifactSha256": model_hash},
        "hardware": run.get("hardware"),
        "decoding": decoding,
        "promptModeRequested": run.get("promptModeRequested"),
        "promptAdaptationModesObserved": run.get("promptAdaptationModesObserved"),
        "promptAdaptationDetailsObserved": run.get("promptAdaptationDetailsObserved"),
        "taskFile": run.get("taskFile"),
        "taskFileSha256": run.get("taskFileSha256"),
        "taskCount": run.get("taskCount"),
        "runReproducibility": reproducibility,
        "scoreBenchmarkInputs": score.get("benchmarkInputs") if score else None,
        "scoreComplete": score.get("complete") if score else None,
        "metricProvenance": unique_metric_provenance(score),
        "benchmarkCheckout": {
            "currentGitCommit": current_commit,
            "worktreeDirty": dirty,
            "declaredBenchmarkRevision": declared_benchmark_revision,
            "declaredMatchesCurrent": bool(current_commit and declared_benchmark_revision == current_commit),
        },
        "publicSourceManifests": public_manifests,
        "officialEvidence": official_evidence,
        "artifacts": artifacts,
        "rules": [
            "All supplied evidence files are hashed byte-for-byte.",
            "The run's raw-output hash, task count, task-file hash, and task/output ID set are independently rechecked when the task file is locally resolvable.",
            "A task file that cannot be locally resolved blocks promotion-manifest integrity verification instead of being silently trusted from metadata alone.",
            "Promotion readiness is a provenance gate only; it does not imply model quality or benchmark validity.",
            "Promotion requires an explicit prompt adaptation mode and one observed adaptation path; auto/mixed adaptation is exploratory only.",
            "A dirty benchmark checkout or declared/current revision mismatch blocks promotion because the evaluator state would not be independently reproducible.",
            "A complete shadow score is required; missing generative judgments cannot be hidden by a provenance-complete manifest.",
            "Chat-template runs require a recorded tokenizer chat-template hash.",
            "Supplied Hugging Face public-source manifests require immutable requested revisions and resolved fingerprints for every represented source.",
            "Public-fast reproducibility does not convert that lane into an official/native benchmark result.",
            "Generic --artifact inputs are byte-hashed only. A JSON that looks like supported official benchmark evidence must be supplied through --official-evidence or it blocks promotion readiness.",
            "Supported --official-evidence JSONs are semantically inspected for frozen revision/clean-checkout/hash/protocol requirements rather than trusted by filename or existence alone.",
            "SemanticQA official evidence must preserve the benchmark's own LCC postprocessing before exact-label evaluation; the broader Pari tolerant parser remains a separate diagnostic.",
            "SWORDS, JFLEG, and SemanticQA official evidence remain separate benchmark lanes and are never collapsed into one pseudo-official score by this manifest."
        ],
    }

    output_path = args.output.expanduser().resolve()
    output_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output_path), "promotionReady": not blockers, "blockers": blockers}, indent=2))
    if args.require_promotion_ready and blockers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
