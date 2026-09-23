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
      --public-manifest public-full=english-core-public-full-classification.manifest.json \
      --output repro-manifest.json \
      --require-promotion-ready

Use repeated --artifact LABEL=PATH for native/public benchmark outputs, official
SWORDS/JFLEG evaluator files, human-eval exports, or other frozen evidence.
Use repeated --public-manifest LABEL=PATH for Hugging Face-derived builder
manifests whose revisions/fingerprints must be immutable for promotion use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MUTABLE_REVISIONS = {"", "unknown", "mutable_default_not_pinned", "main", "master", "latest", "default"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


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


def is_sha256(value: str | None) -> bool:
    if not value or len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--score", type=Path)
    ap.add_argument("--artifact", action="append", default=[], type=parse_labeled_file)
    ap.add_argument("--public-manifest", action="append", default=[], type=parse_labeled_file)
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
    for label, path in args.artifact:
        if label in used_labels:
            raise SystemExit(f"Duplicate artifact label: {label}")
        used_labels.add(label)
        artifacts.append({"label": label, "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})

    public_manifests = []
    public_blockers = []
    for label, path in args.public_manifest:
        if label in used_labels:
            raise SystemExit(f"Duplicate artifact label: {label}")
        used_labels.add(label)
        data = load_json(path)
        blockers = public_manifest_blockers(label, data)
        public_blockers.extend(blockers)
        public_manifests.append({
            "label": label,
            "path": str(path),
            "sha256": sha256_file(path),
            "datasetsLibraryVersion": data.get("datasetsLibraryVersion"),
            "sources": data.get("sources"),
            "resolvedDatasetFingerprints": data.get("resolvedDatasetFingerprints"),
            "promotionBlockers": blockers,
        })
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
    if not isinstance(run.get("taskCount"), int) or run.get("taskCount") < 1:
        blockers.append("missing_task_count")
    for key in ("temperature", "topP", "topK", "maxNewTokens", "forcedChoiceMaxNewTokens", "seed"):
        if key not in decoding:
            blockers.append(f"missing_decoding_{key}")
    if not is_sha256(reproducibility.get("rawOutputSha256")):
        blockers.append("missing_raw_output_hash")
    if not known(declared_benchmark_revision):
        blockers.append("missing_benchmark_revision")
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
    blockers = list(dict.fromkeys(blockers))

    manifest = {
        "version": 3,
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "purpose": "Frozen provenance manifest for English Core evidence; not a quality metric.",
        "promotionReady": not blockers,
        "promotionBlockers": blockers,
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
        "artifacts": artifacts,
        "rules": [
            "All supplied evidence files are hashed byte-for-byte.",
            "Promotion readiness is a provenance gate only; it does not imply model quality or benchmark validity.",
            "Promotion requires an explicit prompt adaptation mode and one observed adaptation path; auto/mixed adaptation is exploratory only.",
            "A dirty benchmark checkout or declared/current revision mismatch blocks promotion because the evaluator state would not be independently reproducible.",
            "A complete shadow score is required; missing generative judgments cannot be hidden by a provenance-complete manifest.",
            "Chat-template runs require a recorded tokenizer chat-template hash.",
            "Supplied Hugging Face public-source manifests require immutable requested revisions and resolved fingerprints for every represented source.",
            "Public-fast reproducibility does not convert that lane into an official/native benchmark result.",
            "External/native evaluator outputs should be attached with --artifact and evaluator/source revisions preserved in accompanying artifacts/notes."
        ],
    }

    output_path = args.output.expanduser().resolve()
    output_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output_path), "promotionReady": not blockers, "blockers": blockers}, indent=2))
    if args.require_promotion_ready and blockers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
