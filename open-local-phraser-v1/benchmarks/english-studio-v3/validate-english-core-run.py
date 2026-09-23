"""Validate English Core result metadata before promotion-quality comparison.

Usage:
    python validate-english-core-run.py result.json
    python validate-english-core-run.py result.json --promotion

The default mode reports reproducibility warnings. --promotion turns the
promotion-quality requirements from ENGLISH_CORE_ROBUSTNESS.md into hard errors.
This validates metadata/completeness/integrity, not linguistic correctness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
UNKNOWN = {"", "unknown", "unspecified", "n/a", "na", "none-known"}


def known(value) -> bool:
    return str(value or "").strip().lower() not in UNKNOWN


def is_sha256(value) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "")))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_outputs_sha256(outputs: list[dict]) -> str:
    """Match run-english-core-mlx.py's raw-output hashing contract exactly."""
    payload = json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256_bytes(payload)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--promotion", action="store_true", help="enforce Tier-2/promotion metadata as hard requirements")
    args = ap.parse_args()

    result_path = Path(args.result)
    run = json.loads(result_path.read_text())
    errors: list[str] = []
    warnings: list[str] = []

    def issue(message: str, promotion_required: bool = False) -> None:
        if args.promotion and promotion_required:
            errors.append(message)
        else:
            warnings.append(message)

    model = run.get("model") or {}
    decoding = run.get("decoding") or {}
    repro = run.get("reproducibility") or {}
    outputs = run.get("outputs") or []

    if not isinstance(outputs, list):
        errors.append("outputs must be an array")
        outputs = []

    if not known(model.get("name")):
        errors.append("model.name missing")
    if not known(model.get("repoOrName")):
        issue("model.repoOrName missing/unknown", True)
    if not known(model.get("revision")):
        issue("model.revision missing/unknown", True)
    if not known(model.get("quantization")):
        issue("model.quantization missing/unknown; use an explicit value such as fp16/bf16/q4/q8/full", True)
    if model.get("checkpointType") in (None, "unknown"):
        issue("model.checkpointType missing/unknown", True)
    if not known(model.get("runtime")) or not known(model.get("runtimeVersion")):
        issue("runtime identity/version incomplete", True)
    if not known(model.get("tokenizerName")):
        issue("tokenizerName missing/unknown", True)

    artifact_hash = model.get("artifactSha256")
    if artifact_hash and not is_sha256(artifact_hash):
        errors.append("model.artifactSha256 is not a SHA-256 hex string")
    elif not artifact_hash:
        issue("model.artifactSha256 missing; exact model artifact is not cryptographically pinned", True)

    task_hash = run.get("taskFileSha256")
    if not is_sha256(task_hash):
        errors.append("taskFileSha256 missing/invalid")

    declared_task_count = run.get("taskCount")
    if not isinstance(declared_task_count, int) or isinstance(declared_task_count, bool) or declared_task_count < 1:
        issue("taskCount missing/invalid; expected positive integer", True)

    task_path = Path(str(run.get("taskFile") or ""))
    task_ids: list[str] | None = None
    if task_path.exists() and task_path.is_file():
        actual = sha256_bytes(task_path.read_bytes())
        if actual != task_hash:
            errors.append("taskFileSha256 does not match the current task file bytes")
        try:
            task_ids = [json.loads(line)["id"] for line in task_path.read_text().splitlines() if line.strip()]
            if len(task_ids) != len(set(task_ids)):
                errors.append("duplicate task IDs in task file")
            if isinstance(declared_task_count, int) and declared_task_count != len(task_ids):
                errors.append(f"taskCount={declared_task_count} does not match task file count={len(task_ids)}")

            output_ids = [row.get("id") for row in outputs if isinstance(row, dict)]
            if len(output_ids) != len(set(output_ids)):
                errors.append("duplicate output IDs in result")
            if set(task_ids) != set(output_ids):
                missing = sorted(set(task_ids) - set(output_ids))
                extra = sorted(set(output_ids) - set(task_ids))
                issue(f"output/task ID mismatch: missing={len(missing)} extra={len(extra)}", True)
            if len(outputs) != len(task_ids):
                issue(f"output count={len(outputs)} does not match task file count={len(task_ids)}", True)
        except Exception as exc:
            errors.append(f"could not validate task/output IDs: {exc}")
    else:
        issue("taskFile path is not locally resolvable; hash/count cannot be rechecked against task bytes", args.promotion)
        if isinstance(declared_task_count, int) and declared_task_count != len(outputs):
            issue(f"taskCount={declared_task_count} does not match output count={len(outputs)}", True)

    prompt_mode = run.get("promptModeRequested")
    if prompt_mode not in {"plain", "chat", "auto"}:
        errors.append("promptModeRequested missing/invalid")
    if prompt_mode == "auto":
        issue("promptModeRequested=auto is exploratory; promotion runs require explicit plain or chat adaptation", True)

    observed = run.get("promptAdaptationModesObserved") or []
    if not observed:
        issue("promptAdaptationModesObserved missing", True)
    if len(set(observed)) > 1:
        issue(f"mixed prompt adaptation modes observed: {observed}", True)
    if prompt_mode == "plain" and observed and set(observed) != {"plain"}:
        errors.append(f"plain prompt mode produced unexpected adaptation modes: {observed}")
    if prompt_mode == "chat" and observed and set(observed) != {"chat_template"}:
        errors.append(f"chat prompt mode produced unexpected adaptation modes: {observed}")

    checkpoint_type = model.get("checkpointType")
    if checkpoint_type == "base" and prompt_mode == "chat":
        issue("base checkpoint evaluated through chat adaptation; justify protocol before comparison", True)
    if checkpoint_type in {"chat", "instruct"} and prompt_mode == "plain":
        issue("chat/instruct checkpoint evaluated with plain prompt; justify protocol before comparison", True)

    if "chat_template" in observed:
        if not is_sha256(model.get("chatTemplateSha256")):
            issue("chat template was used but chatTemplateSha256 is missing/invalid", True)

    required_decoding = ["temperature", "topP", "topK", "maxNewTokens", "forcedChoiceMaxNewTokens", "seed"]
    for key in required_decoding:
        if key not in decoding:
            issue(f"decoding.{key} missing", True)
    if isinstance(decoding.get("temperature"), (int, float)) and decoding["temperature"] < 0:
        errors.append("decoding.temperature < 0")
    if isinstance(decoding.get("topP"), (int, float)) and not 0 <= decoding["topP"] <= 1:
        errors.append("decoding.topP outside [0,1]")
    if isinstance(decoding.get("topK"), int) and not isinstance(decoding.get("topK"), bool) and decoding["topK"] < 0:
        errors.append("decoding.topK < 0")
    for key in ("maxNewTokens", "forcedChoiceMaxNewTokens"):
        value = decoding.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value < 1:
            errors.append(f"decoding.{key} < 1")

    if not known(repro.get("benchmarkRevision")):
        issue("reproducibility.benchmarkRevision missing/unknown", True)

    declared_raw_hash = repro.get("rawOutputSha256")
    if not is_sha256(declared_raw_hash):
        issue("reproducibility.rawOutputSha256 missing/invalid", True)
    elif outputs:
        actual_raw_hash = canonical_outputs_sha256(outputs)
        if actual_raw_hash.lower() != str(declared_raw_hash).lower():
            errors.append("reproducibility.rawOutputSha256 does not match the current outputs array; result may have been modified after generation")

    output_ids = [row.get("id") for row in outputs if isinstance(row, dict)]
    if len(output_ids) != len(outputs):
        errors.append("one or more outputs are not objects")
    if any(not known(x) for x in output_ids):
        errors.append("one or more outputs have missing IDs")
    if len(output_ids) != len(set(output_ids)):
        errors.append("duplicate output IDs")

    if not outputs:
        errors.append("result has no outputs")

    report = {
        "version": 2,
        "result": str(result_path),
        "mode": "promotion" if args.promotion else "exploratory",
        "declaredTaskCount": declared_task_count,
        "observedOutputCount": len(outputs),
        "locallyResolvedTaskCount": len(task_ids) if task_ids is not None else None,
        "rawOutputHashVerified": bool(outputs and is_sha256(declared_raw_hash) and canonical_outputs_sha256(outputs).lower() == str(declared_raw_hash).lower()),
        "errors": errors,
        "warnings": warnings,
        "status": "fail" if errors else ("pass_with_warnings" if warnings else "pass"),
        "interpretation": [
            "This validator checks reproducibility/comparability metadata and result-file integrity, not English correctness.",
            "The raw-output hash is recomputed from the outputs array using the same canonical serialization as run-english-core-mlx.py; a mismatch is a hard integrity error.",
            "Promotion mode intentionally rejects ambiguous adaptation, incomplete task coverage, and unknown artifact metadata rather than assuming two runs are comparable.",
            "A passing result still requires benchmark-native anchors, robustness lanes, statistical comparison, and human validation at the claim tier specified in ENGLISH_CORE_ROBUSTNESS.md."
        ]
    }
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
