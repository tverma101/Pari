#!/usr/bin/env python3
"""CPU-only parity tests for the shared Issue #62 promotion gate.

These tests run the *real* diagnostics and promotion validator as subprocesses
over fabricated result artifacts. They never load a model, never touch a GPU
and never reach Kaggle.

The point of the suite is parity: for every scenario, the vLLM-shaped result and
the Prism-shaped result must reach the *same* terminal status through the *same*
gate. Before Issue #62 a Prism full-screen result could be marked ``completed``
after diagnostics alone, so a malformed or mismatched Prism result entered the
candidate matrix as completed while the identical vLLM result did not. Each
scenario below asserts the two runtimes agree, and the weaker-path scenarios
assert that neither runtime can be ``completed``.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import kaggle_promotion_gate as gate  # noqa: E402

SCHEMA_PATH = HERE / "english-core-result-schema.json"

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_outputs_sha256(outputs: list[dict]) -> str:
    """The validator's own raw-output digest convention."""
    payload = json.dumps(outputs, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _task_rows(count: int = 3) -> list[dict]:
    rows = []
    for index in range(count):
        rows.append({
            "id": f"task-{index:02d}",
            "prompt": "Choose the best continuation.\nA. alpha\nB. beta\nAnswer only with the letter.",
            "allowedChoices": ["A", "B"],
            "answerProtocol": "letter",
            "generative": False,
        })
    return rows


def _write_tasks(path: Path, rows: list[dict]) -> tuple[str, int]:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")
    return _sha256_text(text), len(rows)


def _fabricated_result(
    tasks_path: Path,
    task_sha: str,
    task_count: int,
    *,
    runtime: str,
    chat_template_sha: str | None = "b" * 64,
) -> dict:
    """A canonical, promotion-valid result for one runtime.

    The two runtimes differ only in the backend-native fields the Issue #63
    registry exists to normalize: vLLM's ``topK=-1`` disabled sentinel versus
    llama.cpp's ``topK=0``, and ``chat_template`` versus
    ``llama.cpp_embedded_chat_template``. Everything the shared content/task/
    provenance gate cares about is identical.
    """
    is_vllm = runtime == "vllm"
    outputs = [
        {
            "id": row["id"],
            "output": "A",
            "latencySeconds": 0.5,
            "promptAdaptation": "chat_template" if is_vllm else "llama.cpp_embedded_chat_template",
            "promptAdaptationDetail": "reasoning_effort=none;enable_thinking=false",
            "finishReason": "stop",
            "completionTokenCount": 1,
        }
        for row in _task_rows(task_count)
    ]
    decoding = {
        "temperature": 0.0,
        "topP": 1.0,
        "topK": -1 if is_vllm else 0,
        "maxNewTokens": 220,
        "forcedChoiceMaxNewTokens": 8,
        "seed": 0,
        "batchSize": 8,
    }
    if is_vllm:
        decoding["speculativeConfig"] = None
    return {
        "schemaVersion": 1,
        "runId": f"fixture-{runtime}",
        "timestamp": "2026-10-03T00:00:00Z",
        "status": "completed",
        "complete": True,
        "completedCount": task_count,
        "sourceTaskCount": task_count,
        "model": {
            "name": f"fixture-{runtime}",
            "repoOrName": f"fixture/{runtime}",
            "revision": "f" * 40,
            "artifactSha256": "a" * 64,
            "artifactIdentityType": "file-sha256",
            "quantization": "bf16" if is_vllm else "Q4_K_M",
            "checkpointType": "instruct",
            "runtime": "vllm" if is_vllm else "llama.cpp",
            "runtimeVersion": "0.30.0" if is_vllm else "b10735",
            "tokenizerName": "fixture-tokenizer",
            "chatTemplate": (
                "tokenizer.apply_chat_template" if is_vllm else "GGUF-embedded chat template"
            ),
            "chatTemplateSha256": chat_template_sha,
        },
        "hardware": {},
        "taskFile": str(tasks_path),
        "taskFileSha256": task_sha,
        "taskCount": task_count,
        "promptModeRequested": "chat",
        "promptAdaptationModesObserved": [
            "chat_template" if is_vllm else "llama.cpp_embedded_chat_template"
        ],
        "promptAdaptationDetailsObserved": ["reasoning_effort=none;enable_thinking=false"],
        "decoding": decoding,
        "runtime": {},
        "outputs": outputs,
        "reproducibility": {
            "benchmarkRevision": "fixture-benchmark-revision",
            "rawOutputSha256": _canonical_outputs_sha256(outputs),
            "resultSchemaVersion": 1,
            "resultSchemaSha256": (
                hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
                if SCHEMA_PATH.is_file()
                else None
            ),
            "notes": [],
        },
    }


def _write_result(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _write_context_budget(root: Path, result_path: Path) -> None:
    """Write a context-budget receipt and bind it into the result (#45)."""
    receipt_path = root / (result_path.stem + ".context-budget.json")
    payload = {
        "schemaVersion": 1,
        "state": "qualified",
        "summary": {"maxPromptTokens": 120, "minHeadroom": 7928, "taskCount": 3},
    }
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["contextBudget"] = {
        "receiptPath": str(receipt_path),
        "receiptSha256": gate.sha256_file(receipt_path),
        "effectiveContextLimit": 8192,
        "effectiveContextLimitSource": {
            "tokens": 8192,
            "source": "runtime_override",
            "provenance": "fixture",
        },
        "summary": payload["summary"],
    }
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _run_gate(
    root: Path,
    *,
    runtime: str,
    stage: str = gate.PROMOTION_STAGE,
    decode: str = gate.PROMOTION_DECODE,
    mutate=None,
    tool_override=None,
    label: str = "default",
) -> gate.GateOutcome:
    """Build a runtime's result artifact, then run the one shared gate over it."""
    workspace = root / f"{label}-{runtime}"
    workspace.mkdir(parents=True, exist_ok=True)
    tasks_path = workspace / "tasks.jsonl"
    task_sha, task_count = _write_tasks(tasks_path, _task_rows())
    result_path = workspace / "result.json"
    payload = _fabricated_result(tasks_path, task_sha, task_count, runtime=runtime)
    if mutate is not None:
        mutate(payload, tasks_path, result_path)
    _write_result(result_path, payload)
    _write_context_budget(workspace, result_path)

    provenance = gate.GateProvenance(
        stage=stage,
        decode=decode,
        candidate={
            "id": f"fixture-{runtime}",
            "repo": f"fixture/{runtime}",
            "revision": "f" * 40,
            "runtime": "vllm" if runtime == "vllm" else "llama.cpp",
            "runtimeRevision": "0.30.0" if runtime == "vllm" else "b10735",
            "quantization": "bf16" if runtime == "vllm" else "Q4_K_M",
        },
        benchmark_revision="fixture-benchmark-revision",
        result_path=result_path,
        tasks_path=tasks_path,
        runtime="vllm" if runtime == "vllm" else "llama.cpp",
        task_identity={"stage": stage, "kind": "canonical", "promotionEligible": True},
        model_artifact={"localSha256": "a" * 64, "hubLfsSha256": "a" * 64},
        runtime_environment={"artifactId": f"fixture-{runtime}"},
        extra={"scenario": label},
    )
    candidate_dir = workspace / "receipts"
    if tool_override is not None:
        original_validator = gate.VALIDATOR
        original_diagnostics = gate.DIAGNOSTICS
        gate.VALIDATOR, gate.DIAGNOSTICS = tool_override(original_validator, original_diagnostics)
        try:
            return gate.run_post_inference_gate(provenance, candidate_dir=candidate_dir)
        finally:
            gate.VALIDATOR, gate.DIAGNOSTICS = original_validator, original_diagnostics
    return gate.run_post_inference_gate(provenance, candidate_dir=candidate_dir)


def _assert_parity(label: str, left: gate.GateOutcome, right: gate.GateOutcome) -> None:
    check(
        left.status == right.status,
        f"{label}: runtimes disagree; vllm={left.status} prism={right.status}",
    )
    check(
        left.exit_code == right.exit_code,
        f"{label}: exit codes disagree; vllm={left.exit_code} prism={right.exit_code}",
    )
    check(
        left.failed_step == right.failed_step,
        f"{label}: failed steps disagree; vllm={left.failed_step} prism={right.failed_step}",
    )


def _both(root: Path, label: str, **kwargs) -> tuple[gate.GateOutcome, gate.GateOutcome]:
    """Run the same scenario for both runtimes and assert they agree."""
    vllm = _run_gate(root, runtime="vllm", label=label, **kwargs)
    prism = _run_gate(root, runtime="prism", label=label, **kwargs)
    _assert_parity(label, vllm, prism)
    return vllm, prism


# 1 & 2. A valid vLLM full result and a valid Prism full result pass the exact
#       same validator gate.


def test_valid_full_results_pass_the_same_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vllm, prism = _both(root, "valid")

        for name, outcome, runtime in (("vllm", vllm, "vllm"), ("prism", prism, "llama.cpp")):
            check(
                outcome.status == gate.COMPLETED,
                f"valid {runtime} full result must be completed; got {outcome.status}: {outcome.reason}",
            )
            check(
                outcome.promotion is not None and outcome.promotion.decision == "passed",
                f"valid {runtime} full result must pass the promotion validator",
            )
            check(outcome.exit_code == 0, f"completed must exit 0; {runtime} exited {outcome.exit_code}")

            # The gate must have bound every provenance identity #62 names.
            receipt = outcome.gate_receipt or {}
            tooling = receipt.get("tooling") or {}
            task_artifact = receipt.get("taskArtifact") or {}
            result_artifact = receipt.get("resultArtifact") or {}
            candidate_identity = receipt.get("candidateIdentity") or {}
            context_budget = result_artifact.get("contextBudget") or {}
            check(receipt.get("promotionGateApplied") is True, f"{name}: gate receipt must record the gate applied")
            check(receipt.get("runtimeNeutral") is True, f"{name}: gate receipt must record runtime neutrality")
            check(
                str(tooling.get("parserAndProtocolCodeVersion", "")).startswith("protocol_output_diagnostics.py+"),
                f"{name}: receipt must bind the parser/protocol code version (#44)",
            )
            check(
                len(str(task_artifact.get("sha256", ""))) == 64,
                f"{name}: receipt must bind the task manifest hash (#48)",
            )
            check(
                len(str(result_artifact.get("sha256", ""))) == 64,
                f"{name}: receipt must bind the result artifact hash",
            )
            check(
                context_budget.get("recorded") is True,
                f"{name}: receipt must bind the context-budget receipt (#45)",
            )
            check(
                context_budget.get("receiptMatchesResult") is True,
                f"{name}: the bound context-budget receipt must match the digest the result records",
            )
            check(
                len(str(candidate_identity.get("configSha256", ""))) == 64,
                f"{name}: receipt must bind candidate provenance (#33/#41)",
            )
            check(
                receipt.get("benchmarkRevision") == "fixture-benchmark-revision",
                f"{name}: receipt must bind the benchmark revision (#40)",
            )
            check(
                len(str(tooling.get("resultSchemaSha256", ""))) == 64,
                f"{name}: receipt must bind the exact validated result schema bytes",
            )
            check(
                outcome.gate_receipt_path and Path(outcome.gate_receipt_path).is_file(),
                f"{name}: the gate receipt must be preserved on disk",
            )
            check(
                outcome.promotion.log_path and Path(outcome.promotion.log_path).is_file(),
                f"{name}: the validator log must be preserved on disk",
            )
            check(
                outcome.promotion.report_path and Path(outcome.promotion.report_path).is_file(),
                f"{name}: the validator report must be preserved on disk",
            )
            check(
                outcome.promotion.command[-1] == "--promotion",
                f"{name}: the validator must be invoked under the promotion contract",
            )


# 3. Malformed / missing task rows fail identically on both runtimes.


def _drop_a_task_row(payload: dict, tasks_path: Path, result_path: Path) -> None:
    payload["outputs"] = payload["outputs"][:-1]
    payload["reproducibility"]["rawOutputSha256"] = _canonical_outputs_sha256(payload["outputs"])


def test_missing_task_rows_fail_identically() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vllm, prism = _both(root, "missing-rows", mutate=_drop_a_task_row)
        for name, outcome in (("vllm", vllm), ("prism", prism)):
            check(
                outcome.status == gate.BENCHMARK_VALIDATION_FAILURE,
                f"{name}: a missing task row is a benchmark validation failure; got {outcome.status}",
            )
            check(
                outcome.status != gate.RUNTIME_UNQUALIFIED,
                f"{name}: malformed evidence must never be reported as a runtime failure",
            )
        # Diagnostics own the structural ID-coverage check, so the shared gate
        # stops there and never reaches the promotion validator.
        check(
            vllm.failed_step == "protocol_diagnostics",
            f"missing task rows should fail at diagnostics; got {vllm.failed_step}",
        )
        check(
            vllm.promotion is None,
            "the promotion validator must not run once diagnostics rejected the evidence",
        )


# 4. A task-manifest mismatch fails identically on both runtimes. Diagnostics
#    compares ID *sets*, so a task file whose bytes changed but whose IDs did not
#    passes diagnostics and is caught by the promotion validator's taskFileSha256
#    check. Both runtimes must reach the same terminal state.


def _tamper_task_bytes(payload: dict, tasks_path: Path, result_path: Path) -> None:
    rows = _task_rows()
    rows[0]["prompt"] = rows[0]["prompt"] + " (edited)"
    _write_tasks(tasks_path, rows)


def test_task_manifest_mismatch_fails_identically() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vllm, prism = _both(root, "task-mismatch", mutate=_tamper_task_bytes)
        for name, outcome in (("vllm", vllm), ("prism", prism)):
            check(
                outcome.status == gate.BENCHMARK_VALIDATION_FAILURE,
                f"{name}: a task-manifest mismatch is a benchmark validation failure; got {outcome.status}",
            )
        check(
            vllm.failed_step == "promotion_validator",
            f"task-manifest mismatch should fail at the promotion validator; got {vllm.failed_step}",
        )
        check(
            vllm.promotion is not None and vllm.promotion.detail.get("errors"),
            "the preserved validator report must carry the task-manifest mismatch error",
        )


# 5. A provenance mismatch fails identically on both runtimes. An unpinned model
#    artifact identity is a promotion requirement, and it is the same
#    requirement on both backends.


def _drop_artifact_hash(payload: dict, tasks_path: Path, result_path: Path) -> None:
    payload["model"]["artifactSha256"] = None


def test_provenance_mismatch_fails_identically() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vllm, prism = _both(root, "provenance", mutate=_drop_artifact_hash)
        for name, outcome in (("vllm", vllm), ("prism", prism)):
            check(
                outcome.status == gate.BENCHMARK_VALIDATION_FAILURE,
                f"{name}: an unpinned artifact identity is a benchmark validation failure; got {outcome.status}",
            )
        check(
            vllm.failed_step == "promotion_validator",
            f"a provenance mismatch should fail at the promotion validator; got {vllm.failed_step}",
        )


# 6. Diagnostics pass but the promotion validator fails -> neither runtime is
#    `completed`. This is the exact weaker-path scenario the issue calls out.


def _drop_reproducibility_identity(payload: dict, tasks_path: Path, result_path: Path) -> None:
    payload["reproducibility"]["resultSchemaSha256"] = "c" * 64


def test_diagnostics_pass_but_promotion_fails_is_not_completed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vllm, prism = _both(root, "promo-fail", mutate=_drop_reproducibility_identity)
        for name, outcome in (("vllm", vllm), ("prism", prism)):
            check(
                outcome.diagnostics is not None and outcome.diagnostics.decision == "passed",
                f"{name}: diagnostics must pass before the promotion gate rejects the evidence",
            )
            check(
                outcome.status == gate.BENCHMARK_VALIDATION_FAILURE,
                f"{name}: a promotion-validator rejection must be benchmark_validation_failure; got {outcome.status}",
            )
            check(not outcome.completed, f"{name}: a promotion-validator rejection must never be completed")
            check(
                outcome.promotion is not None,
                f"{name}: a promotion-validator rejection must still preserve its receipt",
            )
            check(
                not gate.gate_evidence_is_comparable(outcome),
                f"{name}: a rejected result must not be comparable evidence",
            )


# 7. A validator executable / error path becomes benchmark_tool_failure, not a
#    runtime failure. Diagnostics stays real so the failure is visibly downstream.


def test_validator_error_path_is_a_tool_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stub_dir = root / "stubs"
        stub_dir.mkdir(parents=True, exist_ok=True)
        crashing = stub_dir / "crashing-validator.py"
        crashing.write_text(
            "import sys\n"
            "print('validator crashed: Traceback ...', file=sys.stderr)\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )

        def override(original_validator: Path, original_diagnostics: Path):
            return crashing, original_diagnostics

        vllm, prism = _both(root, "tool-fail", tool_override=override)
        for name, outcome in (("vllm", vllm), ("prism", prism)):
            check(
                outcome.status == gate.BENCHMARK_TOOL_FAILURE,
                f"{name}: a crashing validator is a benchmark tool failure; got {outcome.status}",
            )
            check(
                outcome.status != gate.RUNTIME_UNQUALIFIED,
                f"{name}: a tooling failure must never be reported as a runtime failure",
            )
            check(
                outcome.exit_code == gate.terminal_exit_code(gate.BENCHMARK_TOOL_FAILURE),
                f"{name}: a tool failure must exit with the shared tool-failure code",
            )
            check(
                outcome.failed_step == "promotion_validator_tool",
                f"{name}: the failed step must name the validator tooling; got {outcome.failed_step}",
            )
            check(
                outcome.diagnostics is not None and outcome.diagnostics.decision == "passed",
                f"{name}: diagnostics should still pass before the validator tooling failed",
            )


# 7b. A missing validator executable is also a tool failure, and a validator
#     that exits 0 without a parseable report is *not* a pass.


def test_missing_or_reportless_validator_is_a_tool_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stub_dir = root / "stubs"
        stub_dir.mkdir(parents=True, exist_ok=True)

        def override_missing(original_validator: Path, original_diagnostics: Path):
            return stub_dir / "does-not-exist-validator.py", original_diagnostics

        outcome = _run_gate(root, runtime="vllm", label="missing-validator", tool_override=override_missing)
        check(
            outcome.status == gate.BENCHMARK_TOOL_FAILURE,
            f"a missing validator executable is a tool failure; got {outcome.status}",
        )
        check(outcome.exit_code != 0, "a missing validator must never exit 0")

        silent = stub_dir / "silent-validator.py"
        silent.write_text(
            "import sys\nprint('nothing to see here')\nsys.exit(0)\n",
            encoding="utf-8",
        )

        def override_silent(original_validator: Path, original_diagnostics: Path):
            return silent, original_diagnostics

        outcome = _run_gate(root, runtime="vllm", label="silent-validator", tool_override=override_silent)
        check(
            outcome.status == gate.BENCHMARK_TOOL_FAILURE,
            f"a validator that exits 0 with no report must not be a pass; got {outcome.status}",
        )
        check(
            not outcome.completed,
            "a validator that exits 0 with no parseable report must never be completed",
        )

        # A diagnostics crash is also a tooling failure, never a runtime failure.
        def override_diagnostics(original_validator: Path, original_diagnostics: Path):
            return original_validator, silent

        outcome = _run_gate(root, runtime="vllm", label="silent-diagnostics", tool_override=override_diagnostics)
        check(
            outcome.status == gate.BENCHMARK_TOOL_FAILURE,
            f"a crashing diagnostics tool is a benchmark tool failure; got {outcome.status}",
        )
        check(
            outcome.failed_step == "protocol_diagnostics_tool",
            f"the failed step must name the diagnostics tooling; got {outcome.failed_step}",
        )


# 8. The candidate matrix cannot classify one backend complete under a weaker
#    gate. Only a gate receipt that both says `completed` *and* records that the
#    shared promotion gate ran is comparable; a summary claiming `completed`
#    without the gate (the pre-#62 Prism path) is not comparable at all.


def test_matrix_cannot_treat_weaker_completion_as_comparable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = _run_gate(root, runtime="vllm", label="comparable")
        check(gate.gate_evidence_is_comparable(good), "a completed gated receipt must be comparable")

    weak_receipt = {"status": gate.COMPLETED, "promotionGateApplied": False}
    check(
        not gate.gate_evidence_is_comparable(weak_receipt),
        "a `completed` produced without the shared promotion gate must NOT be comparable",
    )
    check(
        not gate.gate_evidence_is_comparable({"status": gate.COMPLETED}),
        "a `completed` with no promotion-gate record must NOT be comparable",
    )
    for status in (gate.BENCHMARK_VALIDATION_FAILURE, gate.BENCHMARK_TOOL_FAILURE, gate.RUNTIME_UNQUALIFIED):
        check(
            not gate.gate_evidence_is_comparable({"status": status, "promotionGateApplied": True}),
            f"a gated {status} must NOT be comparable",
        )
    check(gate.terminal_exit_code(gate.COMPLETED) == 0, "completed must exit 0")
    for status in (gate.BENCHMARK_VALIDATION_FAILURE, gate.BENCHMARK_TOOL_FAILURE, gate.RUNTIME_UNQUALIFIED):
        check(gate.terminal_exit_code(status) != 0, f"{status} must exit non-zero")


# 9. Non-full-screen stages stay diagnostics-only on both runtimes, preserving
#    the pre-existing product/smoke behavior through the one shared path.


def test_non_full_stage_is_diagnostics_only_on_both_runtimes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vllm, prism = _both(root, "non-full", stage="word-studio")
        for name, outcome in (("vllm", vllm), ("prism", prism)):
            check(
                outcome.status == gate.COMPLETED,
                f"{name}: a non-full stage is completed on diagnostics alone; got {outcome.status}",
            )
            check(
                outcome.promotion is None,
                f"{name}: the promotion validator must not run for a non-full stage",
            )
            check(
                gate.gate_evidence_is_comparable(outcome) is False,
                f"{name}: a diagnostics-only completion is not promotion/comparability evidence",
            )


# 10. Structural: both wrappers route post-inference terminalization through the
#     shared module and keep no private validator/diagnostics branch.


def test_wrappers_share_the_gate_and_keep_no_private_validator_branch() -> None:
    for filename in ("run-kaggle-vllm-candidate.py", "run-kaggle-prism-candidate.py"):
        path = HERE / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        imported = any(
            isinstance(node, ast.Import)
            and any(alias.name == "kaggle_promotion_gate" for alias in node.names)
            for node in ast.walk(tree)
        )
        check(imported, f"{filename} must import kaggle_promotion_gate")

        calls_shared = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run_post_inference_gate"
            for node in ast.walk(tree)
        )
        check(
            calls_shared,
            f"{filename} must route post-inference terminalization through "
            "promotion_gate.run_post_inference_gate",
        )

        # The private validator/diagnostics invocation is exactly the drift #62
        # removed, so neither wrapper may keep it.
        check(
            "validate-english-core-run.py" not in source,
            f"{filename} must not reference validate-english-core-run.py directly",
        )
        check(
            "protocol_output_diagnostics.py" not in source,
            f"{filename} must not reference protocol_output_diagnostics.py directly",
        )

        # Neither wrapper hand-writes a terminal status for a produced result;
        # the shared gate owns the terminal vocabulary.
        for literal_status in ("benchmark_validation_failure", "benchmark_tool_failure"):
            check(
                literal_status not in source,
                f"{filename} must not hard-code the terminal status {literal_status!r}",
            )


# 11. The gate must refuse a missing result artifact rather than silently
#     terminalizing evidence that does not exist.


def test_missing_result_artifact_is_refused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_path = root / "tasks.jsonl"
        _write_tasks(tasks_path, _task_rows())
        provenance = gate.GateProvenance(
            stage=gate.PROMOTION_STAGE,
            decode=gate.PROMOTION_DECODE,
            candidate={"id": "fixture"},
            benchmark_revision="fixture-benchmark-revision",
            result_path=root / "absent.json",
            tasks_path=tasks_path,
            runtime="vllm",
        )
        raised = False
        try:
            gate.run_post_inference_gate(provenance, candidate_dir=root / "receipts")
        except gate.GateToolError as exc:
            raised = True
            check(exc.step == "result", f"the failure must name the result step; got {exc.step}")
        check(raised, "a missing raw result artifact must be refused, not terminalized")


def main() -> None:
    tests = [
        test_valid_full_results_pass_the_same_gate,
        test_missing_task_rows_fail_identically,
        test_task_manifest_mismatch_fails_identically,
        test_provenance_mismatch_fails_identically,
        test_diagnostics_pass_but_promotion_fails_is_not_completed,
        test_validator_error_path_is_a_tool_failure,
        test_missing_or_reportless_validator_is_a_tool_failure,
        test_matrix_cannot_treat_weaker_completion_as_comparable,
        test_non_full_stage_is_diagnostics_only_on_both_runtimes,
        test_wrappers_share_the_gate_and_keep_no_private_validator_branch,
        test_missing_result_artifact_is_refused,
    ]
    for test in tests:
        before = len(FAILURES)
        test()
        added = len(FAILURES) - before
        print(f"  {'ok  ' if added == 0 else 'FAIL'} {test.__name__} ({added} failure(s))")
    if FAILURES:
        print()
        for failure in FAILURES:
            print("FAILURE:", failure)
        raise SystemExit(1)
    print(f"All Issue #62 promotion-gate parity tests passed ({CHECKS} checks, CPU only).")


if __name__ == "__main__":
    main()
