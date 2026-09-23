"""Build a frozen reproducibility manifest for an English Core evaluation.

The manifest is evidence bookkeeping, not a quality metric. It records exact
artifacts and identifies missing provenance that blocks promotion-quality claims.

Example:
    python build-english-core-repro-manifest.py \
      --run shadow-result.json \
      --score shadow-score.json \
      --artifact shadow-stats=shadow-stats.json \
      --artifact prompt-score=prompt-score.json \
      --model-artifact-sha256 <64-hex> \
      --output repro-manifest.json \
      --require-promotion-ready

Use repeated --artifact LABEL=PATH for public/native benchmark outputs, official
SWORDS/JFLEG evaluator files, human-eval exports, or other frozen evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


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


def parse_artifact(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("artifact must be LABEL=PATH")
    label, raw_path = value.split("=", 1)
    label = label.strip()
    if not label:
        raise argparse.ArgumentTypeError("artifact label cannot be empty")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"artifact is not a file: {path}")
    return label, path


def is_sha256(value: str | None) -> bool:
    if not value or len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


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
    ap.add_argument("--artifact", action="append", default=[], type=parse_artifact)
    ap.add_argument("--model-artifact-sha256")
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
        artifacts.append(
            {
                "label": label,
                "path": str(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )

    model = run.get("model") or {}
    decoding = run.get("decoding") or {}
    reproducibility = run.get("reproducibility") or {}
    model_hash = args.model_artifact_sha256 or model.get("artifactSha256")
    declared_benchmark_revision = reproducibility.get("benchmarkRevision")

    blockers = []
    if not is_sha256(model_hash):
        blockers.append("missing_or_invalid_model_artifact_sha256")
    if not model.get("revision") or model.get("revision") == "unknown":
        blockers.append("missing_exact_model_revision")
    if not model.get("quantization") or model.get("quantization") == "unknown":
        blockers.append("missing_quantization_identity")
    if not model.get("runtimeVersion") or model.get("runtimeVersion") == "unknown":
        blockers.append("missing_runtime_version")
    if not run.get("taskFileSha256"):
        blockers.append("missing_task_file_hash")
    for key in ("temperature", "topP", "topK", "seed"):
        if key not in decoding:
            blockers.append(f"missing_decoding_{key}")
    if not reproducibility.get("rawOutputSha256"):
        blockers.append("missing_raw_output_hash")
    if not declared_benchmark_revision or declared_benchmark_revision == "unknown":
        blockers.append("missing_benchmark_revision")
    if not current_commit:
        blockers.append("unable_to_resolve_current_git_commit")
    elif declared_benchmark_revision and declared_benchmark_revision != "unknown" and declared_benchmark_revision != current_commit:
        blockers.append("declared_benchmark_revision_mismatch_current_checkout")
    if dirty:
        blockers.append("benchmark_worktree_is_dirty")

    adaptation_modes = set(run.get("promptAdaptationModesObserved") or [])
    if "chat_template" in adaptation_modes and not is_sha256(model.get("chatTemplateSha256")):
        blockers.append("missing_chat_template_hash_for_chat_run")

    if score is None:
        blockers.append("missing_shadow_score_artifact")
    else:
        required_hashes = (
            "configSha256",
            "shadowSeedSha256",
            "generativeMetricContractSha256",
        )
        benchmark_inputs = score.get("benchmarkInputs") or {}
        for key in required_hashes:
            if not is_sha256(benchmark_inputs.get(key)):
                blockers.append(f"missing_score_benchmark_hash_{key}")
        if score.get("taskFileSha256") != run.get("taskFileSha256"):
            blockers.append("score_run_task_hash_mismatch")
        if score.get("complete") is not True:
            blockers.append("incomplete_shadow_score")

    blockers = list(dict.fromkeys(blockers))
    manifest = {
        "version": 2,
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "purpose": "Frozen provenance manifest for English Core evidence; not a quality metric.",
        "promotionReady": not blockers,
        "promotionBlockers": blockers,
        "model": {
            **model,
            "artifactSha256": model_hash,
        },
        "hardware": run.get("hardware"),
        "decoding": decoding,
        "promptModeRequested": run.get("promptModeRequested"),
        "promptAdaptationModesObserved": run.get("promptAdaptationModesObserved"),
        "promptAdaptationDetailsObserved": run.get("promptAdaptationDetailsObserved"),
        "taskFile": run.get("taskFile"),
        "taskFileSha256": run.get("taskFileSha256"),
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
        "artifacts": artifacts,
        "rules": [
            "All supplied evidence files are hashed byte-for-byte.",
            "Promotion readiness is a provenance gate only; it does not imply model quality or benchmark validity.",
            "A dirty benchmark checkout or a declared/current revision mismatch blocks promotion readiness because the evaluator state would not be independently reproducible.",
            "A complete shadow score is required for promotion readiness; missing generative judgments cannot be hidden by a provenance-complete manifest.",
            "Chat-template runs require a recorded tokenizer chat-template hash.",
            "External/native evaluator outputs should be attached with --artifact and their evaluator revisions recorded in the artifact itself or accompanying notes.",
        ],
    }

    output_path = args.output.expanduser().resolve()
    output_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output_path), "promotionReady": not blockers, "blockers": blockers}, indent=2))
    if args.require_promotion_ready and blockers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
