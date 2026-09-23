"""Validate English Core result metadata before promotion-quality comparison.

Usage:
    python validate-english-core-run.py result.json
    python validate-english-core-run.py result.json --promotion

The default mode reports reproducibility warnings. --promotion turns the
promotion-quality requirements from ENGLISH_CORE_ROBUSTNESS.md into hard errors.
This validates metadata/completeness, not linguistic correctness.
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

    task_path = Path(str(run.get("taskFile") or ""))
    if task_path.exists() and task_path.is_file():
        actual = sha256_bytes(task_path.read_bytes())
        if actual != task_hash:
            errors.append("taskFileSha256 does not match the current task file bytes")
        try:
            task_ids = [json.loads(line)["id"] for line in task_path.read_text().splitlines() if line.strip()]
            output_ids = [row.get("id") for row in outputs]
            if len(output_ids) != len(set(output_ids)):
                errors.append("duplicate output IDs in result")
            if set(task_ids) != set(output_ids):
                missing = sorted(set(task_ids) - set(output_ids))
                extra = sorted(set(output_ids) - set(task_ids))
                issue(f"output/task ID mismatch: missing={len(missing)} extra={len(extra)}", True)
        except Exception as exc:
            errors.append(f"could not validate task/output IDs: {exc}")
    else:
        issue("taskFile path is not locally resolvable; hash cannot be rechecked against bytes", args.promotion)

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
    if isinstance(decoding.get("topP"), (int, float)) and not 0 <= decoding["topP"] <= 1:
        errors.append("decoding.topP outside [0,1]")
    if isinstance(decoding.get("topK"), int) and decoding["topK"] < 0:
        errors.append("decoding.topK < 0")

    if not known(repro.get("benchmarkRevision")):
        issue("reproducibility.benchmarkRevision missing/unknown", True)
    if not is_sha256(repro.get("rawOutputSha256")):
        issue("reproducibility.rawOutputSha256 missing/invalid", True)

    output_ids = [row.get("id") for row in outputs]
    if any(not known(x) for x in output_ids):
        errors.append("one or more outputs have missing IDs")
    if len(output_ids) != len(set(output_ids)):
        errors.append("duplicate output IDs")

    if not outputs:
        errors.append("result has no outputs")

    report = {
        "version": 1,
        "result": str(result_path),
        "mode": "promotion" if args.promotion else "exploratory",
        "errors": errors,
        "warnings": warnings,
        "status": "fail" if errors else ("pass_with_warnings" if warnings else "pass"),
        "interpretation": [
            "This validator checks reproducibility/comparability metadata, not English correctness.",
            "Promotion mode intentionally rejects ambiguous adaptation and unknown artifact metadata rather than assuming two runs are comparable.",
            "A passing result still requires benchmark-native anchors, robustness lanes, statistical comparison, and human validation at the claim tier specified in ENGLISH_CORE_ROBUSTNESS.md."
        ]
    }
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
