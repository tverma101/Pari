#!/usr/bin/env python3
"""Runtime-neutral post-inference promotion gate for canonical runs (Issue #62).

Before this module the two canonical wrappers each carried their own
post-inference branch, and the branches had drifted: the vLLM wrapper ran the
promotion validator for ``stage=full``/``decode=normal`` and refused to mark
``completed`` without it, while the Prism wrapper ran protocol diagnostics and
then marked ``completed`` unconditionally. A Prism full-screen result could
therefore enter the candidate matrix as ``completed`` under a strictly weaker
acceptance path than the vLLM evidence beside it, and ``completed`` stopped
meaning one thing.

This module is the single runtime-neutral path both wrappers now consume. It is
runtime-neutral by construction: it knows nothing about vLLM, llama.cpp, batch
ladders or GPUs. It is handed a stable raw result artifact plus the provenance
identities already bound by the wrapper, and it decides one terminal status:

``completed``
    Protocol diagnostics passed and, for a canonical full-screen normal-decode
    result, the one canonical promotion validator passed.
``benchmark_validation_failure``
    The tooling ran and reported that the evidence itself is not promotion- or
    comparability-valid (structural protocol failure, or a promotion validator
    report carrying errors). The raw result still exists.
``benchmark_tool_failure``
    The validator or diagnostic tooling itself could not produce a decision
    (missing/unrunnable executable, crash, or output that is not a parseable
    report). This is deliberately *not* ``runtime_unqualified``: inference ran
    fine, and an English score zero would be a lie.
``runtime_unqualified``
    Inference environment/configuration could not run at all. Wrappers reach
    this state themselves before inference; it is declared here only so the
    status vocabulary has exactly one definition, and a gate result can never
    be confused with a runtime failure.

Every gate run binds and preserves a receipt (``promotion-gate.json`` plus one
receipt per tool) covering:

* the exact task manifest and its SHA-256 (#48);
* the benchmark revision / tree identity the evidence claims (#40);
* candidate, runtime and model-artifact provenance (#33/#41);
* parser and protocol version, as the content digest of the exact tool sources
  that judged the result (#44);
* the result artifact's SHA-256;
* the applicable context-budget receipt (#45), read from the result payload so
  the binding follows the evidence rather than a wrapper argument;
* the validator/diagnostic command, tool SHA-256, return code and preserved
  log.

The gate re-reads the preserved tool reports from disk before trusting their
verdict, so a receipt can never claim a pass that its own bound report does not
support.

This module imports stdlib only. It never imports torch, vLLM or llama.cpp, so
the CPU-only parity tests and the structural self-checks can import it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
DIAGNOSTICS = HERE / "protocol_output_diagnostics.py"
VALIDATOR = HERE / "validate-english-core-run.py"
RESULT_SCHEMA = HERE / "english-core-result-schema.json"

#: The exact tool sources whose bytes decide a result. The gate hashes these and
#: records the digest in every receipt, so a ``completed`` status is always
#: attributable to a specific validator/diagnostics implementation (#44).
GATE_TOOL_SOURCES: tuple[Path, ...] = (DIAGNOSTICS, VALIDATOR)

GATE_CONTRACT_VERSION = 1

#: The one full-screen normal-decode combination that carries the canonical
#: promotion contract. Everything else is gated by protocol diagnostics only,
#: which is what both wrappers did for non-full stages before this module.
PROMOTION_STAGE = "full"
PROMOTION_DECODE = "normal"

# --- terminal statuses ------------------------------------------------------
COMPLETED = "completed"
BENCHMARK_VALIDATION_FAILURE = "benchmark_validation_failure"
BENCHMARK_TOOL_FAILURE = "benchmark_tool_failure"
RUNTIME_UNQUALIFIED = "runtime_unqualified"

#: The complete terminal vocabulary of this gate. ``completed`` is only ever
#: reached through :func:`run_post_inference_gate`, so wrapper choice cannot
#: change what it means.
TERMINAL_STATUSES: frozenset[str] = frozenset({
    COMPLETED,
    BENCHMARK_VALIDATION_FAILURE,
    BENCHMARK_TOOL_FAILURE,
    RUNTIME_UNQUALIFIED,
})

#: Process exit code per terminal status. 0 is reserved for ``completed`` so a
#: caller that only inspects the exit code still cannot read a failed gate as
#: success. Every non-completed terminal status is a hard non-zero exit.
TERMINAL_EXIT_CODES: dict[str, int] = {
    COMPLETED: 0,
    BENCHMARK_VALIDATION_FAILURE: 2,
    BENCHMARK_TOOL_FAILURE: 3,
    RUNTIME_UNQUALIFIED: 4,
}

STATUS_SEMANTICS: dict[str, str] = {
    COMPLETED: "all required validators passed; the evidence is promotion/comparability valid",
    BENCHMARK_VALIDATION_FAILURE: (
        "the raw result exists but promotion/comparability validation rejected it; "
        "this is not an English score zero and not a runtime failure"
    ),
    BENCHMARK_TOOL_FAILURE: (
        "validator/diagnostic tooling could not produce a decision; the evidence is "
        "unresolved rather than invalid, and inference itself is not implicated"
    ),
    RUNTIME_UNQUALIFIED: (
        "inference environment/configuration could not run; wrappers reach this "
        "before inference and this gate never emits it"
    ),
}

GATE_RECEIPT_FILENAME = "promotion-gate.json"
DIAGNOSTICS_RECEIPT_FILENAME = "protocol-diagnostics.json"
DIAGNOSTICS_LOG_FILENAME = "protocol-diagnostics.log.txt"
PROMOTION_RECEIPT_FILENAME = "promotion-validation.json"
PROMOTION_LOG_FILENAME = "promotion-validation.log.txt"


class GateToolError(RuntimeError):
    """Raised when the gate itself cannot run a required tool.

    ``step`` names which tool failed so the caller can record *which* receipt is
    missing, and ``detail`` carries any evidence already recovered.
    """

    def __init__(self, step: str, reason: str, *, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason
        self.detail = dict(detail or {})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path | str | None) -> str | None:
    """SHA-256 of a file's bytes, or ``None`` when it cannot be read."""
    if path is None:
        return None
    p = Path(path)
    try:
        digest = hashlib.sha256()
        with p.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def tool_code_version(paths: Sequence[Path | str]) -> str:
    """Content digest of the tool sources that judge a result set (#44).

    Stable across directories and across copies of the benchmark tree, because
    only the basenames and content digests participate.
    """
    digests = []
    for raw in sorted({Path(p) for p in paths}, key=lambda item: item.name):
        digest = sha256_file(raw)
        if digest is not None:
            digests.append({"source": raw.name, "sha256": digest})
    if not digests:
        return "unavailable"
    primary = sorted(digests, key=lambda d: d["source"])[0]["source"]
    return f"{primary}+{sha256_json(digests)}"


def terminal_exit_code(status: str) -> int:
    """Exit code for a terminal status (0 only for ``completed``)."""
    if status not in TERMINAL_EXIT_CODES:
        raise GateToolError("status", f"unknown terminal status {status!r}")
    return TERMINAL_EXIT_CODES[status]


@dataclass(frozen=True)
class GateProvenance:
    """Runtime-neutral provenance a wrapper binds before the gate runs.

    Every field is something both wrappers can supply without knowing anything
    about the other's runtime. ``task_identity`` is the wrapper's resolved
    stage identity when it has one (Issue #48), carried through verbatim.
    """

    stage: str
    decode: str
    candidate: Mapping[str, Any]
    benchmark_revision: str
    result_path: Path
    tasks_path: Path
    runtime: str
    task_identity: Mapping[str, Any] | None = None
    model_artifact: Mapping[str, Any] | None = None
    runtime_environment: Mapping[str, Any] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def requires_promotion(self) -> bool:
        return self.stage == PROMOTION_STAGE and self.decode == PROMOTION_DECODE


@dataclass(frozen=True)
class ToolReceipt:
    """One tool invocation: what ran, which bytes ran, and what it decided."""

    tool: str
    command: list[str]
    exit_code: int
    log_path: str
    report_path: str | None
    report_sha256: str | None
    tool_sha256: str | None
    decision: str
    stdout_tail: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool": self.tool,
            "command": list(self.command),
            "returnCode": self.exit_code,
            "log": self.log_path,
            "report": self.report_path,
            "reportSha256": self.report_sha256,
            "toolSha256": self.tool_sha256,
            "decision": self.decision,
            # Issue #62 requires the return code and log to be preserved with the
            # validator receipt, so the receipt never points at a path alone.
            "logSha256": sha256_file(self.log_path),
        }
        if self.stdout_tail is not None:
            payload["stdoutTail"] = self.stdout_tail
        if self.detail:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass(frozen=True)
class GateOutcome:
    """The one terminal decision plus the receipts that justify it."""

    status: str
    exit_code: int
    reason: str
    failed_step: str | None = None
    result_path: str | None = None
    diagnostics_receipt_path: str | None = None
    promotion_receipt_path: str | None = None
    promotion_log_path: str | None = None
    gate_receipt_path: str | None = None
    gate_receipt: Mapping[str, Any] | None = None
    diagnostics: ToolReceipt | None = None
    promotion: ToolReceipt | None = None

    @property
    def completed(self) -> bool:
        return self.status == COMPLETED

    def summary_patch(self) -> dict[str, Any]:
        """Summary fields a wrapper merges into its own summary record.

        ``promotionValidation`` keeps its pre-#62 key name and payload shape so
        existing readers of a vLLM summary do not break, while
        ``promotionGate``/``promotionGateReceipt`` carry the new shared receipt.
        """
        patch: dict[str, Any] = {
            "status": self.status,
            "promotionGate": {
                "contractVersion": GATE_CONTRACT_VERSION,
                "runtimeNeutral": True,
                "status": self.status,
                "statusSemantics": STATUS_SEMANTICS[self.status],
                "promotionGateApplied": self.promotion is not None,
                "receipt": self.gate_receipt_path,
                "result": self.result_path,
                "protocolDiagnostics": self.diagnostics_receipt_path,
                "diagnosticsReceipt": (
                    self.diagnostics.to_dict() if self.diagnostics is not None else None
                ),
                "validatorReceipt": (
                    self.promotion.to_dict() if self.promotion is not None else None
                ),
                "reason": self.reason,
                "failedStep": self.failed_step,
            },
        }
        if self.gate_receipt_path:
            patch["promotionGateReceiptPath"] = self.gate_receipt_path
        if self.gate_receipt is not None:
            patch["promotionGateReceipt"] = dict(self.gate_receipt)
        if self.diagnostics_receipt_path:
            patch["protocolDiagnostics"] = self.diagnostics_receipt_path
        if self.promotion is not None:
            patch["promotionValidation"] = {
                "returnCode": self.promotion.exit_code,
                "log": self.promotion.log_path,
                "report": self.promotion.report_path,
                "reportSha256": self.promotion.report_sha256,
                "toolSha256": self.promotion.tool_sha256,
                "command": list(self.promotion.command),
                "decision": self.promotion.decision,
            }
        return patch


def _run_tool(
    *,
    tool: str,
    script: Path,
    args: Sequence[str],
    log_path: Path,
    python: str | None = None,
    timeout: float | None = None,
) -> tuple[int, str, list[str]]:
    """Run one gate tool, always preserving its combined output.

    Raises :class:`GateToolError` when the tool could not be started at all, so
    a missing/unrunnable executable can never be misread as "the evidence
    failed validation".
    """
    command = [python or sys.executable, str(script), *args]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not Path(script).is_file():
        raise GateToolError(
            tool,
            f"{tool} executable is missing: {script}",
            detail={"command": command},
        )
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        raise GateToolError(
            tool,
            f"{tool} could not be executed: {type(exc).__name__}: {exc}",
            detail={"command": command},
        ) from exc
    except subprocess.TimeoutExpired as exc:
        output = exc.output or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        log_path.write_text(output, encoding="utf-8", errors="replace")
        raise GateToolError(
            tool,
            f"{tool} timed out after {timeout} seconds",
            detail={"command": command, "log": str(log_path)},
        ) from exc
    log_path.write_text(completed.stdout or "", encoding="utf-8", errors="replace")
    return int(completed.returncode), completed.stdout or "", command


def _load_json_report(path: Path, *, tool: str) -> dict[str, Any]:
    """Read a tool's preserved report, or fail the gate as a tooling failure.

    A tool that ran but left no parseable report behind has not made a decision,
    so the evidence is unresolved rather than invalid.
    """
    if not path.is_file():
        raise GateToolError(
            tool,
            f"{tool} reported success but left no report at {path}",
            detail={"report": str(path)},
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise GateToolError(
            tool,
            f"{tool} report {path} is not readable JSON: {exc}",
            detail={"report": str(path)},
        ) from exc
    if not isinstance(payload, dict):
        raise GateToolError(
            tool,
            f"{tool} report {path} is not a JSON object",
            detail={"report": str(path)},
        )
    return payload


def _stdout_tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return "...[truncated]...\n" + text[-limit:]


def _bind_context_budget(result_path: Path) -> dict[str, Any]:
    """Bind the Issue #45 context-budget receipt the result itself records.

    The binding follows the result payload rather than a wrapper argument, so it
    cannot be swapped between runtimes and a missing receipt is visible as a
    missing receipt rather than quietly omitted.
    """
    binding: dict[str, Any] = {"recorded": False}
    try:
        payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        binding["error"] = f"{type(exc).__name__}: {exc}"
        return binding
    if not isinstance(payload, dict):
        binding["error"] = "result payload is not a JSON object"
        return binding
    block = payload.get("contextBudget")
    if not isinstance(block, dict):
        binding["error"] = "result records no contextBudget block"
        return binding
    receipt_path = block.get("receiptPath")
    declared = block.get("receiptSha256")
    actual = sha256_file(receipt_path) if receipt_path else None
    binding.update({
        "recorded": True,
        "receiptPath": str(receipt_path) if receipt_path else None,
        "receiptSha256": declared,
        "receiptSha256Observed": actual,
        "receiptResolvable": actual is not None,
        "receiptMatchesResult": bool(
            isinstance(declared, str) and actual is not None and declared.lower() == actual.lower()
        ),
    })
    return binding


def _gate_receipt(
    *,
    provenance: GateProvenance,
    status: str,
    reason: str,
    failed_step: str | None,
    diagnostics: ToolReceipt | None,
    promotion: ToolReceipt | None,
) -> dict[str, Any]:
    return {
        "schemaVersion": GATE_CONTRACT_VERSION,
        "gate": "post_inference_promotion",
        "runtimeNeutral": True,
        "issuedAt": utc_now(),
        "stage": provenance.stage,
        "decode": provenance.decode,
        "runtime": provenance.runtime,
        "promotionGateApplied": promotion is not None,
        "status": status,
        "statusSemantics": STATUS_SEMANTICS[status],
        "reason": reason,
        "failedStep": failed_step,
        "benchmarkRevision": provenance.benchmark_revision,
        "candidate": dict(provenance.candidate),
        "candidateIdentity": {
            "id": provenance.candidate.get("id"),
            "repo": provenance.candidate.get("repo"),
            "revision": provenance.candidate.get("revision"),
            "runtime": provenance.candidate.get("runtime"),
            "runtimeRevision": provenance.candidate.get("runtimeRevision"),
            "quantization": provenance.candidate.get("quantization"),
            "configSha256": sha256_json(dict(provenance.candidate)),
        },
        "modelArtifact": dict(provenance.model_artifact) if provenance.model_artifact else None,
        "runtimeEnvironment": (
            dict(provenance.runtime_environment) if provenance.runtime_environment else None
        ),
        "taskArtifact": {
            "path": str(provenance.tasks_path),
            "sha256": sha256_file(provenance.tasks_path),
        },
        "taskIdentity": dict(provenance.task_identity) if provenance.task_identity else None,
        "resultArtifact": {
            "path": str(provenance.result_path),
            "sha256": sha256_file(provenance.result_path),
            "preserved": True,
            "contextBudget": _bind_context_budget(provenance.result_path),
        },
        "tooling": {
            "parserAndProtocolCodeVersion": tool_code_version(GATE_TOOL_SOURCES),
            "toolSources": [
                {"source": path.name, "sha256": sha256_file(path)} for path in GATE_TOOL_SOURCES
            ],
            "resultSchemaSha256": sha256_file(RESULT_SCHEMA),
            "pythonExecutable": sys.executable,
        },
        "diagnosticsReceipt": diagnostics.to_dict() if diagnostics else None,
        "promotionValidatorReceipt": promotion.to_dict() if promotion else None,
        "extra": dict(provenance.extra),
        "interpretation": [
            "This gate decides terminal status for a produced result; it never scores English and never reports a runtime failure.",
            "A promotion-validator or diagnostics failure is benchmark_validation_failure; the tooling itself failing is benchmark_tool_failure.",
            "runtime_unqualified is a wrapper-owned state decided before inference and is never emitted by this gate.",
            "The bound task manifest, result digest, parser/protocol code version and context-budget receipt make the verdict reproducible from the preserved artifacts alone.",
        ],
    }


def _diagnostics_step(
    *,
    provenance: GateProvenance,
    candidate_dir: Path,
    python: str | None,
    timeout: float | None,
) -> ToolReceipt:
    """Run protocol diagnostics for one result and classify its outcome.

    Diagnostics own the frozen answer protocol (#44): they exit non-zero with a
    written report when the *result* violates that protocol, which is a
    validation failure of real evidence, not a tooling failure.
    """
    report_path = candidate_dir / DIAGNOSTICS_RECEIPT_FILENAME
    log_path = candidate_dir / DIAGNOSTICS_LOG_FILENAME
    exit_code, stdout, command = _run_tool(
        tool="protocol-diagnostics",
        script=DIAGNOSTICS,
        args=[str(provenance.result_path), str(provenance.tasks_path), str(report_path)],
        log_path=log_path,
        python=python,
        timeout=timeout,
    )
    tool_sha = sha256_file(DIAGNOSTICS)
    if exit_code == 0:
        # A clean exit still has to leave a report behind; otherwise the gate has
        # no evidence to bind.
        _load_json_report(report_path, tool="protocol-diagnostics")
        return ToolReceipt(
            tool="protocol-diagnostics",
            command=command,
            exit_code=exit_code,
            log_path=str(log_path),
            report_path=str(report_path),
            report_sha256=sha256_file(report_path),
            tool_sha256=tool_sha,
            decision="passed",
            stdout_tail=_stdout_tail(stdout),
        )

    # A non-clean exit is only a *validation* failure when diagnostics actually
    # wrote a report describing structural problems in the result. Anything else
    # (crash, traceback, no report) is a tooling failure.
    detail: dict[str, Any] = {"returnCode": exit_code}
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise GateToolError(
                "protocol-diagnostics",
                f"diagnostics report {report_path} is not readable JSON: {exc}",
                detail={"returnCode": exit_code, "log": str(log_path)},
            ) from exc
        structural = report.get("structuralStatuses") if isinstance(report, dict) else None
        detail = {
            "returnCode": exit_code,
            "structuralStatuses": structural,
            "statusCounts": report.get("statusCounts") if isinstance(report, dict) else None,
        }
        if isinstance(report, dict) and isinstance(structural, list) and structural != ["ok"]:
            return ToolReceipt(
                tool="protocol-diagnostics",
                command=command,
                exit_code=exit_code,
                log_path=str(log_path),
                report_path=str(report_path),
                report_sha256=sha256_file(report_path),
                tool_sha256=tool_sha,
                decision="validation_failure",
                stdout_tail=_stdout_tail(stdout),
                detail=detail,
            )
    raise GateToolError(
        "protocol-diagnostics",
        "protocol diagnostics exited non-zero without a structural report; "
        "the diagnostic tooling itself could not decide",
        detail={"returnCode": exit_code, "log": str(log_path), "stdout": _stdout_tail(stdout)},
    )


def _promotion_step(
    *,
    provenance: GateProvenance,
    candidate_dir: Path,
    python: str | None,
    timeout: float | None,
) -> ToolReceipt:
    """Run the one canonical promotion validator for a full-screen result."""
    log_path = candidate_dir / PROMOTION_LOG_FILENAME
    exit_code, stdout, command = _run_tool(
        tool="promotion-validator",
        script=VALIDATOR,
        args=[str(provenance.result_path), "--promotion"],
        log_path=log_path,
        python=python,
        timeout=timeout,
    )
    tool_sha = sha256_file(VALIDATOR)

    # The validator prints its JSON report to stdout and exits non-zero when the
    # report carries errors. A parseable report is a decision; no parseable
    # report is a tooling failure, because the validator could not judge the
    # evidence.
    report: dict[str, Any] | None = None
    text = stdout.strip()
    if text:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            report = parsed
    if report is None:
        raise GateToolError(
            "promotion-validator",
            "promotion validator produced no parseable report; the validator "
            "tooling itself could not decide",
            detail={"returnCode": exit_code, "log": str(log_path), "stdout": _stdout_tail(stdout)},
        )

    report_path = candidate_dir / PROMOTION_RECEIPT_FILENAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    schema_validation = report.get("schemaValidation") if isinstance(report.get("schemaValidation"), dict) else {}
    mode = schema_validation.get("validationMode") or report.get("mode")
    if mode != "promotion":
        raise GateToolError(
            "promotion-validator",
            f"promotion validator report declares mode {mode!r}, not 'promotion'; "
            "the validator was not run under the canonical promotion contract",
            detail={"returnCode": exit_code, "report": str(report_path)},
        )
    errors = report.get("errors")
    errors = errors if isinstance(errors, list) else []
    warnings = report.get("warnings")
    warnings = warnings if isinstance(warnings, list) else []
    decision = "passed" if not errors else "validation_failure"
    return ToolReceipt(
        tool="promotion-validator",
        command=command,
        exit_code=exit_code,
        log_path=str(log_path),
        report_path=str(report_path),
        report_sha256=sha256_file(report_path),
        tool_sha256=tool_sha,
        decision=decision,
        stdout_tail=_stdout_tail(stdout),
        detail={
            "validationMode": mode,
            "validatorContractVersion": schema_validation.get("validatorContractVersion"),
            "resultSchemaVersion": schema_validation.get("resultSchemaVersion"),
            "schemaSha256": schema_validation.get("schemaSha256"),
            "errorCount": len(errors),
            "errors": errors,
            "warningCount": len(warnings),
        },
    )


def _finalize(
    *,
    provenance: GateProvenance,
    candidate_dir: Path,
    status: str,
    reason: str,
    failed_step: str | None,
    diagnostics: ToolReceipt | None,
    promotion: ToolReceipt | None,
    diagnostics_receipt_path: str | None = None,
    promotion_receipt_path: str | None = None,
    promotion_log_path: str | None = None,
) -> GateOutcome:
    """Write the shared gate receipt and return the terminal outcome."""
    if status not in TERMINAL_STATUSES:
        raise GateToolError("status", f"refusing to emit non-terminal status {status!r}")
    receipt = _gate_receipt(
        provenance=provenance,
        status=status,
        reason=reason,
        failed_step=failed_step,
        diagnostics=diagnostics,
        promotion=promotion,
    )
    gate_path = candidate_dir / GATE_RECEIPT_FILENAME
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return GateOutcome(
        status=status,
        exit_code=terminal_exit_code(status),
        reason=reason,
        failed_step=failed_step,
        result_path=str(provenance.result_path),
        diagnostics_receipt_path=diagnostics_receipt_path,
        promotion_receipt_path=promotion_receipt_path,
        promotion_log_path=promotion_log_path,
        gate_receipt_path=str(gate_path),
        gate_receipt=receipt,
        diagnostics=diagnostics,
        promotion=promotion,
    )


def run_post_inference_gate(
    provenance: GateProvenance,
    *,
    candidate_dir: Path | str,
    python: str | None = None,
    timeout: float | None = None,
) -> GateOutcome:
    """Decide one runtime-neutral terminal status for a produced result.

    Order is fixed for every runtime (Issue #62):

    1. the raw result artifact is preserved and its digest bound;
    2. protocol diagnostics run;
    3. for a canonical full-screen normal-decode result, the one canonical
       promotion validator runs under ``--promotion``;
    4. only then may the status be ``completed``.

    ``python`` lets a caller select the interpreter used for benchmark tooling.
    It defaults to the caller's own interpreter; wrappers must never pass the
    model runtime's interpreter here, because these tools are benchmark tooling,
    not the inference runtime.
    """
    candidate_dir = Path(candidate_dir)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    if not provenance.result_path.is_file():
        raise GateToolError(
            "result",
            f"stable result artifact is missing: {provenance.result_path}; the raw "
            "evidence must be preserved before terminalization",
            detail={"result": str(provenance.result_path)},
        )

    try:
        diagnostics = _diagnostics_step(
            provenance=provenance,
            candidate_dir=candidate_dir,
            python=python,
            timeout=timeout,
        )
    except GateToolError as exc:
        return _finalize(
            provenance=provenance,
            candidate_dir=candidate_dir,
            status=BENCHMARK_TOOL_FAILURE,
            reason="protocol diagnostics tooling could not decide: " + exc.reason,
            failed_step="protocol_diagnostics_tool",
            diagnostics=None,
            promotion=None,
        )

    if diagnostics.decision != "passed":
        return _finalize(
            provenance=provenance,
            candidate_dir=candidate_dir,
            status=BENCHMARK_VALIDATION_FAILURE,
            reason=(
                "protocol diagnostics rejected the frozen answer protocol: "
                f"{diagnostics.detail.get('structuralStatuses')}"
            ),
            failed_step="protocol_diagnostics",
            diagnostics=diagnostics,
            promotion=None,
            diagnostics_receipt_path=diagnostics.report_path,
        )

    if not provenance.requires_promotion:
        return _finalize(
            provenance=provenance,
            candidate_dir=candidate_dir,
            status=COMPLETED,
            reason=(
                f"protocol diagnostics passed for stage {provenance.stage!r}/decode "
                f"{provenance.decode!r}; the canonical promotion contract applies only "
                f"to stage {PROMOTION_STAGE!r} decode {PROMOTION_DECODE!r}"
            ),
            failed_step=None,
            diagnostics=diagnostics,
            promotion=None,
            diagnostics_receipt_path=diagnostics.report_path,
        )

    try:
        promotion = _promotion_step(
            provenance=provenance,
            candidate_dir=candidate_dir,
            python=python,
            timeout=timeout,
        )
    except GateToolError as exc:
        return _finalize(
            provenance=provenance,
            candidate_dir=candidate_dir,
            status=BENCHMARK_TOOL_FAILURE,
            reason="promotion validator tooling could not decide: " + exc.reason,
            failed_step="promotion_validator_tool",
            diagnostics=diagnostics,
            promotion=None,
            diagnostics_receipt_path=diagnostics.report_path,
        )

    if promotion.decision != "passed":
        return _finalize(
            provenance=provenance,
            candidate_dir=candidate_dir,
            status=BENCHMARK_VALIDATION_FAILURE,
            reason=(
                "the canonical promotion validator rejected this full-screen result "
                f"with {promotion.detail.get('errorCount')} error(s); the raw result is "
                "preserved and this is not an English score zero"
            ),
            failed_step="promotion_validator",
            diagnostics=diagnostics,
            promotion=promotion,
            diagnostics_receipt_path=diagnostics.report_path,
            promotion_receipt_path=promotion.report_path,
            promotion_log_path=promotion.log_path,
        )

    return _finalize(
        provenance=provenance,
        candidate_dir=candidate_dir,
        status=COMPLETED,
        reason=(
            "protocol diagnostics and the canonical promotion validator both passed "
            "for this full-screen normal-decode result"
        ),
        failed_step=None,
        diagnostics=diagnostics,
        promotion=promotion,
        diagnostics_receipt_path=diagnostics.report_path,
        promotion_receipt_path=promotion.report_path,
        promotion_log_path=promotion.log_path,
    )


def gate_evidence_is_comparable(outcome: GateOutcome | Mapping[str, Any]) -> bool:
    """Whether a recorded gate outcome may be compared as promotion evidence.

    This is the consumer-side rule the candidate matrix needs (#34): only a
    gate receipt that says ``completed`` counts, and only when the shared
    promotion gate actually ran. A ``completed`` produced without the gate
    cannot be reclassified as comparable after the fact.
    """
    if isinstance(outcome, GateOutcome):
        status = outcome.status
        gate = outcome.gate_receipt if isinstance(outcome.gate_receipt, dict) else {}
        applied = gate.get("promotionGateApplied", outcome.promotion is not None)
    else:
        status = str(outcome.get("status", ""))
        applied = outcome.get("promotionGateApplied")
    return status == COMPLETED and bool(applied)


def main() -> None:
    """Re-run the shared gate over a preserved result, for the replay path.

    Issue #62 requires historical full-screen evidence that was labeled
    ``completed`` without the canonical validator to be revalidated from its
    preserved raw output. This entry point performs exactly that: it binds the
    same provenance, runs the same gate, and prints the terminal status. It
    never scores English and never re-runs inference.
    """
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result", type=Path, help="preserved raw result artifact")
    ap.add_argument("--tasks", type=Path, required=True, help="frozen task artifact")
    ap.add_argument(
        "--candidate-dir",
        type=Path,
        default=None,
        help="directory for receipts; defaults to the result's directory",
    )
    ap.add_argument("--stage", default=PROMOTION_STAGE)
    ap.add_argument("--decode", default=PROMOTION_DECODE)
    ap.add_argument("--candidate-id", default="replayed")
    ap.add_argument("--runtime", default="replayed")
    ap.add_argument("--benchmark-revision", default="unknown")
    args = ap.parse_args()

    provenance = GateProvenance(
        stage=args.stage,
        decode=args.decode,
        candidate={"id": args.candidate_id, "runtime": args.runtime},
        benchmark_revision=args.benchmark_revision,
        result_path=args.result,
        tasks_path=args.tasks,
        runtime=args.runtime,
    )
    outcome = run_post_inference_gate(
        provenance,
        candidate_dir=args.candidate_dir or args.result.parent,
    )
    print(json.dumps(outcome.summary_patch()["promotionGate"], indent=2, ensure_ascii=False))
    raise SystemExit(outcome.exit_code)


if __name__ == "__main__":
    main()
