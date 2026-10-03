#!/usr/bin/env python3
"""Build a phase-aware runtime/product status matrix from Kaggle result summaries.

This tool never ranks models. It prevents silent omission by requiring every
roster candidate to appear at every phase, and by *validating* the provenance
chain that ties each measured candidate-stage summary to the exact preflight
artifact, pinned runtime install receipt, and frozen task artifacts that produced
it (Issue #33).

Lifecycle (Issue #39): the matrix is phase-aware rather than demanding all four
stages from everyone.

* Screening phase -- every roster candidate needs ``smoke``; ``full`` is required
  once the candidate is runtime-qualified. ``word-studio``/``transform`` are the
  Word Studio product suites and are finalist-only, so a correctly screened
  non-finalist reaches ``screen_complete_pending_finalist_selection`` instead of
  sitting forever in ``pending_measurement`` and burning GPU time.
* Finalist decision -- membership comes only from an explicit, hashable
  ``finalist-set.json`` artifact (``--finalist-set``), never from whichever
  product folders happen to exist. The artifact is validated: unknown candidate
  ids, config/benchmark-revision mismatches and unresolvable source screen hashes
  all fail closed.
* Product phase -- only finalists require ``word-studio`` and ``transform``.
  Non-finalists show ``not_run_non_finalist`` for those stages, and any historical
  product evidence they still carry remains visible without reclassifying them.

Provenance is an integrity requirement (Issue #33). A summary that records a
hash for an artifact that is missing, or whose bytes no longer hash to that
value, is a reporting/integrity failure. It is never converted into an
English-quality score and never silently repaired. Conflicting or unverified
provenance keeps the row visible but excludes it from any comparable
head-to-head group. A runtime-unqualified result stays visible and, when its
provenance chain is complete, remains a valid (unqualified) history row.

Canonical per-summary ``provenance`` block emitted by the candidate runners:

    "provenance": {
      "benchmarkRevision":     "<benchmark git revision>",
      "candidateRevision":     "<pinned model revision>",
      "candidateConfigSha256": "<sha256 of canonical candidate-row JSON>",
      "preflightPath":         "<path to preflight.json>",
      "preflightSha256":       "<sha256 of preflight.json>",
      "runtimeReceiptPath":    "<path to pinned runtime install receipt>",
      "runtimeReceiptSha256":  "<sha256 of that receipt>",
      "taskFiles":             ["<frozen task file>", ...],
      "taskManifestSha256s":   [{"role": "...", "path": "...", "sha256": "..."}],
      "resultSha256":          "<sha256 of raw result artifact>",
      "parserCodeVersion":     "<parser/diagnostics code identity>"
    }

For every result-bearing summary, the raw result must also name its exact
``contextBudget.receiptPath`` and ``contextBudget.receiptSha256``. The matrix
resolves relative receipt paths beside that raw result, verifies the sidecar's
canonical self-hash and candidate/prompt identity, and includes those values in
``resultFingerprintSha256``. Missing or drifted receipts fail provenance.

``candidateConfigSha256`` is ``sha256`` over the stage-specific configuration
that the runner bound: ``{"candidate": <roster row>, "stage": ..., "decode": ...,
"runtimeArtifact": ...}`` encoded with ``json.dumps(..., sort_keys=True,
separators=(",", ":"))``. The helpers ``stage_config_digest`` and
``candidate_config_digest`` below are the shared definitions.

Legacy summaries written before this contract have no ``provenance`` block.
They remain visible as ``provenance_unverified`` history and are excluded from
comparable groups, because their environment/runtime/task linkage cannot be
proven from the summary itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# Issue #62: the shared promotion gate owns the one definition of "comparable
# promotion evidence", so the matrix reads that contract instead of restating
# it. The module is stdlib-only (no torch/vLLM/llama.cpp), so importing it here
# keeps this tool CPU-safe; the sys.path insert mirrors
# validate-english-core-run.py so the matrix works when loaded by path.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import kaggle_promotion_gate as promotion_gate  # noqa: E402

ROSTER = HERE / "kaggle-candidate-roster.json"
REQUIRED_STAGES = ("smoke", "benchmark-smoke", "full", "word-studio", "transform")
#: The product suites are finalist-only; screening is smoke + full.
SCREEN_STAGES = ("smoke", "benchmark-smoke", "full")
PRODUCT_STAGES = ("word-studio", "transform")

#: Stage -> qualification gate, loaded from the one canonical stage register so
#: the matrix cannot restate (or drift from) the ladder (Issue #48/#49).
_STAGE_MANIFEST_PATH = Path(__file__).resolve().parent / "kaggle-stage-manifest.json"
_STAGE_REGISTER = json.loads(_STAGE_MANIFEST_PATH.read_text(encoding="utf-8"))
STAGE_GATES: dict[str, str] = {
    str(stage): str(entry["gate"]) for stage, entry in _STAGE_REGISTER["stages"].items()
}
QUALIFICATION_LADDER: list[dict[str, Any]] = list(_STAGE_REGISTER["qualificationLadder"])
STAGE_MANIFEST_SHA256 = hashlib.sha256(
    _STAGE_MANIFEST_PATH.read_bytes()
).hexdigest()
#: Canonical pinned vLLM runtime artifact, mirroring run-kaggle-candidate.py.
VLLM_RUNTIME_ARTIFACT = "vllm-0.30.0-cu129-linux-x86_64"

# Non-finalist product stages are intentionally not run, which is a different
# fact from "never attempted" and must never read as an empty cell.
NON_FINALIST_STAGE_STATUS = "not_run_non_finalist"
NOT_APPLICABLE_AFTER_SCREEN = "not_applicable_after_screen"

# Statuses that prove the runtime itself never became usable, so screening can
# never be "required" beyond smoke for that candidate.
RUNTIME_UNQUALIFIED_STATUSES = frozenset({"runtime_unqualified"})

# A written summary in one of these states is a real measurement attempt and must
# carry a verifiable provenance chain. "starting"/"running" summaries belong to
# runs interrupted before inference, are exempt, and stay visible.
PROVENANCE_REQUIRED_STATUSES = frozenset({
    "completed",
    "inference_completed",
    "runtime_unqualified",
    "benchmark_tool_failure",
    "benchmark_validation_failure",
    # Terminal statuses emitted by kaggle_run_checkpoint.execute_unit.
    "benchmark_failed",
    "infrastructure_failed",
    "interrupted_resume_available",
})
PROVENANCE_EXEMPT_STATUSES = frozenset({"starting", "running"})

# The runner binds the stage-specific configuration (roster row, stage, decode
# method and pinned runtime artifact). The matrix reconstructs that same value
# and requires the summary to agree, so a summary cannot borrow a digest that was
# computed for a different stage, decode method or runtime artifact.
BLOCKED_STAGE_STATUSES = frozenset({
    "benchmark_tool_failure",
    "benchmark_validation_failure",
    "benchmark_failed",
    "infrastructure_failed",
    "interrupted_resume_available",
})

#: The one canonical full-screen cell that carries the Issue #62 promotion
#: contract. Sourced from the shared gate module rather than restated here, so
#: the matrix and the two candidate wrappers cannot disagree about which cell
#: needs comparable promotion evidence.
PROMOTION_GATE_STAGE = promotion_gate.PROMOTION_STAGE
PROMOTION_GATE_DECODE = promotion_gate.PROMOTION_DECODE


def promotion_gate_required(stage: str, decode: str, status: str) -> bool:
    """Whether this cell's evidence must carry comparable promotion-gate proof.

    Only a *completed* canonical full-screen normal-decode cell does. Every
    other cell keeps its pre-#62 behaviour, which is deliberate:

    * smoke / benchmark-smoke / product stages legitimately complete on
      protocol diagnostics alone, because the shared gate applies the promotion
      validator only to the full screen;
    * a non-completed terminal state (runtime_unqualified, the two benchmark
      failure states, an interrupted resume) was never comparable in the first
      place, so requiring gate evidence there would only relabel an honest
      failure as a provenance problem.
    """
    return status == "completed" and stage == PROMOTION_GATE_STAGE and decode == PROMOTION_GATE_DECODE


def load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    """Hash the canonical JSON payload used by context-budget receipts."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def candidate_config_digest(candidate: dict[str, Any]) -> str:
    """Shared stable digest of a canonical candidate roster row."""
    blob = json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def stage_config_digest(candidate: dict[str, Any], stage: str, decode: str) -> str:
    """Digest of the stage-specific configuration a runner actually bound.

    Mirrors ``run-kaggle-candidate.build_provenance``: the roster row plus the
    stage, the decode method and the pinned runtime artifact identity. Requiring
    this value stops a summary from reusing a digest computed for a different
    stage or a different speculative method.
    """
    if candidate.get("runtime") == "vllm":
        runtime_artifact: str | None = VLLM_RUNTIME_ARTIFACT
    else:
        declared = candidate.get("runtimeArtifactId")
        runtime_artifact = str(declared) if declared else None
    blob = json.dumps(
        {"candidate": candidate, "stage": stage, "decode": decode, "runtimeArtifact": runtime_artifact},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def summary_path(results: Path, candidate: dict[str, Any], stage: str, decode: str = "normal") -> Path:
    if candidate.get("runtime") == "vllm":
        return results / candidate["id"] / stage / decode / "summary.json"
    return results / candidate["id"] / stage / "summary.json"


def resolve_link(raw: Any, *, results_dir: Path, base: Path) -> Path:
    """Resolve a recorded artifact path onto this machine for hashing."""
    candidate = Path(str(raw))
    if candidate.is_absolute():
        return candidate
    for root in (base, results_dir):
        probe = root / candidate
        if probe.exists():
            return probe
    return base / candidate


def resolve_result_link(raw: Any, *, result_file: Path) -> Path:
    """Resolve a result-declared sidecar exactly, with no search-root fallback.

    A relative context receipt path is relative to the result artifact that names
    it. This avoids accidentally accepting a same-named receipt from the summary
    directory or results root when the declared file is absent.
    """
    candidate = Path(str(raw)).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    result_root = result_file.parent.resolve()
    resolved = (result_root / candidate).resolve()
    try:
        resolved.relative_to(result_root)
    except ValueError as exc:
        raise ValueError("relative context-budget receipt path escapes the raw-result directory") from exc
    return resolved


def verify_context_budget(
    *,
    result_file: Path | None,
    result_payload: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Verify the exact tokenizer/template budget receipt named by a result.

    The raw result hash binds the receipt reference; this check binds that
    reference to the sidecar bytes and validates the sidecar's own canonical
    digest. The returned identity digest covers the tokenizer, prompt mode,
    effective limit and thinking-capability evidence.
    """
    codes: list[str] = []
    details: list[str] = []

    def fail(code: str, detail: str | None = None) -> None:
        if code not in codes:
            codes.append(code)
        if detail:
            details.append(detail)

    if result_file is None or not isinstance(result_payload, dict):
        fail("context_budget_receipt_missing", "raw result is unavailable for context-budget verification")
        return {"status": "failed", "codes": codes, "details": details}

    reference = result_payload.get("contextBudget")
    if not isinstance(reference, dict):
        fail("context_budget_receipt_missing", "raw result has no contextBudget receipt reference")
        return {"status": "failed", "codes": codes, "details": details}

    receipt_path_raw = reference.get("receiptPath")
    receipt_sha_raw = reference.get("receiptSha256")
    if not receipt_path_raw or not receipt_sha_raw:
        fail(
            "context_budget_receipt_missing",
            "raw result contextBudget must include receiptPath and receiptSha256",
        )
        return {"status": "failed", "codes": codes, "details": details}

    try:
        receipt_file = resolve_result_link(receipt_path_raw, result_file=result_file)
    except (OSError, RuntimeError, ValueError) as exc:
        fail("context_budget_receipt_path_invalid", f"invalid context-budget receipt path: {exc}")
        return {"status": "failed", "codes": codes, "details": details}
    if not receipt_file.is_file():
        fail("context_budget_receipt_missing", f"context-budget receipt not found: {receipt_file}")
        return {"status": "failed", "codes": codes, "details": details}

    try:
        receipt_bytes = receipt_file.read_bytes()
        file_sha = hashlib.sha256(receipt_bytes).hexdigest()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail("context_budget_receipt_invalid", f"cannot read context-budget receipt {receipt_file}: {exc}")
        return {"status": "failed", "codes": codes, "details": details}
    if not isinstance(receipt, dict):
        fail("context_budget_receipt_invalid", "context-budget receipt is not a JSON object")
        return {"status": "failed", "codes": codes, "details": details}

    recorded_receipt_sha = receipt.get("receiptSha256")
    if not isinstance(recorded_receipt_sha, str) or len(recorded_receipt_sha) != 64:
        fail("context_budget_receipt_hash_missing", "context-budget receipt has no SHA-256 self-hash")
    else:
        payload = {key: value for key, value in receipt.items() if key != "receiptSha256"}
        actual_receipt_sha = canonical_json_sha256(payload)
        if actual_receipt_sha.lower() != recorded_receipt_sha.lower():
            fail(
                "context_budget_receipt_hash_mismatch",
                f"context-budget receipt {receipt_file} canonical hash is {actual_receipt_sha}, "
                f"receipt records {recorded_receipt_sha}",
            )
    if str(receipt_sha_raw).lower() != str(recorded_receipt_sha or "").lower():
        fail(
            "context_budget_receipt_reference_mismatch",
            f"raw result records context-budget hash {receipt_sha_raw}, receipt records {recorded_receipt_sha}",
        )

    if receipt.get("schemaVersion") != 1:
        fail("context_budget_schema_mismatch", f"unsupported context-budget schemaVersion {receipt.get('schemaVersion')!r}")
    if receipt.get("state") != "context_qualified" or receipt.get("violatingTaskIds"):
        fail(
            "context_budget_unqualified",
            f"context-budget receipt state={receipt.get('state')!r}, violatingTaskIds={receipt.get('violatingTaskIds')!r}",
        )

    tokenizer = receipt.get("tokenizer")
    prompt_mode = receipt.get("promptMode")
    effective_limit = receipt.get("effectiveContextLimit")
    thinking = receipt.get("thinkingCapability")
    tasks = receipt.get("tasks")
    if (
        not isinstance(tokenizer, dict)
        or not tokenizer.get("repoOrName")
        or not tokenizer.get("revision")
        or not isinstance(prompt_mode, dict)
        or not prompt_mode.get("promptMode")
        or not isinstance(effective_limit, dict)
        or not isinstance(effective_limit.get("effectiveContextLimit"), int)
        or isinstance(effective_limit.get("effectiveContextLimit"), bool)
        or effective_limit.get("effectiveContextLimit", 0) <= 0
        or not isinstance(thinking, dict)
        or not thinking.get("state")
        or not isinstance(tasks, list)
        or not tasks
    ):
        fail("context_budget_identity_missing", "context-budget receipt lacks tokenizer, prompt, limit, thinking, or task identity")
    else:
        model = result_payload.get("model")
        model = model if isinstance(model, dict) else {}
        result_prompt_mode = result_payload.get("promptModeRequested")
        if tokenizer.get("repoOrName") != model.get("repoOrName"):
            fail(
                "context_budget_model_identity_mismatch",
                f"receipt tokenizer repo {tokenizer.get('repoOrName')!r} != result model {model.get('repoOrName')!r}",
            )
        if tokenizer.get("revision") != model.get("revision") or model.get("revision") != candidate.get("revision"):
            fail(
                "context_budget_model_revision_mismatch",
                f"receipt tokenizer revision {tokenizer.get('revision')!r}, result revision {model.get('revision')!r}, "
                f"roster revision {candidate.get('revision')!r}",
            )
        if prompt_mode.get("promptMode") != result_prompt_mode:
            fail(
                "context_budget_prompt_mode_mismatch",
                f"receipt prompt mode {prompt_mode.get('promptMode')!r} != result promptModeRequested {result_prompt_mode!r}",
            )
        if reference.get("effectiveContextLimit") != effective_limit.get("effectiveContextLimit"):
            fail("context_budget_limit_mismatch", "result and context-budget receipt effective limits disagree")
        if reference.get("thinkingCapability") != thinking:
            fail("context_budget_thinking_mismatch", "result and context-budget receipt thinking capability disagree")

    identity = {
        "tokenizer": tokenizer,
        "promptMode": prompt_mode,
        "effectiveContextLimit": effective_limit,
        "thinkingCapability": thinking,
    }
    receipt_sha = str(recorded_receipt_sha or "")
    identity_sha = canonical_json_sha256(identity)
    receipt_path = str(receipt_file)
    fingerprint_sha = canonical_json_sha256({
        "receiptPath": receipt_path,
        "receiptSha256": receipt_sha,
        "receiptFileSha256": file_sha,
        "identitySha256": identity_sha,
    })
    return {
        "status": "failed" if codes else "verified",
        "codes": codes,
        "details": details,
        "receiptPath": receipt_path,
        "receiptSha256": receipt_sha,
        "receiptFileSha256": file_sha,
        "identitySha256": identity_sha,
        "fingerprintSha256": fingerprint_sha,
    }


def verify_promotion_gate(
    *,
    summary: dict[str, Any],
    summary_file: Path,
    stage: str,
    decode: str,
    status: str,
    expected_result_sha256: str | None,
    results_dir: Path,
) -> dict[str, Any]:
    """Require comparable Issue #62 promotion evidence for a completed full screen.

    A legacy/pre-#62 summary can carry a perfectly valid provenance chain and
    still say ``completed`` without ever having passed the canonical promotion
    validator -- that was exactly the Prism path #62 closed. Provenance
    integrity alone therefore cannot tell the two backends apart, so this check
    re-derives comparability from the shared gate's own preserved evidence:

    1. the summary's ``promotionGate`` block must satisfy
       ``kaggle_promotion_gate.gate_evidence_is_comparable``;
    2. the gate receipt it names must exist and satisfy the same contract
       independently, so the summary's claim cannot stand alone;
    3. the receipt must be for this exact stage/decode cell, at the current
       gate contract version;
    4. the receipt must bind this exact raw result digest, so a gate that ran
       against different bytes cannot vouch for these bytes;
    5. its diagnostics and validator receipts must both record a ``passed``
       decision, and the validator's preserved report must still hash to the
       digest the receipt recorded.

    Every failure is a fail-closed comparability failure, never a re-labelling
    of an honest runtime or benchmark failure: cells that are not a completed
    full-screen normal-decode return ``not_required`` untouched.
    """
    codes: list[str] = []
    details: list[str] = []

    def fail(code: str, detail: str | None = None) -> None:
        if code not in codes:
            codes.append(code)
        if detail:
            details.append(detail)

    def verdict(**extra: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "required": True,
            "status": "failed" if codes else "verified",
            "comparable": not codes,
            "codes": codes,
            "details": details,
            "gateReceiptPath": None,
            "gateReceiptFileSha256": None,
            "validatorReportSha256": None,
        }
        base.update(extra)
        return base

    if not promotion_gate_required(stage, decode, status):
        return {
            "required": False,
            "status": "not_required",
            "comparable": None,
            "codes": [],
            "details": [],
            "gateReceiptPath": None,
            "gateReceiptFileSha256": None,
            "validatorReportSha256": None,
        }

    block = summary.get("promotionGate")
    if not isinstance(block, dict) or not block:
        fail(
            "promotion_gate_missing",
            f"summary {summary_file} claims completed for stage {stage!r}/decode {decode!r} "
            "but records no shared promotion-gate block; a pre-#62 completion that "
            "never ran the canonical validator is not promotion evidence",
        )
        return verdict()
    if not promotion_gate.gate_evidence_is_comparable(block):
        fail(
            "promotion_gate_not_comparable",
            f"summary promotionGate block is not comparable evidence "
            f"(status={block.get('status')!r} promotionGateApplied={block.get('promotionGateApplied')!r})",
        )
        return verdict()

    receipt_path_raw = summary.get("promotionGateReceiptPath") or block.get("receipt")
    if not receipt_path_raw:
        fail(
            "promotion_gate_receipt_missing",
            "summary promotion gate names no preserved gate receipt",
        )
        return verdict()
    receipt_file = resolve_link(receipt_path_raw, results_dir=results_dir, base=summary_file.parent)
    if not receipt_file.is_file():
        fail("promotion_gate_receipt_missing", f"promotion-gate receipt not found: {receipt_file}")
        return verdict(gateReceiptPath=str(receipt_file))
    try:
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(
            "promotion_gate_receipt_unreadable",
            f"cannot read promotion-gate receipt {receipt_file}: {exc}",
        )
        return verdict(gateReceiptPath=str(receipt_file))
    if not isinstance(receipt, dict):
        fail(
            "promotion_gate_receipt_unreadable",
            f"promotion-gate receipt {receipt_file} is not a JSON object",
        )
        return verdict(gateReceiptPath=str(receipt_file))

    receipt_sha = sha256_file(receipt_file)
    extra: dict[str, Any] = {
        "gateReceiptPath": str(receipt_file),
        "gateReceiptFileSha256": receipt_sha,
    }

    # The receipt must stand on its own: the summary's block is only a pointer.
    if not promotion_gate.gate_evidence_is_comparable(receipt):
        fail(
            "promotion_gate_receipt_not_comparable",
            f"preserved gate receipt {receipt_file} does not itself record a completed "
            f"shared gate (status={receipt.get('status')!r} "
            f"promotionGateApplied={receipt.get('promotionGateApplied')!r})",
        )
        return verdict(**extra)

    if receipt.get("schemaVersion") != promotion_gate.GATE_CONTRACT_VERSION:
        fail(
            "promotion_gate_receipt_version_mismatch",
            f"gate receipt {receipt_file} declares schemaVersion "
            f"{receipt.get('schemaVersion')!r}, not the current gate contract "
            f"{promotion_gate.GATE_CONTRACT_VERSION}",
        )
        return verdict(**extra)

    if receipt.get("stage") != stage or receipt.get("decode") != decode:
        fail(
            "promotion_gate_receipt_cell_mismatch",
            f"gate receipt {receipt_file} is for stage {receipt.get('stage')!r}/decode "
            f"{receipt.get('decode')!r}, not this cell's {stage!r}/{decode!r}",
        )
        return verdict(**extra)

    # Bind the gate to the exact raw result bytes this summary claims.
    bound_result = (receipt.get("resultArtifact") or {}).get("sha256")
    if not expected_result_sha256:
        fail(
            "promotion_gate_receipt_result_missing",
            "summary has no verified raw result digest for the gate receipt to bind",
        )
        return verdict(**extra)
    if not bound_result or str(bound_result).lower() != str(expected_result_sha256).lower():
        fail(
            "promotion_gate_receipt_result_mismatch",
            f"gate receipt {receipt_file} bound result digest {bound_result!r} does not match "
            f"the summary's verified raw result digest {expected_result_sha256!r}",
        )
        return verdict(**extra)

    # Both steps of the fixed gate order must have passed, in order.
    diagnostics = receipt.get("diagnosticsReceipt")
    validator = receipt.get("promotionValidatorReceipt")
    if not isinstance(diagnostics, dict) or diagnostics.get("decision") != "passed":
        fail(
            "promotion_gate_diagnostics_not_passed",
            f"gate receipt {receipt_file} does not record passed protocol diagnostics",
        )
        return verdict(**extra)
    if not isinstance(validator, dict) or validator.get("decision") != "passed":
        fail(
            "promotion_gate_validator_not_passed",
            f"gate receipt {receipt_file} does not record a passed canonical promotion validator",
        )
        return verdict(**extra)

    # The validator report is the proof behind the receipt, so it must still be
    # preserved and still hash to what the receipt recorded.
    report_path_raw = validator.get("report")
    report_sha = validator.get("reportSha256")
    if not report_path_raw or not report_sha:
        fail(
            "promotion_gate_validator_report_missing",
            f"gate receipt {receipt_file} records no preserved validator report digest",
        )
        return verdict(**extra)
    report_file = resolve_link(report_path_raw, results_dir=results_dir, base=receipt_file.parent)
    if not report_file.is_file():
        fail(
            "promotion_gate_validator_report_missing",
            f"preserved promotion-validator report not found: {report_file}",
        )
        return verdict(**extra)
    actual_report_sha = sha256_file(report_file)
    if not actual_report_sha or actual_report_sha.lower() != str(report_sha).lower():
        fail(
            "promotion_gate_validator_report_drifted",
            f"preserved promotion-validator report {report_file} now hashes "
            f"{actual_report_sha!r}, but the gate receipt recorded {report_sha!r}",
        )
        return verdict(**extra)

    return verdict(validatorReportSha256=actual_report_sha, **extra)


def normalize_task_entries(raw: Any) -> list[dict[str, Any]]:
    """Normalize recorded task manifests into deterministic ordered entries."""
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw or []):
        if isinstance(item, str):
            entries.append({"role": item, "path": item, "sha256": None})
        elif isinstance(item, dict):
            path = item.get("path") or item.get("file")
            entries.append({
                "role": str(item.get("role") or item.get("id") or path or f"task{index:02d}"),
                "path": path,
                "sha256": item.get("sha256") or item.get("digest"),
            })
    return entries


def canonical_task_order(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda e: (e.get("role") or "", e.get("path") or ""))


def snake(name: str) -> str:
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def not_applicable_state(path: Path, status: str, reason: str) -> dict[str, Any]:
    """A stage that is intentionally out of scope for this candidate's phase."""
    return {
        "status": status,
        "summary": str(path),
        "result": None,
        "stableBatchSize": None,
        "terminalFailureCategories": [],
        "protocolDiagnostics": None,
        "required": False,
        "reason": reason,
        "provenance": {
            "status": status,
            "comparable": False,
            "codes": [reason],
            "details": [],
            "recorded": {},
        },
    }


def finalist_set_errors(
    payload: Any,
    *,
    candidates_by_id: dict[str, dict[str, Any]],
    expected_benchmark_revision: str | None,
    results_dir: Path,
) -> list[str]:
    """Validate a frozen finalist-set artifact, failing closed on any doubt.

    Finalist identity is an explicit decision, so every reference must resolve:
    unknown candidates, revision/config drift and unresolvable source screen
    hashes are reported rather than silently ignored.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["finalist_set_not_an_object"]

    revision = payload.get("benchmarkRevision")
    if not revision:
        errors.append("finalist_set_missing_benchmark_revision")
    elif expected_benchmark_revision and revision != expected_benchmark_revision:
        errors.append(
            f"finalist_set_benchmark_revision_mismatch:{revision}!={expected_benchmark_revision}"
        )

    entries = payload.get("finalists")
    if not isinstance(entries, list) or not entries:
        errors.append("finalist_set_missing_finalists")
        return errors

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"finalist_entry_not_an_object:{index}")
            continue
        candidate_id = entry.get("candidate")
        if not candidate_id:
            errors.append(f"finalist_entry_missing_candidate:{index}")
            continue
        if candidate_id in seen:
            errors.append(f"finalist_entry_duplicate:{candidate_id}")
        seen.add(str(candidate_id))
        candidate = candidates_by_id.get(str(candidate_id))
        if candidate is None:
            errors.append(f"finalist_unknown_candidate:{candidate_id}")
            continue

        recorded_config = entry.get("candidateConfigSha256")
        expected_config = stage_config_digest(candidate, "full", "normal")
        if not recorded_config:
            errors.append(f"finalist_missing_candidate_config_sha256:{candidate_id}")
        elif recorded_config != expected_config:
            errors.append(f"finalist_candidate_config_sha256_mismatch:{candidate_id}")

        recorded_candidate_revision = entry.get("candidateRevision")
        if recorded_candidate_revision and recorded_candidate_revision != candidate.get("revision"):
            errors.append(f"finalist_candidate_revision_mismatch:{candidate_id}")

        screen = entry.get("screenResult") or {}
        screen_sha = screen.get("sha256") if isinstance(screen, dict) else None
        screen_path = screen.get("path") if isinstance(screen, dict) else None
        if not screen_sha or not screen_path:
            errors.append(f"finalist_missing_screen_result:{candidate_id}")
        else:
            resolved = resolve_link(screen_path, results_dir=results_dir, base=results_dir)
            if not resolved.is_file():
                errors.append(f"finalist_screen_result_not_found:{candidate_id}")
            elif sha256_file(resolved).lower() != str(screen_sha).lower():
                errors.append(f"finalist_screen_result_hash_mismatch:{candidate_id}")
    return errors


def load_finalists(
    finalist_set_path: Path | None,
    *,
    candidates_by_id: dict[str, dict[str, Any]],
    expected_benchmark_revision: str | None,
    results_dir: Path,
) -> dict[str, Any]:
    """Load and validate the explicit finalist decision, if one was supplied."""
    if finalist_set_path is None:
        return {"present": False, "path": None, "sha256": None, "finalists": [], "errors": []}
    if not finalist_set_path.is_file():
        return {
            "present": False,
            "path": str(finalist_set_path),
            "sha256": None,
            "finalists": [],
            "errors": [f"finalist_set_missing:{finalist_set_path}"],
        }
    payload = load(finalist_set_path)
    errors = finalist_set_errors(
        payload,
        candidates_by_id=candidates_by_id,
        expected_benchmark_revision=expected_benchmark_revision,
        results_dir=results_dir,
    )
    finalists: list[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("finalists"), list):
        finalists = [str(e.get("candidate")) for e in payload["finalists"] if isinstance(e, dict) and e.get("candidate")]
    return {
        "present": True,
        "path": str(finalist_set_path),
        "sha256": sha256_file(finalist_set_path),
        "benchmarkRevision": (payload or {}).get("benchmarkRevision") if isinstance(payload, dict) else None,
        "decidedAtUtc": (payload or {}).get("decidedAtUtc") if isinstance(payload, dict) else None,
        "finalists": sorted(set(finalists)) if not errors else [],
        "errors": errors,
    }


def not_run_state(path: Path) -> dict[str, Any]:
    return {
        "status": "not_run",
        "summary": str(path),
        "result": None,
        "stableBatchSize": None,
        "terminalFailureCategories": [],
        "protocolDiagnostics": None,
        "required": None,
        "reason": None,
        "provenance": {
            "status": "not_run",
            "comparable": False,
            "codes": ["stage_not_run"],
            "details": [],
            "recorded": {},
        },
    }


def verify_provenance(
    *,
    summary: dict[str, Any],
    summary_file: Path,
    candidate: dict[str, Any],
    stage: str,
    decode: str,
    results_dir: Path,
    expected_benchmark_revision: str | None,
) -> dict[str, Any]:
    """Validate one candidate-stage summary against the artifacts it links."""
    codes: list[str] = []
    details: list[str] = []
    base = summary_file.parent
    status = str(summary.get("status", "unknown"))

    def fail(code: str, detail: str | None = None) -> None:
        if code not in codes:
            codes.append(code)
        if detail:
            details.append(detail)

    def finish(kind: str) -> dict[str, Any]:
        return {
            "status": kind,
            "comparable": kind == "verified" and status == "completed",
            "codes": codes,
            "details": details,
            # Populated by verify_promotion_gate on the full measured path. The
            # early returns above describe a cell that never reached that check,
            # so the key is present and explicitly "not required" rather than
            # absent, keeping the report shape stable for every consumer.
            "promotionGate": {
                "required": False,
                "status": "not_required",
                "comparable": None,
                "codes": [],
                "details": [],
                "gateReceiptPath": None,
                "gateReceiptFileSha256": None,
                "validatorReportSha256": None,
            },
        }

    if status in PROVENANCE_EXEMPT_STATUSES:
        fail("provenance_exempt_before_measurement", f"summary status {status!r} never reached a measured state")
        return finish("exempt")

    provenance = summary.get("provenance")
    if not isinstance(provenance, dict) or not provenance:
        fail(
            "provenance_block_missing",
            f"{summary_file} has no provenance block; environment/runtime/task linkage is unprovable",
        )
        return finish("unverified")

    # ---- benchmark revision linkage --------------------------------------
    recorded_revision = provenance.get("benchmarkRevision")
    summary_revision = summary.get("benchmarkRevision")
    if not recorded_revision:
        fail("benchmark_revision_missing", "provenance has no benchmarkRevision")
    if summary_revision and recorded_revision and summary_revision != recorded_revision:
        fail(
            "benchmark_revision_mismatch",
            f"summary benchmarkRevision {summary_revision!r} != provenance {recorded_revision!r}",
        )
    if expected_benchmark_revision and recorded_revision != expected_benchmark_revision:
        fail(
            "benchmark_revision_mismatch",
            f"provenance benchmarkRevision {recorded_revision!r} != expected {expected_benchmark_revision!r}",
        )

    # ---- candidate identity / revision / config linkage ------------------
    embedded = summary.get("candidate")
    embedded = embedded if isinstance(embedded, dict) else {}
    if embedded.get("id") and embedded.get("id") != candidate.get("id"):
        fail(
            "candidate_identity_mismatch",
            f"summary embeds candidate {embedded.get('id')!r} but the roster row is {candidate.get('id')!r}",
        )

    recorded_candidate_revision = provenance.get("candidateRevision")
    if recorded_candidate_revision != candidate.get("revision"):
        fail(
            "candidate_revision_mismatch",
            f"provenance candidateRevision {recorded_candidate_revision!r} != roster {candidate.get('revision')!r}",
        )
    if embedded.get("revision") and embedded["revision"] != recorded_candidate_revision:
        fail(
            "candidate_revision_mismatch",
            f"embedded candidate revision {embedded['revision']!r} != provenance {recorded_candidate_revision!r}",
        )

    expected_roster_digest = candidate_config_digest(candidate)
    if embedded and candidate_config_digest(embedded) != expected_roster_digest:
        fail(
            "candidate_config_mismatch",
            f"embedded candidate row digest {candidate_config_digest(embedded)} != roster row digest "
            f"{expected_roster_digest}",
        )

    expected_config = stage_config_digest(candidate, stage, decode)
    recorded_config = provenance.get("candidateConfigSha256")
    if not recorded_config:
        fail("candidate_config_missing", "provenance has no candidateConfigSha256")
    elif recorded_config != expected_config:
        fail(
            "candidate_config_mismatch",
            f"provenance candidateConfigSha256 {recorded_config} != stage-config digest {expected_config}",
        )

    # ---- preflight artifact linkage --------------------------------------
    preflight_path_raw = provenance.get("preflightPath")
    preflight_sha = provenance.get("preflightSha256")
    if not preflight_sha or not preflight_path_raw:
        fail(
            "preflight_receipt_missing",
            "provenance does not link a preflight artifact (preflightPath + preflightSha256)",
        )
    else:
        preflight_file = resolve_link(preflight_path_raw, results_dir=results_dir, base=base)
        if not preflight_file.is_file():
            fail("preflight_receipt_missing", f"preflight artifact not found: {preflight_file}")
        else:
            actual = sha256_file(preflight_file)
            if actual.lower() != str(preflight_sha).lower():
                fail(
                    "preflight_receipt_hash_mismatch",
                    f"preflight {preflight_file} now hashes {actual}, summary recorded {preflight_sha}",
                )

    # ---- pinned runtime install receipt linkage --------------------------
    # Required for every written summary, ordinary decode or attempted MTP. If an
    # MTP method was never attempted there is no summary for that decode, so no
    # MTP receipt requirement is invented for it.
    runtime_path_raw = provenance.get("runtimeReceiptPath")
    runtime_sha = provenance.get("runtimeReceiptSha256")
    if not runtime_sha or not runtime_path_raw:
        fail(
            "runtime_receipt_missing",
            "provenance does not link a pinned runtime receipt (runtimeReceiptPath + runtimeReceiptSha256)",
        )
    else:
        runtime_file = resolve_link(runtime_path_raw, results_dir=results_dir, base=base)
        if not runtime_file.is_file():
            fail("runtime_receipt_missing", f"pinned runtime receipt not found: {runtime_file}")
        else:
            actual = sha256_file(runtime_file)
            if actual.lower() != str(runtime_sha).lower():
                fail(
                    "runtime_receipt_hash_mismatch",
                    f"runtime receipt {runtime_file} now hashes {actual}, summary recorded {runtime_sha}",
                )

    # ---- frozen task artifact linkage ------------------------------------
    entries = normalize_task_entries(provenance.get("taskManifestSha256s"))
    if not entries:
        fail("task_manifest_missing", "provenance has no taskManifestSha256s for this stage")
    else:
        if entries != canonical_task_order(entries):
            fail(
                "task_manifest_order_nondeterministic",
                "taskManifestSha256s must be recorded in deterministic (role, path) order",
            )
        for entry in entries:
            entry_path = entry.get("path")
            entry_sha = entry.get("sha256")
            if not entry_path or not entry_sha:
                fail("task_manifest_missing", f"task manifest entry lacks path/sha256: {entry!r}")
                continue
            task_file = resolve_link(entry_path, results_dir=results_dir, base=base)
            if not task_file.is_file():
                fail("task_manifest_missing", f"frozen task artifact not found: {task_file}")
                continue
            actual = sha256_file(task_file)
            if actual.lower() != str(entry_sha).lower():
                fail(
                    "task_manifest_hash_mismatch",
                    f"frozen task {task_file} now hashes {actual}, summary recorded {entry_sha}",
                )
        declared_files = provenance.get("taskFiles")
        if isinstance(declared_files, list) and declared_files:
            declared = {str(p) for p in declared_files}
            manifested = {str(e.get("path")) for e in entries}
            if declared != manifested:
                fail(
                    "task_manifest_missing",
                    "provenance taskFiles does not match the taskManifestSha256s paths",
                )

    # ---- raw result artifact linkage -------------------------------------
    result_sha = provenance.get("resultSha256")
    result_raw = provenance.get("resultPath") or summary.get("result")
    result_file: Path | None = None
    result_payload: dict[str, Any] | None = None
    actual_result_sha: str | None = None
    if result_sha:
        if not result_raw:
            fail("raw_result_missing", "provenance has resultSha256 but no result path")
        else:
            result_file = resolve_link(result_raw, results_dir=results_dir, base=base)
            if not result_file.is_file():
                fail("raw_result_missing", f"raw result artifact not found: {result_file}")
            else:
                actual_result_sha = sha256_file(result_file)
                if actual_result_sha.lower() != str(result_sha).lower():
                    fail(
                        "raw_result_hash_mismatch",
                        f"raw result {result_file} now hashes {actual_result_sha}, summary recorded {result_sha}",
                    )
                try:
                    loaded_result = json.loads(result_file.read_text(encoding="utf-8"))
                    if isinstance(loaded_result, dict):
                        result_payload = loaded_result
                    else:
                        fail("raw_result_invalid", f"raw result {result_file} is not a JSON object")
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    fail("raw_result_invalid", f"cannot read raw result {result_file}: {exc}")
    elif result_raw:
        fail("raw_result_missing", "summary records a result path but provenance has no resultSha256")

    # An inference artifact must carry the exact context receipt it was run
    # against. Startup failures that never produced a result remain visible as
    # runtime history, but any result-bearing summary without the receipt is
    # ineligible for comparison.
    needs_context_budget = bool(result_raw) or status in {"completed", "inference_completed"}
    context_budget: dict[str, Any] = {
        "status": "not_applicable",
        "codes": [],
        "details": [],
    }
    if needs_context_budget:
        context_budget = verify_context_budget(
            result_file=result_file if result_file and result_file.is_file() else None,
            result_payload=result_payload,
            candidate=candidate,
        )
        for code in context_budget.get("codes", []):
            fail(str(code), None)
        details.extend(str(detail) for detail in context_budget.get("details", []))
        # Check that the raw result did not change while its sidecar was being
        # read and validated.
        if result_file and result_file.is_file() and actual_result_sha:
            after_context_sha = sha256_file(result_file)
            if after_context_sha.lower() != actual_result_sha.lower():
                fail(
                    "raw_result_changed_during_verification",
                    f"raw result {result_file} changed while its context receipt was checked",
                )

    if status not in PROVENANCE_REQUIRED_STATUSES:
        fail("provenance_exempt_unknown_status", f"summary status {status!r} is not a declared terminal state")
        return finish("unverified")

    # Issue #62/#39: a completed full-screen cell is only comparable if the
    # shared runtime-neutral promotion gate actually ran and passed over these
    # exact result bytes. This runs after the artifact chain is settled so the
    # gate can bind the already-verified raw result digest, and it fires only
    # for that one cell, so runtime-unqualified and benchmark-failure rows keep
    # their existing verdicts untouched.
    promotion_gate_verdict = verify_promotion_gate(
        summary=summary,
        summary_file=summary_file,
        stage=stage,
        decode=decode,
        status=status,
        expected_result_sha256=result_sha,
        results_dir=results_dir,
    )
    for code in promotion_gate_verdict.get("codes", []):
        fail(str(code), None)
    details.extend(str(detail) for detail in promotion_gate_verdict.get("details", []))

    kind = "failed" if codes else "verified"
    verified = finish(kind)
    verified["contextBudget"] = context_budget
    verified["promotionGate"] = promotion_gate_verdict
    if kind == "verified" and context_budget.get("status") == "verified":
        verified["fingerprintSha256"] = canonical_json_sha256({
            "benchmarkRevision": recorded_revision,
            "candidateRevision": recorded_candidate_revision,
            "candidateConfigSha256": recorded_config,
            "preflightSha256": preflight_sha,
            "runtimeReceiptSha256": runtime_sha,
            "taskManifestSha256s": canonical_task_order(entries),
            "resultSha256": result_sha,
            "contextBudget": {
                "receiptPath": context_budget.get("receiptPath"),
                "receiptSha256": context_budget.get("receiptSha256"),
                "receiptFileSha256": context_budget.get("receiptFileSha256"),
                "identitySha256": context_budget.get("identitySha256"),
            },
            # The gate receipt digest joins the fingerprint, so two candidates
            # screened under different terminal gates cannot share one
            # comparison fingerprint even when every other artifact matches.
            # A gate failure already forced kind="failed" above (its codes are
            # folded into the same list), so this block only needs the verified
            # values; non-required cells record nulls.
            "promotionGate": {
                "gateReceiptFileSha256": promotion_gate_verdict.get("gateReceiptFileSha256"),
                "validatorReportSha256": promotion_gate_verdict.get("validatorReportSha256"),
            },
        })
    else:
        verified["fingerprintSha256"] = None
    return verified


def state_for(
    path: Path,
    *,
    results_dir: Path,
    candidate: dict[str, Any],
    stage: str,
    decode: str,
    expected_benchmark_revision: str | None,
) -> dict[str, Any]:
    data = load(path)
    if data is None:
        return not_run_state(path)
    provenance = verify_provenance(
        summary=data,
        summary_file=path,
        candidate=candidate,
        stage=stage,
        decode=decode,
        results_dir=results_dir,
        expected_benchmark_revision=expected_benchmark_revision,
    )
    recorded = data.get("provenance")
    recorded = recorded if isinstance(recorded, dict) else {}
    return {
        "status": data.get("status", "unknown"),
        "summary": str(path),
        "result": data.get("result"),
        "stableBatchSize": data.get("stableBatchSize"),
        "terminalFailureCategories": data.get("terminalFailureCategories", []),
        "protocolDiagnostics": data.get("protocolDiagnostics"),
        "required": None,
        "reason": None,
        "provenance": provenance | {
            "recorded": {
                "benchmarkRevision": recorded.get("benchmarkRevision"),
                "candidateRevision": recorded.get("candidateRevision"),
                "candidateConfigSha256": recorded.get("candidateConfigSha256"),
                "preflightSha256": recorded.get("preflightSha256"),
                "runtimeReceiptSha256": recorded.get("runtimeReceiptSha256"),
                "resultSha256": recorded.get("resultSha256"),
                "parserCodeVersion": recorded.get("parserCodeVersion"),
                "taskManifestSha256s": normalize_task_entries(recorded.get("taskManifestSha256s")),
                # Verified from the raw result and its exact sidecar, not trusted
                # from the outer summary's provenance block.
                "contextBudgetReceiptPath": (provenance.get("contextBudget") or {}).get("receiptPath"),
                "contextBudgetReceiptSha256": (provenance.get("contextBudget") or {}).get("receiptSha256"),
                "contextBudgetReceiptFileSha256": (provenance.get("contextBudget") or {}).get("receiptFileSha256"),
                "contextBudgetIdentitySha256": (provenance.get("contextBudget") or {}).get("identitySha256"),
                "resultFingerprintSha256": provenance.get("fingerprintSha256"),
                # Issue #62: re-derived from the preserved gate receipt, not
                # trusted from the summary's own claim.
                "promotionGateReceiptPath": (provenance.get("promotionGate") or {}).get("gateReceiptPath"),
                "promotionGateReceiptFileSha256": (provenance.get("promotionGate") or {}).get("gateReceiptFileSha256"),
                "promotionGateValidatorReportSha256": (provenance.get("promotionGate") or {}).get("validatorReportSha256"),
            }
        },
    }


def cross_stage_conflicts(row: dict[str, Any]) -> list[str]:
    """Surface a candidate whose own stages disagree on shared provenance."""
    buckets: dict[str, set[str]] = {
        "preflight": set(),
        "runtimeReceipt": set(),
        "benchmarkRevision": set(),
        "candidateRevision": set(),
    }
    for stage in REQUIRED_STAGES:
        provenance = ((row.get(stage) or {}).get("provenance") or {})
        if provenance.get("status") in {"not_run", NON_FINALIST_STAGE_STATUS, NOT_APPLICABLE_AFTER_SCREEN}:
            continue
        recorded = provenance.get("recorded") or {}
        for key in buckets:
            value = recorded.get(f"{key}Sha256") or recorded.get(key)
            if value:
                buckets[key].add(str(value).lower())
    return [
        f"{snake(key)}_conflict_across_stages"
        for key in ("preflight", "runtimeReceipt", "benchmarkRevision", "candidateRevision")
        if len(buckets[key]) > 1
    ]


def comparable_group(row: dict[str, Any]) -> str | None:
    """Head-to-head grouping key, or None when the row is not comparable.

    Only a finalist with a complete product run may enter a product head-to-head.
    A screening row never groups: a screen is not a product comparison.
    """
    if row["provenanceFailures"] or row["provenanceConflicts"] or row["provenanceUnverified"]:
        return None
    if not row.get("finalist"):
        return None
    for stage in REQUIRED_STAGES:
        state = row[stage]
        if state["status"] != "completed" or not state["provenance"]["comparable"]:
            return None
    revision = (row[REQUIRED_STAGES[0]]["provenance"].get("recorded") or {}).get("benchmarkRevision")
    return f"benchmarkRevision={revision}" if revision else None


def screening_complete(row: dict[str, Any]) -> bool:
    """True when the candidate cleared every stage its screen actually requires."""
    smoke = row["smoke"]["status"]
    if smoke in RUNTIME_UNQUALIFIED_STATUSES:
        # A runtime that never loaded cannot be screened any further.
        return True
    if smoke != "completed":
        return False
    full = row["full"]["status"]
    if full in RUNTIME_UNQUALIFIED_STATUSES:
        return True
    return full == "completed"


def product_complete(row: dict[str, Any]) -> bool:
    if not row.get("finalist"):
        return False
    return all(row[stage]["status"] == "completed" for stage in PRODUCT_STAGES)


def mark_phase_states(
    row: dict[str, Any],
    *,
    candidate: dict[str, Any],
    results_dir: Path,
    finalist_set: dict[str, Any],
) -> None:
    """Rewrite out-of-scope stage cells into explicit lifecycle states."""
    row["finalist"] = bool(row["candidate"] in (finalist_set.get("finalists") or []))
    # Without an explicit decision artifact nobody is a finalist, and the roster
    # is still waiting on a decision. With an invalid artifact we fail closed
    # rather than guessing membership from whatever folders exist.
    row["finalistDecisionPending"] = not finalist_set["present"] and not row["finalist"]
    row["finalistSetErrors"] = list(finalist_set.get("errors") or [])

    runtime_unqualified = any(row[stage]["status"] in RUNTIME_UNQUALIFIED_STATUSES for stage in SCREEN_STAGES)
    for stage in REQUIRED_STAGES:
        state = row[stage]
        if state["status"] == "not_run" and stage in PRODUCT_STAGES and not row["finalist"]:
            reason = NOT_APPLICABLE_AFTER_SCREEN if runtime_unqualified else NON_FINALIST_STAGE_STATUS
            detail = (
                f"{stage} is finalist-only and the candidate is runtime-unqualified"
                if runtime_unqualified
                else f"{stage} is finalist-only and the candidate is not in the frozen finalist set"
            )
            row[stage] = not_applicable_state(summary_path(results_dir, candidate, stage), reason, detail)
            continue
        state["required"] = stage in SCREEN_STAGES or (row["finalist"] and stage in PRODUCT_STAGES)
        state["reason"] = None

    # MTP/spec is never required; an attempted method stays visible either way.
    for method, method_states in row["speculative"].items():
        for state in method_states.values():
            state["required"] = False
            if state["status"] == "not_run":
                state["reason"] = f"speculative method {method} was never attempted"


def disposition(row: dict[str, Any]) -> str:
    # Integrity failures dominate every other disposition: mismatched provenance
    # must never be presented as a pending quality comparison.
    if row["provenanceFailures"] or row["provenanceConflicts"]:
        return "provenance_failed"
    if row["provenanceUnverified"]:
        return "provenance_unverified"
    if row.get("finalistSetErrors"):
        return "finalist_set_blocked"
    states = [row[stage]["status"] for stage in REQUIRED_STAGES]
    if any(status in RUNTIME_UNQUALIFIED_STATUSES for status in states):
        return "runtime_unqualified"
    if any(
        status
        in {"benchmark_tool_failure", "benchmark_validation_failure", "benchmark_failed", "infrastructure_failed"}
        for status in states
    ):
        return "benchmark_blocked"

    if not screening_complete(row):
        # "never attempted" is a statement about the screening lane. Product
        # stages that are out of scope for a non-finalist are not attempts.
        return (
            "never_attempted"
            if all(row[stage]["status"] == "not_run" for stage in SCREEN_STAGES)
            else "screening_incomplete"
        )
    if row.get("finalistDecisionPending"):
        return "screen_complete_pending_finalist_selection"
    if not row.get("finalist"):
        # Screened out. The product suites were intentionally not run; any
        # product evidence that does exist stays visible and is not erased.
        return "screened_non_finalist"
    if product_complete(row):
        return "finalist_product_complete_pending_comparison"
    return "finalist_product_pending"


def build_report(
    results_dir: Path,
    expected_benchmark_revision: str | None,
    finalist_set_path: Path | None = None,
) -> dict[str, Any]:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    candidates_by_id = {row["id"]: row for row in roster["candidates"]}
    finalist_set = load_finalists(
        finalist_set_path,
        candidates_by_id=candidates_by_id,
        expected_benchmark_revision=expected_benchmark_revision,
        results_dir=results_dir,
    )
    rows: list[dict[str, Any]] = []
    for candidate in roster["candidates"]:
        row: dict[str, Any] = {
            "candidate": candidate["id"],
            "runtime": candidate.get("runtime"),
            "repo": candidate.get("repo"),
            "revision": candidate.get("revision"),
            "quantization": candidate.get("quantization"),
            "candidateConfigSha256": {
                stage: stage_config_digest(candidate, stage, "normal")
                for stage in REQUIRED_STAGES
            },
        }
        for stage in REQUIRED_STAGES:
            row[stage] = state_for(
                summary_path(results_dir, candidate, stage),
                results_dir=results_dir,
                candidate=candidate,
                stage=stage,
                decode="normal",
                expected_benchmark_revision=expected_benchmark_revision,
            )
        speculative = {}
        for method in candidate.get("mtpMethodsToProbe") or []:
            speculative[method] = {
                stage: state_for(
                    summary_path(results_dir, candidate, stage, method),
                    results_dir=results_dir,
                    candidate=candidate,
                    stage=stage,
                    decode=method,
                    expected_benchmark_revision=expected_benchmark_revision,
                )
                for stage in REQUIRED_STAGES
            }
        row["speculative"] = speculative

        # Issue #49: report the exact qualification gate reached instead of
        # collapsing the ladder into one ambiguous `smoke` cell.
        receipts: dict[str, Any] = {}
        for stage in REQUIRED_STAGES:
            gate = STAGE_GATES.get(stage)
            if not gate:
                continue
            spec = next(
                (e for e in QUALIFICATION_LADDER if e["gate"] == gate), None
            )
            if spec is None:
                continue
            # state_for returns the summary payload itself; `status` is its state.
            state = row[stage].get("status") if isinstance(row[stage], dict) else None
            receipts[str(spec["receiptKey"])] = {
                "gate": gate,
                "stage": stage,
                "summaryState": state,
                "status": "completed" if state == "completed" else str(state or "missing"),
                "provenanceStatus": row[stage].get("provenance", {}).get("status"),
            }
        completed = [
            str(entry["gate"])
            for entry in QUALIFICATION_LADDER
            if (receipts.get(str(entry["receiptKey"])) or {}).get("status") == "completed"
        ]
        row["qualification"] = {
            "stageManifestSha256": STAGE_MANIFEST_SHA256,
            "stageGates": dict(STAGE_GATES),
            "receipts": receipts,
            "gatesCompleted": completed,
            "highestGateReached": completed[-1] if completed else None,
            "gatesNotCompleted": [
                str(entry["gate"])
                for entry in QUALIFICATION_LADDER
                if str(entry["gate"]) not in completed
            ],
        }

        failures: list[str] = []
        unverified = False
        for stage in REQUIRED_STAGES:
            provenance = row[stage]["provenance"]
            if provenance["status"] == "failed":
                failures.extend(provenance["codes"])
            elif provenance["status"] == "unverified":
                unverified = True
        row["provenanceFailures"] = sorted(set(failures))
        row["provenanceConflicts"] = cross_stage_conflicts(row)
        row["provenanceUnverified"] = unverified and not row["provenanceFailures"]
        mark_phase_states(row, candidate=candidate, results_dir=results_dir, finalist_set=finalist_set)
        row["disposition"] = disposition(row)
        row["comparableGroup"] = comparable_group(row)
        rows.append(row)

    groups: dict[str, list[str]] = {}
    for row in rows:
        if row["comparableGroup"]:
            groups.setdefault(row["comparableGroup"], []).append(row["candidate"])

    excluded = [
        {
            "candidate": row["candidate"],
            "disposition": row["disposition"],
            "codes": (
                row["provenanceFailures"]
                or row["provenanceConflicts"]
                or row["finalistSetErrors"]
                or ["provenance_unverified"]
            ),
        }
        for row in rows
        if row["disposition"] in {"provenance_failed", "provenance_unverified", "finalist_set_blocked"}
    ]

    return {
        "version": 4,
        "resultsDir": str(results_dir),
        "expectedBenchmarkRevision": expected_benchmark_revision,
        "screeningStages": list(SCREEN_STAGES),
        "productStages": list(PRODUCT_STAGES),
        "requiredStages": list(REQUIRED_STAGES),
        "finalistSet": finalist_set,
        "rows": rows,
        "comparableGroups": groups,
        "excludedFromComparison": excluded,
        "counts": {
            status: sum(1 for row in rows if row["disposition"] == status)
            for status in sorted({row["disposition"] for row in rows})
        },
        "interpretation": [
            "This is a phase-aware completeness/runtime/provenance matrix, not a quality ranking.",
            "Every roster candidate stays visible at every phase; no cell is left blank.",
            "Screening is smoke + full. Word Studio product suites are finalist-only.",
            "Finalist membership comes only from the validated frozen finalist-set artifact.",
            "runtime_unqualified is not an English score of zero.",
            "Every result-bearing summary binds its exact context-budget receipt into resultFingerprintSha256.",
            "Only finalist rows sharing a comparableGroup may enter a product head-to-head comparison.",
            "A provenance mismatch is an integrity failure and is never converted into a quality score.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    headers = [
        "candidate", "runtime", "screen(smoke)", "screen(full)", "product(word-studio)",
        "product(transform)", "spec/MTP", "finalist", "provenance", "comparable", "disposition",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in report["rows"]:
        spec = ", ".join(f"{k}:{v['smoke']['status']}" for k, v in row["speculative"].items()) or "n/a"
        if all(row[stage]["status"] in {"not_run", NON_FINALIST_STAGE_STATUS, NOT_APPLICABLE_AFTER_SCREEN}
               for stage in REQUIRED_STAGES):
            provenance_cell = "n/a (not_run)"
        elif row["provenanceFailures"] or row["provenanceConflicts"]:
            provenance_cell = "failed: " + ",".join(row["provenanceFailures"] or row["provenanceConflicts"])
        elif row["provenanceUnverified"]:
            provenance_cell = "unverified"
        else:
            provenance_cell = "verified"
        lines.append("| " + " | ".join([
            row["candidate"], row["runtime"], row["smoke"]["status"], row["full"]["status"],
            row["word-studio"]["status"], row["transform"]["status"], spec,
            "yes" if row["finalist"] else ("pending" if row["finalistDecisionPending"] else "no"),
            provenance_cell,
            "yes" if row["comparableGroup"] else "no", row["disposition"],
        ]) + " |")
    return "# Kaggle candidate status matrix\n\n" + "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--json", type=Path, default=Path("/kaggle/working/results/candidate-matrix.json"))
    ap.add_argument("--markdown", type=Path, default=Path("/kaggle/working/results/candidate-matrix.md"))
    ap.add_argument(
        "--benchmark-revision",
        default=None,
        help="optional expected benchmark git revision; summaries at another revision are flagged",
    )
    ap.add_argument(
        "--finalist-set",
        type=Path,
        default=None,
        help=(
            "explicit frozen finalist decision (finalist-set.json); finalist membership is never "
            "inferred from which product result folders happen to exist"
        ),
    )
    args = ap.parse_args()

    report = build_report(args.results_dir, args.benchmark_revision, args.finalist_set)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "json": str(args.json),
        "markdown": str(args.markdown),
        "counts": report["counts"],
        "finalistSet": {
            "present": report["finalistSet"]["present"],
            "path": report["finalistSet"]["path"],
            "sha256": report["finalistSet"]["sha256"],
            "finalists": report["finalistSet"]["finalists"],
            "errors": report["finalistSet"]["errors"],
        },
        "comparableGroups": report["comparableGroups"],
        "excludedFromComparison": [row["candidate"] for row in report["excludedFromComparison"]],
    }, indent=2))


if __name__ == "__main__":
    main()
