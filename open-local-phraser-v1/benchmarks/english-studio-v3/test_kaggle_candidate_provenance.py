#!/usr/bin/env python3
"""Deterministic Issue #33 provenance fixtures for the Kaggle candidate matrix.

Every fixture builds a self-contained results tree in a temporary directory and
then runs the real ``build-kaggle-candidate-matrix.build_report`` against it. No
real Kaggle artifact, GPU, or network access is involved.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_matrix_module():
    """Import the hyphenated matrix script as a module without touching sys.path."""
    spec = importlib.util.spec_from_file_location(
        "build_kaggle_candidate_matrix", HERE / "build-kaggle-candidate-matrix.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


matrix = load_matrix_module()
ROSTER = json.loads(matrix.ROSTER.read_text(encoding="utf-8"))
CANDIDATES = {row["id"]: row for row in ROSTER["candidates"]}
MTP_CANDIDATE = next(row for row in ROSTER["candidates"] if row.get("mtpMethodsToProbe"))
BENCH_REVISION = "a" * 40


class Fixture:
    """A temporary results tree with pinned preflight/runtime/task artifacts."""

    def __init__(self, root: Path, candidate: dict[str, Any]) -> None:
        self.root = root
        self.candidate = candidate
        self.artifacts = root / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)

        self.preflight = self.artifacts / "preflight.json"
        self.preflight.write_text(
            json.dumps({"schemaVersion": 2, "status": "qualified", "promotionEligibleEnvironment": True}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        self.runtime_receipt = self.artifacts / "vllm.receipt.json"
        self.runtime_receipt.write_text(
            json.dumps(
                {
                    "artifact": {"id": "vllm-0.30.0-cu129-linux-x86_64", "runtime": "vllm", "version": "0.30.0"},
                    "sha256Verified": "e" * 64,
                    "sourceCompilationAllowed": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.other_runtime_receipt = self.artifacts / "llamacpp.receipt.json"
        self.other_runtime_receipt.write_text(
            json.dumps(
                {
                    "artifact": {"id": "prism-llamacpp-b10735", "runtime": "PrismML-Eng/llama.cpp"},
                    "sha256Verified": "f" * 64,
                    "sourceCompilationAllowed": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.tasks = self.artifacts / f"{candidate['id']}-fixed-screen.jsonl"
        self.tasks.write_text(
            "".join(json.dumps({"id": f"case-{i:04d}"}) + "\n" for i in range(4)),
            encoding="utf-8",
        )
        self.result: Path | None = None
        self.context_receipt: Path | None = None
        self.result_counter = 0

    def digest(self, path: Path) -> str:
        return matrix.sha256_file(path)

    def provenance(
        self,
        *,
        stage: str = "smoke",
        decode: str = "normal",
        benchmark_revision: str = BENCH_REVISION,
        candidate_revision: str | None = None,
        candidate_config_sha256: str | None = None,
        preflight_path: Path | None = None,
        preflight_sha256: str | None = None,
        runtime_path: Path | None = None,
        runtime_sha256: str | None = None,
        tasks: Path | None = None,
        tasks_sha256: str | None = None,
        write_result: bool = True,
        task_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        candidate_revision = candidate_revision if candidate_revision is not None else self.candidate["revision"]
        candidate_config_sha256 = (
            candidate_config_sha256
            if candidate_config_sha256 is not None
            else matrix.stage_config_digest(self.candidate, stage, decode)
        )
        preflight_path = preflight_path if preflight_path is not None else self.preflight
        preflight_sha256 = preflight_sha256 if preflight_sha256 is not None else self.digest(preflight_path)
        runtime_path = runtime_path if runtime_path is not None else self.runtime_receipt
        runtime_sha256 = runtime_sha256 if runtime_sha256 is not None else self.digest(runtime_path)
        tasks = tasks if tasks is not None else self.tasks
        tasks_sha256 = tasks_sha256 if tasks_sha256 is not None else self.digest(tasks)

        if task_entries is None:
            task_entries = [{"role": "primaryTasks", "path": str(tasks), "sha256": tasks_sha256}]
            task_files = [str(tasks)]
        else:
            task_files = [str(entry["path"]) for entry in task_entries]

        if write_result:
            self.result_counter += 1
            self.result = self.artifacts / f"{self.candidate['id']}-{self.result_counter:02d}.result.json"
            prompt_mode = str(self.candidate.get("promptMode") or "plain")
            thinking = {"state": "applied", "requested": "fixture", "proof": "fixture"}
            context_receipt = {
                "schemaVersion": 1,
                "state": "context_qualified",
                "tokenizer": {
                    "nameOrPath": str(self.candidate["repo"]),
                    "kind": "fixture-tokenizer",
                    "repoOrName": str(self.candidate["repo"]),
                    "revision": str(self.candidate["revision"]),
                },
                "promptMode": {
                    "promptMode": prompt_mode,
                    "template": "fixture-template",
                    "templateSha256": "a" * 64,
                    "detail": "fixture",
                },
                "effectiveContextLimit": {
                    "effectiveContextLimit": 4096,
                    "selectedFrom": {"tokens": 4096, "source": "fixture", "provenance": "fixture"},
                    "tiedSources": ["fixture"],
                    "applicableLimits": [{"tokens": 4096, "source": "fixture", "provenance": "fixture"}],
                    "policy": "minimum_applicable_limit",
                },
                "thinkingCapability": thinking,
                "tasks": [{
                    "taskId": "case-0000",
                    "promptMode": prompt_mode,
                    "templateSha256": "a" * 64,
                    "promptTokens": 16,
                    "requestedMaxNewTokens": 8,
                    "effectiveContextLimit": 4096,
                    "remainingHeadroom": 4080,
                    "fits": True,
                    "thinkingCapability": thinking,
                }],
                "violatingTaskIds": [],
                "summary": {"maxPromptTokens": 16, "violationCount": 0},
            }
            context_receipt["receiptSha256"] = matrix.canonical_json_sha256(context_receipt)
            self.context_receipt = self.result.with_suffix(f"{self.result.suffix}.context-budget.json")
            self.context_receipt.write_text(json.dumps(context_receipt, indent=2) + "\n", encoding="utf-8")
            context_reference = {
                # Exercise the documented result-relative sidecar resolution.
                "receiptPath": self.context_receipt.name,
                "receiptSha256": context_receipt["receiptSha256"],
                "effectiveContextLimit": 4096,
                "thinkingCapability": thinking,
                "summary": context_receipt["summary"],
            }
            result_payload = {
                "model": {
                    "repoOrName": str(self.candidate["repo"]),
                    "revision": str(self.candidate["revision"]),
                },
                "promptModeRequested": prompt_mode,
                "contextBudget": context_reference,
                "outputs": [],
            }
            self.result.write_text(json.dumps(result_payload, indent=2) + "\n", encoding="utf-8")

        return {
            "benchmarkRevision": benchmark_revision,
            "candidateRevision": candidate_revision,
            "candidateConfigSha256": candidate_config_sha256,
            "preflightPath": str(preflight_path),
            "preflightSha256": preflight_sha256,
            "runtimeReceiptPath": str(runtime_path),
            "runtimeReceiptSha256": runtime_sha256,
            "taskFiles": task_files,
            "taskManifestSha256s": task_entries,
            "resultSha256": self.digest(self.result) if self.result is not None else None,
            "resultPath": str(self.result) if self.result is not None else None,
            "parserCodeVersion": "protocol_output_diagnostics/1",
        }

    def write_summary(
        self,
        *,
        stage: str,
        status: str = "completed",
        provenance: dict[str, Any] | None = None,
        decode: str = "normal",
        benchmark_revision: str | None = BENCH_REVISION,
        embedded_candidate: dict[str, Any] | None = None,
        promotion_gate: dict[str, Any] | None = None,
        promotion_gate_receipt: dict[str, Any] | None = None,
        write_promotion_gate: bool = True,
    ) -> Path:
        if provenance is None:
            provenance = self.provenance(
                stage=stage, decode=decode, benchmark_revision=benchmark_revision or BENCH_REVISION
            )
        path = matrix.summary_path(self.root, self.candidate, stage, decode)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": 9,
            "candidate": embedded_candidate if embedded_candidate is not None else self.candidate,
            "stage": stage,
            "decode": decode,
            "benchmarkRevision": benchmark_revision,
            "status": status,
            "provenance": provenance,
        }
        if provenance and provenance.get("resultPath"):
            payload["result"] = provenance["resultPath"]
        payload["benchmarkRevision"] = provenance.get("benchmarkRevision")
        # Issue #62: a completed full-screen cell only counts as promotion
        # evidence when the shared runtime-neutral gate actually ran over these
        # result bytes. `write_promotion_gate=False` fabricates exactly the
        # pre-#62 Prism shape: completed, valid provenance, no gate at all.
        if promotion_gate is None and write_promotion_gate and matrix.promotion_gate_required(
            stage, decode, status
        ):
            promotion_gate, promotion_gate_receipt = self.write_promotion_gate_receipts(
                path=path,
                provenance=provenance,
                stage=stage,
                decode=decode,
            )
        if promotion_gate is not None:
            payload["promotionGate"] = promotion_gate
            receipt_path = promotion_gate.get("receipt")
            if receipt_path:
                payload["promotionGateReceiptPath"] = receipt_path
            if promotion_gate_receipt is not None:
                payload["promotionGateReceipt"] = promotion_gate_receipt
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def write_promotion_gate_receipts(
        self,
        *,
        path: Path,
        provenance: dict[str, Any],
        stage: str,
        decode: str,
        validator_decision: str = "passed",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Write the shared gate's receipt plus the validator report it binds.

        This mirrors what ``kaggle_promotion_gate`` preserves beside a real run:
        the gate receipt, and the validator report whose bytes the receipt binds.
        The fixture is fabricated -- no validator subprocess runs -- but its shape
        is exactly the shape the matrix re-verifies.
        """
        receipts = path.parent
        validator_report = receipts / "promotion-validation.json"
        validator_report.write_text(
            json.dumps(
                {
                    "mode": "promotion",
                    "schemaValidation": {
                        "validatorContractVersion": 1,
                        "validationMode": "promotion",
                        "resultSchemaVersion": 1,
                    },
                    "errors": [] if validator_decision == "passed" else ["fixture rejection"],
                    "warnings": [],
                    "status": "pass" if validator_decision == "passed" else "fail",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        diagnostics_report = receipts / "protocol-diagnostics.json"
        diagnostics_report.write_text(
            json.dumps({"version": 4, "structuralStatuses": ["ok"], "statusCounts": {}}, indent=2) + "\n",
            encoding="utf-8",
        )
        receipt = {
            "schemaVersion": 1,
            "gate": "post_inference_promotion",
            "runtimeNeutral": True,
            "stage": stage,
            "decode": decode,
            "runtime": self.candidate.get("runtime"),
            "promotionGateApplied": True,
            "status": "completed" if validator_decision == "passed" else "benchmark_validation_failure",
            "benchmarkRevision": provenance.get("benchmarkRevision"),
            "taskArtifact": {"path": str(self.tasks), "sha256": self.digest(self.tasks)},
            "resultArtifact": {
                "path": provenance.get("resultPath"),
                "sha256": provenance.get("resultSha256"),
                "preserved": True,
            },
            "diagnosticsReceipt": {
                "tool": "protocol-diagnostics",
                "decision": "passed",
                "returnCode": 0,
                "report": str(diagnostics_report),
                "reportSha256": self.digest(diagnostics_report),
                "log": str(receipts / "protocol-diagnostics.log.txt"),
            },
            "promotionValidatorReceipt": {
                "tool": "promotion-validator",
                "decision": validator_decision,
                "returnCode": 0 if validator_decision == "passed" else 1,
                "report": str(validator_report),
                "reportSha256": self.digest(validator_report),
                "log": str(receipts / "promotion-validation.log.txt"),
            },
        }
        receipt_path = receipts / "promotion-gate.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        block = {
            "contractVersion": 1,
            "runtimeNeutral": True,
            "status": receipt["status"],
            "promotionGateApplied": True,
            "receipt": str(receipt_path),
            "result": provenance.get("resultPath"),
            "reason": "fixture",
        }
        return block, receipt

    def write_finalist_set(
        self,
        candidates: list[dict[str, Any]],
        *,
        benchmark_revision: str = BENCH_REVISION,
        path: Path | None = None,
        mutate: dict[str, Any] | None = None,
    ) -> Path:
        """Write an explicit, frozen finalist decision artifact."""
        entries = []
        for candidate in candidates:
            screen = self.artifacts / f"{candidate['id']}-full.result.json"
            screen.write_text(json.dumps({"screen": candidate["id"]}, indent=2) + "\n", encoding="utf-8")
            entries.append({
                "candidate": candidate["id"],
                "candidateRevision": candidate["revision"],
                "candidateConfigSha256": matrix.stage_config_digest(candidate, "full", "normal"),
                "screenResult": {"path": str(screen), "sha256": self.digest(screen)},
            })
        payload = {
            "version": 1,
            "benchmarkRevision": benchmark_revision,
            "decidedAtUtc": "2026-10-02T12:00:00Z",
            "rationale": "screening fixtures",
            "evidence": ["smoke", "full"],
            "finalists": entries,
        }
        if mutate:
            payload.update(mutate)
        target = path or (self.root / "finalist-set.json")
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return target

    def report(
        self,
        expected_benchmark_revision: str | None = BENCH_REVISION,
        finalist_set: Path | None = None,
    ) -> dict[str, Any]:
        return matrix.build_report(self.root, expected_benchmark_revision, finalist_set)

    def sibling(self, candidate_id: str) -> "Fixture":
        """Another candidate sharing this results root but its own artifacts."""
        other = Fixture.__new__(Fixture)
        other.root = self.root
        other.candidate = CANDIDATES[candidate_id]
        other.artifacts = self.artifacts
        other.preflight = self.preflight
        other.runtime_receipt = self.runtime_receipt
        other.other_runtime_receipt = self.other_runtime_receipt
        other.tasks = self.artifacts / f"{candidate_id}-fixed-screen.jsonl"
        other.tasks.write_text(
            "".join(json.dumps({"id": f"{candidate_id}-{i:04d}"}) + "\n" for i in range(4)),
            encoding="utf-8",
        )
        other.result = None
        other.context_receipt = None
        other.result_counter = self.result_counter
        return other

    def row(self, report: dict[str, Any], candidate_id: str | None = None) -> dict[str, Any]:
        wanted = candidate_id or self.candidate["id"]
        return next(row for row in report["rows"] if row["candidate"] == wanted)


def with_fixture(candidate: dict[str, Any], body) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        body(Fixture(Path(tmp), candidate))


def candidate(id_: str) -> dict[str, Any]:
    return CANDIDATES[id_]


def test_valid_complete_provenance_chain() -> None:
    """A fully linked completed candidate enters exactly one comparable group."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([fixture.candidate])
        report = fixture.report(finalist_set=finalists)
        row = fixture.row(report)
        assert row["finalist"] is True
        assert row["disposition"] == "finalist_product_complete_pending_comparison", row["disposition"]
        assert row["provenanceFailures"] == []
        assert row["provenanceConflicts"] == []
        assert row["provenanceUnverified"] is False
        for stage in matrix.REQUIRED_STAGES:
            provenance = row[stage]["provenance"]
            assert provenance["status"] == "verified", (stage, provenance)
            assert provenance["comparable"] is True
            assert provenance["contextBudget"]["status"] == "verified"
            assert provenance["contextBudget"]["receiptSha256"]
            assert provenance["contextBudget"]["receiptFileSha256"]
            assert provenance["contextBudget"]["identitySha256"]
            assert provenance["fingerprintSha256"]
            assert provenance["recorded"]["contextBudgetReceiptSha256"] == \
                provenance["contextBudget"]["receiptSha256"]
            assert provenance["recorded"]["resultFingerprintSha256"] == \
                provenance["fingerprintSha256"]
            # Issue #62: only the full-screen normal-decode cell carries the
            # promotion gate; every other stage legitimately completes on
            # diagnostics alone and must not be asked for gate evidence.
            gate = provenance["promotionGate"]
            if stage == matrix.PROMOTION_GATE_STAGE:
                assert gate["required"] is True, (stage, gate)
                assert gate["status"] == "verified", (stage, gate)
                assert gate["comparable"] is True, (stage, gate)
                assert gate["gateReceiptFileSha256"]
                assert gate["validatorReportSha256"]
                assert provenance["recorded"]["promotionGateReceiptFileSha256"] == \
                    gate["gateReceiptFileSha256"]
            else:
                assert gate["required"] is False, (stage, gate)
                assert gate["status"] == "not_required", (stage, gate)
                assert gate["comparable"] is None, (stage, gate)
        group = row["comparableGroup"]
        assert group == f"benchmarkRevision={BENCH_REVISION}"
        assert report["comparableGroups"][group] == [row["candidate"]]
        assert report["excludedFromComparison"] == []

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_legacy_completed_full_screen_without_gate_is_not_comparable() -> None:
    """A pre-#62 Prism `completed` full screen cannot enter comparison.

    This is the exact integration gap #62 left open in #39: the Prism wrapper
    used to mark a full-screen result `completed` after protocol diagnostics
    alone, so its provenance chain was entirely valid while never having passed
    the canonical promotion validator. A vLLM summary beside it was held to the
    validator, so the two backends were comparable under different terminal
    gates. The row must stay visible, but never comparable.
    """

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            # `write_promotion_gate=False` is the pre-#62 Prism shape: a
            # completed summary with a fully valid provenance chain and no
            # promotion-gate evidence of any kind.
            fixture.write_summary(stage=stage, write_promotion_gate=False)
        finalists = fixture.write_finalist_set([fixture.candidate])
        report = fixture.report(finalist_set=finalists)
        row = fixture.row(report)

        full = row[matrix.PROMOTION_GATE_STAGE]
        gate = full["provenance"]["promotionGate"]
        assert gate["required"] is True, gate
        assert gate["status"] == "failed", gate
        assert gate["comparable"] is False, gate
        assert "promotion_gate_missing" in gate["codes"], gate
        assert full["provenance"]["comparable"] is False
        assert full["provenance"]["status"] == "failed"

        # The artifact chain itself was fine; only the gate evidence was absent.
        assert "raw_result_missing" not in gate["codes"]
        assert "context_budget_receipt_missing" not in gate["codes"]

        # The candidate stays visible and is excluded from every comparison.
        assert row["candidate"] in [entry["candidate"] for entry in report["rows"]]
        assert row["disposition"] == "provenance_failed", row["disposition"]
        assert row["comparableGroup"] is None
        assert "promotion_gate_missing" in row["provenanceFailures"]
        assert report["comparableGroups"] == {}
        assert [entry["candidate"] for entry in report["excludedFromComparison"]] == [
            fixture.candidate["id"]
        ]

        # Every other stage is untouched: only the full screen asks for the gate.
        for stage in matrix.REQUIRED_STAGES:
            if stage == matrix.PROMOTION_GATE_STAGE:
                continue
            other = row[stage]["provenance"]["promotionGate"]
            assert other["required"] is False, (stage, other)
            assert other["status"] == "not_required", (stage, other)

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_gate_block_pointing_at_a_missing_receipt_is_not_comparable() -> None:
    """A summary's own completed claim cannot stand in for the gate receipt."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        full_path = matrix.summary_path(fixture.root, fixture.candidate, matrix.PROMOTION_GATE_STAGE)
        # Drop only the preserved receipt. The summary still *claims* completed
        # and still points at it, which is exactly the forgery the matrix must
        # refuse rather than trust.
        (full_path.parent / "promotion-gate.json").unlink()

        finalists = fixture.write_finalist_set([fixture.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        gate = row[matrix.PROMOTION_GATE_STAGE]["provenance"]["promotionGate"]
        assert gate["status"] == "failed", gate
        assert "promotion_gate_receipt_missing" in gate["codes"], gate
        assert row["comparableGroup"] is None
        assert row["disposition"] == "provenance_failed", row["disposition"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_gate_receipt_for_a_different_result_is_not_comparable() -> None:
    """A gate that ran against other bytes cannot vouch for these bytes."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        full_path = matrix.summary_path(fixture.root, fixture.candidate, matrix.PROMOTION_GATE_STAGE)
        receipt_path = full_path.parent / "promotion-gate.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["resultArtifact"]["sha256"] = "b" * 64
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

        finalists = fixture.write_finalist_set([fixture.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        gate = row[matrix.PROMOTION_GATE_STAGE]["provenance"]["promotionGate"]
        assert gate["status"] == "failed", gate
        assert "promotion_gate_receipt_result_mismatch" in gate["codes"], gate
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_drifted_validator_report_is_not_comparable() -> None:
    """The preserved validator report must still hash to what the gate recorded."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        full_path = matrix.summary_path(fixture.root, fixture.candidate, matrix.PROMOTION_GATE_STAGE)
        report = full_path.parent / "promotion-validation.json"
        # One rewrite is enough: the receipt's binding is a digest, not a
        # promise, so the proof behind `completed` is gone.
        report.write_text(
            json.dumps({"mode": "promotion", "errors": [], "status": "pass"}, indent=2) + "\n",
            encoding="utf-8",
        )

        finalists = fixture.write_finalist_set([fixture.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        gate = row[matrix.PROMOTION_GATE_STAGE]["provenance"]["promotionGate"]
        assert gate["status"] == "failed", gate
        assert "promotion_gate_validator_report_drifted" in gate["codes"], gate
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_gate_receipt_for_another_cell_is_not_comparable() -> None:
    """A receipt for a different stage/decode cannot be borrowed."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        full_path = matrix.summary_path(fixture.root, fixture.candidate, matrix.PROMOTION_GATE_STAGE)
        receipt_path = full_path.parent / "promotion-gate.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["decode"] = "mtp"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

        finalists = fixture.write_finalist_set([fixture.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        gate = row[matrix.PROMOTION_GATE_STAGE]["provenance"]["promotionGate"]
        assert "promotion_gate_receipt_cell_mismatch" in gate["codes"], gate
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_vllm_and_prism_compare_only_when_both_passed_the_same_gate() -> None:
    """One gated backend and one ungated backend never share a comparison group."""

    def body(fixture: Fixture) -> None:
        # The gated candidate is the llama.cpp row under test; the ungated one is
        # a vLLM roster row that skipped the gate entirely. Before #62 exactly
        # this pairing would have grouped on identical provenance.
        prism = fixture
        vllm = fixture.sibling("qwen35-4b")
        for stage in matrix.REQUIRED_STAGES:
            prism.write_summary(stage=stage)
            vllm.write_summary(stage=stage, write_promotion_gate=False)

        finalists = fixture.write_finalist_set([prism.candidate, vllm.candidate])
        report = fixture.report(finalist_set=finalists)
        gated = fixture.row(report, prism.candidate["id"])
        ungated = fixture.row(report, vllm.candidate["id"])

        assert gated[matrix.PROMOTION_GATE_STAGE]["provenance"]["promotionGate"]["status"] == "verified"
        assert ungated[matrix.PROMOTION_GATE_STAGE]["provenance"]["promotionGate"]["codes"] == [
            "promotion_gate_missing"
        ]
        assert gated["comparableGroup"] == f"benchmarkRevision={BENCH_REVISION}"
        assert ungated["comparableGroup"] is None
        assert report["comparableGroups"][gated["comparableGroup"]] == [gated["candidate"]]
        assert [entry["candidate"] for entry in report["excludedFromComparison"]] == [vllm.candidate["id"]]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_non_completed_full_screen_keeps_its_own_terminal_verdict() -> None:
    """Runtime and benchmark failures are never relabelled as a gate problem."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            if stage == matrix.PROMOTION_GATE_STAGE:
                continue
            fixture.write_summary(stage=stage)
        fixture.write_summary(
            stage=matrix.PROMOTION_GATE_STAGE,
            status="runtime_unqualified",
            write_promotion_gate=False,
        )
        row = fixture.row(fixture.report())
        full = row[matrix.PROMOTION_GATE_STAGE]
        # An honest runtime failure has no result and therefore no gate to run:
        # requiring one would turn a real capacity fact into a provenance
        # complaint.
        gate = full["provenance"]["promotionGate"]
        assert gate["required"] is False, gate
        assert gate["status"] == "not_required", gate
        assert "promotion_gate_missing" not in row["provenanceFailures"]
        assert row["disposition"] == "runtime_unqualified", row["disposition"]
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_promotion_gate_cell_is_sourced_from_the_shared_module() -> None:
    """The matrix must not restate which cell carries the promotion contract."""

    gate_module = importlib.import_module("kaggle_promotion_gate")
    assert matrix.PROMOTION_GATE_STAGE == gate_module.PROMOTION_STAGE
    assert matrix.PROMOTION_GATE_DECODE == gate_module.PROMOTION_DECODE
    assert matrix.promotion_gate_required("full", "normal", "completed") is True
    assert matrix.promotion_gate_required("full", "mtp", "completed") is False
    assert matrix.promotion_gate_required("smoke", "normal", "completed") is False
    assert matrix.promotion_gate_required("word-studio", "normal", "completed") is False
    for non_completed in (
        "runtime_unqualified",
        "benchmark_validation_failure",
        "benchmark_tool_failure",
        "inference_completed",
        "not_run",
    ):
        assert matrix.promotion_gate_required("full", "normal", non_completed) is False, non_completed


def test_missing_context_budget_receipt_fails_closed() -> None:
    """A result that names a missing context receipt cannot enter comparison."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        assert fixture.context_receipt is not None
        fixture.context_receipt.unlink()

        report = fixture.report()
        row = fixture.row(report)
        assert row["disposition"] == "provenance_failed", row["disposition"]
        assert "context_budget_receipt_missing" in row["provenanceFailures"]
        assert row["comparableGroup"] is None
        assert [entry["candidate"] for entry in report["excludedFromComparison"]] == [row["candidate"]]
        assert row["transform"]["provenance"]["fingerprintSha256"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_drifted_context_budget_receipt_fails_its_identity_hash() -> None:
    """Changing receipt identity after the result was written is detected."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        assert fixture.context_receipt is not None
        receipt = json.loads(fixture.context_receipt.read_text(encoding="utf-8"))
        receipt["promptMode"]["template"] = "drifted-after-result"
        fixture.context_receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

        report = fixture.report()
        row = fixture.row(report)
        assert row["disposition"] == "provenance_failed", row["disposition"]
        assert "context_budget_receipt_hash_mismatch" in row["provenanceFailures"]
        assert row["comparableGroup"] is None
        assert row["transform"]["provenance"]["fingerprintSha256"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_relative_context_receipt_cannot_escape_result_directory() -> None:
    """A relative receipt link cannot escape the result artifact's directory."""

    def body(fixture: Fixture) -> None:
        provenance = fixture.provenance(stage="smoke")
        result_file = Path(provenance["resultPath"])
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        payload["contextBudget"]["receiptPath"] = "../outside-context-budget.json"
        result_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        provenance["resultSha256"] = fixture.digest(result_file)
        fixture.write_summary(stage="smoke", provenance=provenance)

        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed", row["disposition"]
        assert "context_budget_receipt_path_invalid" in row["provenanceFailures"]
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_one_byte_changed_preflight_artifact() -> None:
    """A preflight artifact mutated after the run is an integrity failure."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        assert fixture.row(fixture.report())["provenanceFailures"] == []

        raw = fixture.preflight.read_bytes()
        fixture.preflight.write_bytes(raw[:-1] + (b" " if raw[-1:] != b" " else b"x"))

        report = fixture.report()
        row = fixture.row(report)
        assert row["disposition"] == "provenance_failed", row["disposition"]
        assert "preflight_receipt_hash_mismatch" in row["provenanceFailures"]
        assert row["comparableGroup"] is None
        assert [entry["candidate"] for entry in report["excludedFromComparison"]] == [row["candidate"]]
        # Every stage still shows its own measured status: nothing is hidden.
        for stage in matrix.REQUIRED_STAGES:
            assert row[stage]["status"] == "completed"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_missing_preflight_receipt() -> None:
    """A preflight artifact that no longer exists is reported, not repaired."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        fixture.preflight.unlink()
        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed"
        assert "preflight_receipt_missing" in row["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_wrong_runtime_receipt_for_candidate_runtime() -> None:
    """A runtime receipt whose bytes no longer match the recorded hash fails."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        swapped = fixture.runtime_receipt
        original = swapped.read_text(encoding="utf-8")
        swapped.write_text(original.replace("0.30.0", "0.31.0"), encoding="utf-8")
        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed"
        assert "runtime_receipt_hash_mismatch" in row["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_summary_recording_a_different_runtime_receipt() -> None:
    """A summary that points at another runtime's receipt fails the chain."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            provenance = fixture.provenance(stage=stage)
            provenance["runtimeReceiptPath"] = str(fixture.other_runtime_receipt)
            provenance["runtimeReceiptSha256"] = fixture.digest(fixture.other_runtime_receipt)
            fixture.write_summary(stage=stage, provenance=provenance)
        row = fixture.row(fixture.report())
        # The chain is internally consistent, so the matrix reports verified
        # rather than guessing that the receipt belongs to another runtime.
        assert row["provenanceFailures"] == []

        # Once the *other* receipt is mutated, the mismatch becomes visible.
        other = fixture.other_runtime_receipt.read_text(encoding="utf-8")
        fixture.other_runtime_receipt.write_text(other.replace("prism", "vendor"), encoding="utf-8")
        row = fixture.row(fixture.report())
        assert "runtime_receipt_hash_mismatch" in row["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_missing_runtime_receipt() -> None:
    """A required pinned runtime receipt that is absent fails the chain."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        fixture.runtime_receipt.unlink()
        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed"
        assert "runtime_receipt_missing" in row["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_receipt_present_but_hash_absent_is_still_missing() -> None:
    """A linked receipt path without its recorded hash is not a valid chain."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            provenance = fixture.provenance(stage=stage)
            provenance.pop("runtimeReceiptSha256")
            fixture.write_summary(stage=stage, provenance=provenance)
        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed"
        assert "runtime_receipt_missing" in row["provenanceFailures"]

        for stage in matrix.REQUIRED_STAGES:
            provenance = fixture.provenance(stage=stage)
            provenance.pop("preflightSha256")
            fixture.write_summary(stage=stage, provenance=provenance)
        row = fixture.row(fixture.report())
        assert "preflight_receipt_missing" in row["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_provenance_block_absent_is_unverified_not_failed() -> None:
    """An unprovable legacy chain is distinguished from a proven mismatch."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            path = matrix.summary_path(fixture.root, fixture.candidate, stage)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"candidate": fixture.candidate, "stage": stage, "status": "completed"}, indent=2) + "\n",
                encoding="utf-8",
            )
        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_unverified"
        assert row["provenanceFailures"] == []
        assert row["provenanceUnverified"] is True

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_task_file_changed_after_result_creation() -> None:
    """A frozen task file mutated after the run is a task-manifest mismatch."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        original = fixture.tasks.read_text(encoding="utf-8")
        fixture.tasks.write_text(original + json.dumps({"id": "case-9999"}) + "\n", encoding="utf-8")
        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed"
        assert "task_manifest_hash_mismatch" in row["provenanceFailures"]
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_missing_task_artifact() -> None:
    """A frozen task file that disappeared is reported as a missing manifest."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        fixture.tasks.unlink()
        row = fixture.row(fixture.report())
        assert "task_manifest_missing" in row["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_task_manifest_must_be_deterministically_ordered() -> None:
    """Multiple frozen task artifacts must be recorded in canonical order."""

    def body(fixture: Fixture) -> None:
        secondary = fixture.artifacts / "secondary-tasks.jsonl"
        secondary.write_text(json.dumps({"id": "case-secondary"}) + "\n", encoding="utf-8")
        unsorted_entries = [
            {"role": "zzzPrimary", "path": str(fixture.tasks), "sha256": fixture.digest(fixture.tasks)},
            {"role": "aaaSecondary", "path": str(secondary), "sha256": fixture.digest(secondary)},
        ]
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(
                stage=stage, provenance=fixture.provenance(stage=stage, task_entries=unsorted_entries)
            )
        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed"
        assert "task_manifest_order_nondeterministic" in row["provenanceFailures"]

        ordered = matrix.canonical_task_order(matrix.normalize_task_entries(unsorted_entries))
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage, provenance=fixture.provenance(stage=stage, task_entries=ordered))
        row = fixture.row(fixture.report())
        assert row["provenanceFailures"] == []
        assert row["disposition"] == "screen_complete_pending_finalist_selection"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_same_candidate_id_at_two_different_revisions() -> None:
    """Two runs under the same friendly name cannot be conflated silently."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        other_revision = "b" * 40
        provenance = fixture.provenance(stage="transform", benchmark_revision=other_revision)
        fixture.write_summary(stage="transform", benchmark_revision=other_revision, provenance=provenance)

        report = fixture.report(expected_benchmark_revision=None)
        row = fixture.row(report)
        assert row["disposition"] == "provenance_failed"
        assert "benchmark_revision_conflict_across_stages" in row["provenanceConflicts"]
        assert row["comparableGroup"] is None
        assert row["transform"]["provenance"]["status"] == "verified"
        assert row["smoke"]["provenance"]["status"] == "verified"

        revisions = {
            stage: row[stage]["provenance"]["recorded"]["benchmarkRevision"]
            for stage in matrix.REQUIRED_STAGES
        }
        assert len(set(revisions.values())) == 2, revisions

        pinned = fixture.row(fixture.report(expected_benchmark_revision=BENCH_REVISION))
        assert "benchmark_revision_mismatch" in pinned["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_candidate_revision_and_config_mismatch() -> None:
    """Model revision and roster-config drift are both detected."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(
                stage=stage, provenance=fixture.provenance(stage=stage, candidate_revision="c" * 40)
            )
        assert "candidate_revision_mismatch" in fixture.row(fixture.report())["provenanceFailures"]

        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(
                stage=stage, provenance=fixture.provenance(stage=stage, candidate_config_sha256="d" * 64)
            )
        assert "candidate_config_mismatch" in fixture.row(fixture.report())["provenanceFailures"]

        tampered = dict(fixture.candidate, quantization="something-else")
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage, embedded_candidate=tampered)
        assert "candidate_config_mismatch" in fixture.row(fixture.report())["provenanceFailures"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_two_conflicting_summaries_for_one_candidate_stage() -> None:
    """Conflicting provenance between stages of one candidate is surfaced."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        other_preflight = fixture.artifacts / "preflight-rerun.json"
        other_preflight.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "status": "qualified",
                    "promotionEligibleEnvironment": True,
                    "runLabel": "second-preflight",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        provenance = fixture.provenance(
            stage="transform", preflight_path=other_preflight, preflight_sha256=fixture.digest(other_preflight)
        )
        fixture.write_summary(stage="transform", provenance=provenance)

        row = fixture.row(fixture.report())
        assert row["disposition"] == "provenance_failed"
        assert "preflight_conflict_across_stages" in row["provenanceConflicts"]
        assert row["provenanceFailures"] == []
        assert row["full"]["provenance"]["recorded"]["preflightSha256"] != \
            row["transform"]["provenance"]["recorded"]["preflightSha256"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_runtime_unqualified_result_with_complete_provenance_stays_visible() -> None:
    """Runtime-unqualified history is retained, not scored, and not hidden."""

    def body(fixture: Fixture) -> None:
        fixture.write_summary(
            stage="smoke", status="runtime_unqualified", provenance=fixture.provenance(stage="smoke", write_result=False)
        )
        report = fixture.report()
        row = fixture.row(report)
        assert row["disposition"] == "runtime_unqualified", row["disposition"]
        assert row["smoke"]["status"] == "runtime_unqualified"
        assert row["smoke"]["provenance"]["status"] == "verified"
        assert row["provenanceFailures"] == []
        assert row["comparableGroup"] is None
        markdown = matrix.render_markdown(report)
        assert row["candidate"] in markdown
        assert "runtime_unqualified" in markdown

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_legacy_summary_without_provenance_block_stays_visible() -> None:
    """Pre-contract summaries remain visible but cannot be compared."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            path = matrix.summary_path(fixture.root, fixture.candidate, stage)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "candidate": fixture.candidate,
                        "stage": stage,
                        "benchmarkRevision": BENCH_REVISION,
                        "status": "completed",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        report = fixture.report()
        row = fixture.row(report)
        assert row["disposition"] == "provenance_unverified"
        assert row["provenanceUnverified"] is True
        assert "provenance_block_missing" in row["smoke"]["provenance"]["codes"]
        assert row["comparableGroup"] is None
        assert row["candidate"] in matrix.render_markdown(report)

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_interrupted_running_summary_is_exempt_but_visible() -> None:
    """A run killed before inference is exempt, visible, and not comparable."""

    def body(fixture: Fixture) -> None:
        path = matrix.summary_path(fixture.root, fixture.candidate, "smoke")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "candidate": fixture.candidate,
                    "stage": "smoke",
                    "benchmarkRevision": BENCH_REVISION,
                    "status": "running",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        row = fixture.row(fixture.report())
        assert row["smoke"]["status"] == "running"
        assert row["smoke"]["provenance"]["status"] == "exempt"
        assert row["provenanceFailures"] == []
        assert row["comparableGroup"] is None
        assert row["disposition"] == "screening_incomplete"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_mtp_receipt_required_only_when_mtp_was_attempted() -> None:
    """Never-attempted MTP needs no receipt; an attempted MTP run does."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        row = fixture.row(fixture.report())
        assert row["disposition"] == "screen_complete_pending_finalist_selection"
        for method in fixture.candidate["mtpMethodsToProbe"]:
            for stage in matrix.REQUIRED_STAGES:
                state = row["speculative"][method][stage]
                assert state["status"] == "not_run"
                assert state["provenance"]["status"] == "not_run"

        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage, decode="mtp", provenance=fixture.provenance(stage=stage, decode="mtp"))
        row = fixture.row(fixture.report())
        assert row["speculative"]["mtp"]["smoke"]["provenance"]["status"] == "verified"

        fixture.runtime_receipt.unlink()
        mtp_state = fixture.row(fixture.report())["speculative"]["mtp"]["smoke"]["provenance"]
        assert mtp_state["status"] == "failed"
        assert "runtime_receipt_missing" in mtp_state["codes"]

    with_fixture(MTP_CANDIDATE, body)


def test_attempted_mtp_summary_without_runtime_receipt_fails() -> None:
    """An attempted speculative run cannot omit its pinned runtime receipt."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        provenance = fixture.provenance(stage="smoke", decode="mtp")
        provenance.pop("runtimeReceiptSha256")
        provenance.pop("runtimeReceiptPath")
        fixture.write_summary(stage="smoke", decode="mtp", provenance=provenance)

        mtp_state = fixture.row(fixture.report())["speculative"]["mtp"]["smoke"]["provenance"]
        assert mtp_state["status"] == "failed"
        assert "runtime_receipt_missing" in mtp_state["codes"]

    with_fixture(MTP_CANDIDATE, body)


def test_raw_result_hash_linkage() -> None:
    """The raw result artifact is part of the verified chain."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        result = fixture.result
        assert result is not None
        result.write_text(json.dumps({"outputs": [{"id": "case-0000"}]}, indent=2) + "\n", encoding="utf-8")
        assert "raw_result_hash_mismatch" in fixture.row(fixture.report())["provenanceFailures"]

        result.unlink()
        row = fixture.row(fixture.report())
        assert "raw_result_missing" in row["provenanceFailures"]
        assert row["disposition"] == "provenance_failed"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_not_run_candidates_are_not_reported_as_provenance_failures() -> None:
    """Nothing was attempted, so there is nothing to fail."""

    def body(fixture: Fixture) -> None:
        report = fixture.report()
        row = fixture.row(report)
        assert row["disposition"] == "never_attempted"
        assert row["provenanceFailures"] == []
        assert row["provenanceUnverified"] is False
        for stage in matrix.REQUIRED_STAGES:
            expected = "not_run" if stage in matrix.SCREEN_STAGES else matrix.NON_FINALIST_STAGE_STATUS
            assert row[stage]["status"] == expected, (stage, row[stage]["status"])
            assert row[stage]["provenance"]["status"] == expected
            assert row[stage]["required"] is (stage in matrix.SCREEN_STAGES)
        assert "n/a (not_run)" in matrix.render_markdown(report)

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_comparable_group_requires_a_shared_benchmark_revision() -> None:
    """Two fully verified candidates at the same revision share a group."""

    def body(fixture: Fixture) -> None:
        other = fixture.sibling("bonsai-8b-q1_0")
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
            other.write_summary(stage=stage, benchmark_revision="9" * 40)

        finalists = fixture.write_finalist_set([fixture.candidate, other.candidate])
        report = fixture.report(expected_benchmark_revision=None, finalist_set=finalists)
        group_a = fixture.row(report)["comparableGroup"]
        group_b = fixture.row(report, "bonsai-8b-q1_0")["comparableGroup"]
        assert group_a == f"benchmarkRevision={BENCH_REVISION}"
        assert group_b == "benchmarkRevision=" + "9" * 40
        assert set(report["comparableGroups"]) == {group_a, group_b}

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_comparable_candidates_at_one_revision_are_grouped() -> None:
    """Verified candidates at one benchmark revision may be compared."""

    def body(fixture: Fixture) -> None:
        other = fixture.sibling("bonsai-8b-q1_0")
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
            other.write_summary(stage=stage)

        finalists = fixture.write_finalist_set([fixture.candidate, other.candidate])
        report = fixture.report(finalist_set=finalists)
        group = report["comparableGroups"]
        assert len(group) == 1
        members = next(iter(group.values()))
        assert sorted(members) == ["bonsai-27b-q1_0", "bonsai-8b-q1_0"]
        assert report["excludedFromComparison"] == []

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_conflicting_candidate_is_excluded_from_its_peers_group() -> None:
    """One failed candidate never joins the other candidate's comparison group."""

    def body(fixture: Fixture) -> None:
        other = fixture.sibling("bonsai-8b-q1_0")
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
            other.write_summary(stage=stage)
        other.tasks.unlink()

        finalists = fixture.write_finalist_set([fixture.candidate, other.candidate])
        report = fixture.report(finalist_set=finalists)
        clean = fixture.row(report)
        broken = fixture.row(report, "bonsai-8b-q1_0")
        assert clean["disposition"] == "finalist_product_complete_pending_comparison"
        assert broken["disposition"] == "provenance_failed"
        assert broken["comparableGroup"] is None
        assert next(iter(report["comparableGroups"].values())) == [clean["candidate"]]
        assert [entry["candidate"] for entry in report["excludedFromComparison"]] == [broken["candidate"]]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_candidate_config_digest_is_order_independent() -> None:
    """The shared config digest depends on content, not JSON key order."""
    original = candidate("bonsai-27b-q1_0")
    reordered = dict(reversed(list(original.items())))
    assert matrix.candidate_config_digest(original) == matrix.candidate_config_digest(reordered)
    mutated = dict(original, quantization="Q4_0")
    assert matrix.candidate_config_digest(original) != matrix.candidate_config_digest(mutated)


def test_validator_accepts_the_real_runner_provenance_block() -> None:
    """A block emitted by kaggle_run_checkpoint.Provenance validates as verified."""

    def body(fixture: Fixture) -> None:
        try:
            import kaggle_run_checkpoint as runner
        except Exception:
            print("skipping runner cross-check: kaggle_run_checkpoint is not importable yet")
            return

        manifest = runner.load_task_manifest(fixture.tasks, "english-core-fixed-screen")
        for stage in matrix.REQUIRED_STAGES:
            provenance = runner.Provenance(
                benchmark_revision=BENCH_REVISION,
                candidate_id=fixture.candidate["id"],
                candidate_revision=fixture.candidate["revision"],
                candidate_config_sha256=runner.sha256_json({
                    "candidate": fixture.candidate,
                    "stage": stage,
                    "decode": "normal",
                    "runtimeArtifact": runner_runtime_artifact(fixture.candidate),
                }),
                preflight_path=str(fixture.preflight),
                preflight_sha256=runner.sha256_file(fixture.preflight),
                runtime_receipt_path=str(fixture.runtime_receipt),
                runtime_receipt_sha256=runner.sha256_file(fixture.runtime_receipt),
                task_manifest_sha256s=(manifest.as_provenance_entry(),),
                task_files=(manifest.path,),
                result_sha256=None,
                parser_code_version=runner.parser_code_version([HERE / "protocol_output_diagnostics.py"]),
            ).to_dict()
            # The real checkpoint provenance constructor does not own model
            # output artifacts. Attach the fixture's actual result + context
            # sidecar links so this cross-check exercises the complete matrix
            # contract without weakening the runner-provenance assertions.
            result_provenance = fixture.provenance(stage=stage)
            provenance["resultSha256"] = result_provenance["resultSha256"]
            provenance["resultPath"] = result_provenance["resultPath"]
            fixture.write_summary(stage=stage, provenance=provenance, benchmark_revision=BENCH_REVISION)

        row = fixture.row(fixture.report())
        assert row["provenanceFailures"] == [], (row["provenanceFailures"], row["smoke"]["provenance"]["details"])
        assert row["disposition"] == "screen_complete_pending_finalist_selection"
        for stage in matrix.REQUIRED_STAGES:
            assert row[stage]["provenance"]["status"] == "verified"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_matrix_stage_config_digest_matches_runner_reconstruction() -> None:
    """The matrix rebuilds the runner's stage-config digest exactly."""
    try:
        import kaggle_run_checkpoint as runner
    except Exception:
        print("skipping digest cross-check: kaggle_run_checkpoint is not importable yet")
        return
    for row in ROSTER["candidates"]:
        for stage in matrix.REQUIRED_STAGES:
            expected = runner.sha256_json({
                "candidate": row,
                "stage": stage,
                "decode": "normal",
                "runtimeArtifact": runner_runtime_artifact(row),
            })
            assert matrix.stage_config_digest(row, stage, "normal") == expected, (row["id"], stage)


def runner_runtime_artifact(row: dict[str, Any]) -> str | None:
    """Mirror run-kaggle-candidate.runtime_artifact_for for the given roster row."""
    if row.get("runtime") == "vllm":
        return matrix.VLLM_RUNTIME_ARTIFACT
    declared = row.get("runtimeArtifactId")
    return str(declared) if declared else None


# ---------------------------------------------------------------------------
# Issue #39: phase-aware lifecycle (screening vs finalist product stages)
# ---------------------------------------------------------------------------


def test_screen_complete_without_any_product_run() -> None:
    """Fixture 1: smoke+full complete and no finalist decision yet."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        row = fixture.row(fixture.report())
        assert row["disposition"] == "screen_complete_pending_finalist_selection"
        assert row["finalist"] is False
        assert row["finalistDecisionPending"] is True
        for stage in matrix.PRODUCT_STAGES:
            assert row[stage]["status"] == matrix.NON_FINALIST_STAGE_STATUS
            assert row[stage]["required"] is False
            assert "finalist-only" in row[stage]["reason"]
        assert row["smoke"]["required"] is True and row["full"]["required"] is True
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_non_finalist_product_stages_are_intentionally_not_run() -> None:
    """Fixture 2: a decided non-finalist shows an explicit intentional state."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        # Freeze a decision that explicitly excludes this candidate.
        other = fixture.sibling("bonsai-8b-q1_0")
        finalists = fixture.write_finalist_set([other.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        assert row["finalist"] is False
        assert row["finalistDecisionPending"] is False
        assert row["disposition"] == "screened_non_finalist"
        for stage in matrix.PRODUCT_STAGES:
            assert row[stage]["status"] == matrix.NON_FINALIST_STAGE_STATUS
        # Screening evidence is not erased by the product decision.
        assert row["smoke"]["status"] == "completed"
        assert row["full"]["status"] == "completed"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_finalist_product_stages_become_required() -> None:
    """Fixture 3: finalist selection makes the product suites required."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([fixture.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        assert row["finalist"] is True
        assert row["disposition"] == "finalist_product_pending"
        for stage in matrix.PRODUCT_STAGES:
            # Not run yet, but now explicitly required work rather than a blank.
            assert row[stage]["status"] == "not_run"
            assert row[stage]["required"] is True

        fixture.write_summary(stage="word-studio")
        row = fixture.row(fixture.report(finalist_set=finalists))
        assert row["disposition"] == "finalist_product_pending", "transform is still missing"
        fixture.write_summary(stage="transform")
        row = fixture.row(fixture.report(finalist_set=finalists))
        assert row["disposition"] == "finalist_product_complete_pending_comparison"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_runtime_unqualified_candidate_never_needs_later_stages() -> None:
    """Fixture 4: an unqualified runtime is terminal without screening/product work."""

    def body(fixture: Fixture) -> None:
        fixture.write_summary(
            stage="smoke", status="runtime_unqualified", provenance=fixture.provenance(stage="smoke", write_result=False)
        )
        row = fixture.row(fixture.report())
        assert row["disposition"] == "runtime_unqualified"
        assert row["smoke"]["status"] == "runtime_unqualified"
        assert row["full"]["status"] == "not_run"
        for stage in matrix.PRODUCT_STAGES:
            assert row[stage]["status"] == matrix.NOT_APPLICABLE_AFTER_SCREEN
            assert "runtime-unqualified" in row[stage]["reason"]
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_finalist_set_with_unknown_candidate_fails_closed() -> None:
    """Fixture 5: a finalist file naming an unknown candidate is rejected."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([fixture.candidate])
        payload = json.loads(finalists.read_text(encoding="utf-8"))
        payload["finalists"].append({
            "candidate": "not-in-the-roster",
            "candidateRevision": "0" * 40,
            "candidateConfigSha256": "0" * 64,
            "screenResult": {"path": str(fixture.artifacts / "screen.result.json"), "sha256": "0" * 64},
        })
        finalists.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        report = fixture.report(finalist_set=finalists)
        assert any("finalist_unknown_candidate" in err for err in report["finalistSet"]["errors"])
        assert report["finalistSet"]["finalists"] == []
        for row in report["rows"]:
            assert row["finalist"] is False
            assert row["disposition"] == "finalist_set_blocked", row["candidate"]
            assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_finalist_config_hash_mismatch_fails_closed() -> None:
    """Fixture 6: a stale candidateConfigSha256 in the finalist file is rejected."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([fixture.candidate])
        payload = json.loads(finalists.read_text(encoding="utf-8"))
        payload["finalists"][0]["candidateConfigSha256"] = "0" * 64
        finalists.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        report = fixture.report(finalist_set=finalists)
        assert any("finalist_candidate_config_sha256_mismatch" in err for err in report["finalistSet"]["errors"])
        assert report["finalistSet"]["finalists"] == []
        assert fixture.row(report)["disposition"] == "finalist_set_blocked"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_finalist_with_a_changed_screen_result_fails_closed() -> None:
    """The finalist decision must reference the exact screen bytes it chose."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([fixture.candidate])
        screen = fixture.artifacts / f"{fixture.candidate['id']}-full.result.json"
        screen.write_text(json.dumps({"screen": "re-scored"}, indent=2) + "\n", encoding="utf-8")

        report = fixture.report(finalist_set=finalists)
        assert any("finalist_screen_result_hash_mismatch" in err for err in report["finalistSet"]["errors"])
        assert report["finalistSet"]["finalists"] == []

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_finalist_missing_transform_is_product_incomplete() -> None:
    """Fixture 7: one missing product stage keeps the finalist row pending."""

    def body(fixture: Fixture) -> None:
        for stage in ("smoke", "full", "word-studio"):
            fixture.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([fixture.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        assert row["finalist"] is True
        assert row["disposition"] == "finalist_product_pending"
        assert row["transform"]["required"] is True
        assert row["transform"]["status"] == "not_run"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_non_finalist_with_historical_product_evidence_is_not_reclassified() -> None:
    """Fixture 8: old product folders stay visible without making a finalist."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        other = fixture.sibling("bonsai-8b-q1_0")
        finalists = fixture.write_finalist_set([other.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        assert row["finalist"] is False
        assert row["word-studio"]["status"] == "completed"
        assert row["transform"]["status"] == "completed"
        assert row["disposition"] == "screened_non_finalist"
        assert row["comparableGroup"] is None

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_conflicting_stage_summaries_survive_the_phase_transition() -> None:
    """Fixture 9: conflicts are surfaced, not silently selected, at any phase."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.REQUIRED_STAGES:
            fixture.write_summary(stage=stage)
        other_preflight = fixture.artifacts / "preflight-rerun.json"
        other_preflight.write_text(
            json.dumps({"schemaVersion": 2, "status": "qualified", "runLabel": "rerun"}, indent=2) + "\n",
            encoding="utf-8",
        )
        fixture.write_summary(
            stage="transform",
            provenance=fixture.provenance(
                stage="transform",
                preflight_path=other_preflight,
                preflight_sha256=fixture.digest(other_preflight),
            ),
        )
        finalists = fixture.write_finalist_set([fixture.candidate])
        row = fixture.row(fixture.report(finalist_set=finalists))
        assert row["disposition"] == "provenance_failed"
        assert "preflight_conflict_across_stages" in row["provenanceConflicts"]
        assert row["comparableGroup"] is None
        # Both conflicting summaries remain visible in the report.
        assert row["full"]["provenance"]["recorded"]["preflightSha256"] != \
            row["transform"]["provenance"]["recorded"]["preflightSha256"]

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_all_roster_candidates_stay_visible_in_every_phase() -> None:
    """No candidate disappears at any point in the lifecycle."""

    def body(fixture: Fixture) -> None:
        other = fixture.sibling("bonsai-8b-q1_0")
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
            other.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([other.candidate])
        for report in (fixture.report(), fixture.report(finalist_set=finalists)):
            assert len(report["rows"]) == len(ROSTER["candidates"])
            assert {row["candidate"] for row in report["rows"]} == set(CANDIDATES)
            for row in report["rows"]:
                assert row["disposition"]
                for stage in matrix.REQUIRED_STAGES:
                    assert row[stage]["status"], (row["candidate"], stage)

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_missing_finalist_set_file_fails_closed() -> None:
    """A declared-but-absent decision is an integrity failure, not a default."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        report = fixture.report(finalist_set=fixture.root / "absent-finalist-set.json")
        assert any("finalist_set_missing" in err for err in report["finalistSet"]["errors"])
        for row in report["rows"]:
            assert row["finalist"] is False
            assert row["disposition"] == "finalist_set_blocked"

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def test_finalist_set_at_a_different_benchmark_revision_is_rejected() -> None:
    """A decision frozen at another benchmark revision cannot be reused."""

    def body(fixture: Fixture) -> None:
        for stage in matrix.SCREEN_STAGES:
            fixture.write_summary(stage=stage)
        finalists = fixture.write_finalist_set([fixture.candidate], benchmark_revision="b" * 40)
        report = fixture.report(finalist_set=finalists)
        assert any("finalist_set_benchmark_revision_mismatch" in err for err in report["finalistSet"]["errors"])
        assert report["finalistSet"]["finalists"] == []

    with_fixture(candidate("bonsai-27b-q1_0"), body)


def main() -> None:
    tests = [
        test_valid_complete_provenance_chain,
        test_promotion_gate_cell_is_sourced_from_the_shared_module,
        test_legacy_completed_full_screen_without_gate_is_not_comparable,
        test_gate_block_pointing_at_a_missing_receipt_is_not_comparable,
        test_gate_receipt_for_a_different_result_is_not_comparable,
        test_drifted_validator_report_is_not_comparable,
        test_gate_receipt_for_another_cell_is_not_comparable,
        test_vllm_and_prism_compare_only_when_both_passed_the_same_gate,
        test_non_completed_full_screen_keeps_its_own_terminal_verdict,
        test_missing_context_budget_receipt_fails_closed,
        test_drifted_context_budget_receipt_fails_its_identity_hash,
        test_relative_context_receipt_cannot_escape_result_directory,
        test_one_byte_changed_preflight_artifact,
        test_missing_preflight_receipt,
        test_wrong_runtime_receipt_for_candidate_runtime,
        test_summary_recording_a_different_runtime_receipt,
        test_missing_runtime_receipt,
        test_receipt_present_but_hash_absent_is_still_missing,
        test_provenance_block_absent_is_unverified_not_failed,
        test_task_file_changed_after_result_creation,
        test_missing_task_artifact,
        test_task_manifest_must_be_deterministically_ordered,
        test_same_candidate_id_at_two_different_revisions,
        test_candidate_revision_and_config_mismatch,
        test_two_conflicting_summaries_for_one_candidate_stage,
        test_runtime_unqualified_result_with_complete_provenance_stays_visible,
        test_legacy_summary_without_provenance_block_stays_visible,
        test_interrupted_running_summary_is_exempt_but_visible,
        test_mtp_receipt_required_only_when_mtp_was_attempted,
        test_attempted_mtp_summary_without_runtime_receipt_fails,
        test_raw_result_hash_linkage,
        test_not_run_candidates_are_not_reported_as_provenance_failures,
        test_comparable_group_requires_a_shared_benchmark_revision,
        test_comparable_candidates_at_one_revision_are_grouped,
        test_conflicting_candidate_is_excluded_from_its_peers_group,
        test_candidate_config_digest_is_order_independent,
        test_matrix_stage_config_digest_matches_runner_reconstruction,
        test_validator_accepts_the_real_runner_provenance_block,
        test_screen_complete_without_any_product_run,
        test_non_finalist_product_stages_are_intentionally_not_run,
        test_finalist_product_stages_become_required,
        test_runtime_unqualified_candidate_never_needs_later_stages,
        test_finalist_set_with_unknown_candidate_fails_closed,
        test_finalist_config_hash_mismatch_fails_closed,
        test_finalist_with_a_changed_screen_result_fails_closed,
        test_finalist_missing_transform_is_product_incomplete,
        test_non_finalist_with_historical_product_evidence_is_not_reclassified,
        test_conflicting_stage_summaries_survive_the_phase_transition,
        test_all_roster_candidates_stay_visible_in_every_phase,
        test_missing_finalist_set_file_fails_closed,
        test_finalist_set_at_a_different_benchmark_revision_is_rejected,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} candidate-matrix provenance fixture tests passed.")


if __name__ == "__main__":
    main()
