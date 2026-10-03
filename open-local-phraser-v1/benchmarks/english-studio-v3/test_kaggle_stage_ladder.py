#!/usr/bin/env python3
"""CPU/synthetic tests for Issues #48 and #49.

No GPU, no model, no network. These prove the two claims that matter:

* #48 - a stage resolves to exactly one frozen task identity, and an arbitrary
  --tasks path can never become promotion-valid;
* #49 - Q1/Q2/Q3 are explicit sequential gates, Q3 is a registered frozen subset
  rather than --limit N, and Q4 full screening is gated behind Q1 -> Q3.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import kaggle_run_checkpoint as K
import kaggle_stage_identity as STAGE

HERE = Path(__file__).resolve().parent


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREP = _load_module("pari_test_prepare_kaggle_benchmark", "prepare-kaggle-benchmark.py")
VERIFY = _load_module(
    "pari_test_verify_kaggle_preparation", "verify-kaggle-benchmark-preparation.py"
)


def write_jsonl(path: Path, rows: list) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def test_register_is_the_single_source_for_every_stage() -> None:
    """Every stage the wrappers accept comes from the one register file."""
    assert STAGE.REGISTER_PATH.is_file()
    assert STAGE.REGISTER_PATH.name == "kaggle-stage-manifest.json"
    assert len(STAGE.stage_manifest_sha256()) == 64
    gates = [str(entry["gate"]) for entry in STAGE.QUALIFICATION_LADDER]
    assert {"q1", "q2", "q3", "q4"} <= set(gates)
    for stage in STAGE.STAGE_MANIFEST:
        assert stage in STAGE.STAGE_GATE_MAP
    assert set(STAGE.STAGE_GATE_MAP.values()) <= set(gates)


def test_canonical_smoke_passes_and_is_not_a_limit() -> None:
    """The frozen protocol smoke resolves canonical with its registered hash."""
    identity = STAGE.resolve_stage_tasks("smoke")
    assert identity.kind == "canonical"
    assert identity.promotion_eligible is True
    assert identity.comparable is True
    assert identity.expected_count == 16
    entry = STAGE.stage_entry("smoke")
    assert identity.sha256 == entry["artifactSha256"]
    assert identity.ids_sha256 == entry["orderedTaskIdsSha256"]
    assert "not derived" in str(entry["subsetRule"]).lower()


def test_arbitrary_task_override_cannot_be_promotion_valid() -> None:
    """A custom task file resolves exploratory, never promotion-canonical."""
    with tempfile.TemporaryDirectory() as tmp:
        custom = write_jsonl(
            Path(tmp) / "custom.jsonl",
            [{"id": "custom-0", "prompt": "p0"}, {"id": "custom-1", "prompt": "p1"}],
        )
        raised = False
        try:
            STAGE.resolve_stage_tasks("smoke", custom, promotion_run=True)
        except K.CheckpointError as exc:
            raised = True
            assert "cannot become promotion-valid" in str(exc)
        assert raised, "an arbitrary task override was accepted for promotion"

        exploratory = STAGE.resolve_stage_tasks("smoke", custom, promotion_run=False)
        assert exploratory.kind == "exploratory"
        assert exploratory.promotion_eligible is False
        assert exploratory.comparable is False
        assert "exploratory" in exploratory.parser_contract
        assert len(exploratory.sha256 or "") == 64


def test_registered_order_drift_is_rejected() -> None:
    """Same IDs but reordered cannot satisfy the canonical order contract."""
    with tempfile.TemporaryDirectory() as tmp:
        original = STAGE.canonical_path("smoke")
        rows = [
            json.loads(line)
            for line in original.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        reordered = write_jsonl(Path(tmp) / "reordered.jsonl", list(reversed(rows)))
        raised = False
        try:
            STAGE.resolve_stage_tasks("smoke", reordered, promotion_run=True)
        except K.CheckpointError:
            raised = True
        assert raised, "a reordered task suite was accepted as canonical"


def test_q3_is_a_registered_frozen_subset_not_a_limit() -> None:
    """Q3 is bound to a frozen prefix rule, never to whatever --limit yields."""
    entry = STAGE.stage_entry("benchmark-smoke")
    assert entry["gate"] == "q3"
    assert entry["subsetOf"] == "full"
    assert int(entry["subsetPrefixCount"]) > 0
    assert "limit" in str(entry["subsetRule"]).lower()
    assert "not the complete comparison" in str(entry["note"]).lower()
    assert entry["expectedCount"] == STAGE.stage_entry("full")["expectedCount"]


def test_gate_sequence_blocks_q4_behind_q1_to_q3() -> None:
    """Q1 failure prevents Q2/Q3, and Q4 needs a completed Q1->Q3 chain."""
    complete = {
        "q0-preflight": {"status": "completed"},
        "q1-load": {"status": "completed"},
        "q2-protocol": {"status": "completed"},
        "q3-benchmark-smoke": {"status": "completed"},
    }
    ok, missing = STAGE.q4_is_gated(complete)
    assert ok is True and missing == []

    assert not STAGE.gate_satisfied("q2", {"q0"})[0]
    assert not STAGE.gate_satisfied("q3", {"q0"})[0]
    no_q3 = {"q1-load": {"status": "completed"}, "q2-protocol": {"status": "completed"}}
    ok, missing = STAGE.q4_is_gated(no_q3)
    assert ok is False
    assert "q3" in missing
    assert not STAGE.gate_satisfied("q3", {"q1"})[0]


def test_highest_gate_reported_exactly() -> None:
    """Report the exact gate reached, not one ambiguous smoke cell."""
    receipts = {"q0-preflight": {"status": "completed"}, "q1-load": {"status": "completed"}}
    progress = STAGE.highest_gate_reached(receipts)
    assert progress["highestGateReached"] == "q1"
    assert progress["gatesCompleted"] == ["q0", "q1"]
    assert "q2" in progress["gatesNotCompleted"]


def test_custom_tasks_cannot_masquerade_as_q2_or_q3() -> None:
    """A custom task file is never a valid Q2/Q3 promotion identity."""
    with tempfile.TemporaryDirectory() as tmp:
        custom = write_jsonl(Path(tmp) / "custom.jsonl", [{"id": "fake", "prompt": "p"}])
        for stage in ("smoke", "benchmark-smoke"):
            raised = False
            try:
                STAGE.resolve_stage_tasks(stage, custom, promotion_run=True)
            except K.CheckpointError:
                raised = True
            assert raised, stage + " accepted an arbitrary override for promotion"


def test_word_studio_stages_cannot_be_swapped() -> None:
    """Strength and transform are distinct registered stages."""
    strength = STAGE.stage_entry("word-studio")
    transform = STAGE.stage_entry("transform")
    assert strength["path"] != transform["path"]
    assert strength["expectedCount"] != transform["expectedCount"]
    assert strength["gate"] != transform["gate"]


def test_dispatcher_preserves_q2_protocol_smoke_routing() -> None:
    """The already-wired Q2 protocol-smoke routing is preserved, not rebuilt."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pari_dispatcher", HERE / "run-kaggle-candidate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PROTOCOL_SMOKE_TASKS.name == "kaggle-protocol-smoke.jsonl"
    assert module.PROTOCOL_SMOKE_TASKS.is_file()
    # `smoke` is the Q2 stage and still resolves to that exact frozen artifact.
    assert STAGE.gate_for_stage("smoke") == "q2"
    assert STAGE.canonical_path("smoke").name == "kaggle-protocol-smoke.jsonl"


def test_dispatcher_gate_blocks_q4_and_preserves_earlier_receipts() -> None:
    """Q1 failure prevents Q2/Q3; Q4 needs Q1->Q3; earlier receipts stay visible."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pari_dispatcher2", HERE / "run-kaggle-candidate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Q1 failure prevents Q2.
    blocked = module.resolve_gate_evidence("smoke", {}, allow_unmet=False)
    assert blocked["allowed"] is False
    assert blocked["missingPrerequisiteGates"] == ["q1"]

    # Q1 pass lets Q2 run.
    after_q1 = module.resolve_gate_evidence(
        "smoke",
        {"q1-load": {"status": "completed"}},
        allow_unmet=False,
    )
    assert after_q1["allowed"] is True

    # Q1+Q2 but no Q3 keeps Q4 gated, and the earlier receipts remain visible.
    q4_blocked = module.resolve_gate_evidence(
        "full",
        {"q1-load": {"status": "completed"}, "q2-protocol": {"status": "completed"}},
        allow_unmet=False,
    )
    assert q4_blocked["allowed"] is False
    assert "q3" in q4_blocked["missingPrerequisiteGates"]
    assert q4_blocked["ladderProgressBeforeThisGate"]["gatesCompleted"] == ["q1", "q2"]

    # Q1+Q2+Q3 unlocks Q4.
    q4_ok = module.resolve_gate_evidence(
        "full",
        {
            "q1-load": {"status": "completed"},
            "q2-protocol": {"status": "completed"},
            "q3-benchmark-smoke": {"status": "completed"},
        },
        allow_unmet=False,
    )
    assert q4_ok["allowed"] is True

    # An explicit override marks the run non-comparable rather than comparable.
    forced = module.resolve_gate_evidence("full", {}, allow_unmet=True)
    assert forced["allowed"] is True
    assert "non-comparable" in forced["nonComparableReason"]


def test_matrix_reports_the_exact_highest_gate() -> None:
    """The matrix shows Q3 reached with Q4 failed, not one ambiguous smoke cell."""
    import importlib.util
    import tempfile

    spec = importlib.util.spec_from_file_location(
        "pari_matrix", HERE / "build-kaggle-candidate-matrix.py"
    )
    matrix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matrix)
    assert matrix.STAGE_GATES["smoke"] == "q2"
    assert matrix.STAGE_GATES["benchmark-smoke"] == "q3"
    assert matrix.STAGE_GATES["full"] == "q4"
    assert len(matrix.STAGE_MANIFEST_SHA256) == 64

    roster = json.loads(matrix.ROSTER.read_text(encoding="utf-8"))
    candidate = roster["candidates"][0]
    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp)
        for stage, status in (("smoke", "completed"), ("benchmark-smoke", "completed"), ("full", "failed")):
            path = matrix.summary_path(results, candidate, stage, "normal")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"status": status, "provenance": {}}), encoding="utf-8")
        report = matrix.build_report(results, None, None)
        rows = report.get("rows") or report.get("candidates")
        row = next(r for r in rows if r["candidate"] == candidate["id"])
        qualification = row["qualification"]
        assert qualification["gatesCompleted"] == ["q2", "q3"]
        assert qualification["highestGateReached"] == "q3"
        # A failed later gate does not erase the earlier completed receipts.
        assert qualification["receipts"]["q4-full"]["status"] == "failed"
        assert "q4" in qualification["gatesNotCompleted"]


def test_roster_phases_include_q3() -> None:
    """The roster runs the Q3 benchmark smoke between Q2 and the full screen."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pari_roster", HERE / "run-kaggle-roster.py"
    )
    roster_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(roster_module)
    for phase in ("english", "product", "all"):
        stages = roster_module.PHASE_STAGES[phase]
        assert "benchmark-smoke" in stages
        assert stages.index("smoke") < stages.index("benchmark-smoke") < stages.index("full")


def stage_manifest_sha256() -> str:
    return STAGE.stage_manifest_sha256()


def write_prepared_register(
    directory: Path,
    *,
    manifest_sha: str | None = None,
    register_stages: dict | None = None,
    benchmark_revision: str = "0" * 40,
    receipt_revision: str | None = None,
) -> tuple[Path, Path]:
    """Write a prepared stage register plus the receipt that binds it."""
    manifest_digest = manifest_sha if manifest_sha is not None else STAGE.stage_manifest_sha256()
    stages = register_stages if register_stages is not None else {}
    register = {
        "version": 1,
        "preparedBy": "prepare-kaggle-benchmark.py",
        "stageManifestFile": STAGE.REGISTER_PATH.name,
        "stageManifestSha256": manifest_digest,
        "stages": stages,
    }
    register_path = directory / STAGE.PREPARED_REGISTER_FILENAME
    register_path.write_text(
        json.dumps(register, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    revision = receipt_revision if receipt_revision is not None else benchmark_revision
    receipt = {
        "benchmarkRevision": revision,
        STAGE.PREPARED_REGISTER_KEY: {
            "file": STAGE.PREPARED_REGISTER_FILENAME,
            "fileSha256": K.sha256_file(register_path),
            "stageManifestSha256": manifest_digest,
            "benchmarkRevision": benchmark_revision,
            "stages": stages,
        },
    }
    receipt_path = directory / "benchmark-preparation.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return register_path, receipt_path


def fake_screen(directory: Path, ids: list[str]) -> Path:
    return write_jsonl(
        directory / "english-core-fixed-screen.jsonl",
        [{"id": task_id, "prompt": f"p{index}"} for index, task_id in enumerate(ids)],
    )


def full_stage_freeze(screen: Path, ids: list[str]) -> dict:
    return {
        "path": screen.name,
        "gate": "q4",
        "taskCount": len(ids),
        "artifactSha256": K.sha256_file(screen),
        "artifactBytes": screen.stat().st_size,
        "orderedTaskIdsSha256": STAGE.ordered_ids_sha256(ids),
    }


def test_generated_stage_is_declared_and_its_prefix_is_registered() -> None:
    """The 1,943-case screen is a prepared stage with a registered Q3 prefix."""
    assert STAGE.uses_prepared_identity("full") is True
    assert STAGE.uses_prepared_identity("benchmark-smoke") is True
    # Protocol and product stages stay frozen by the checked-in register, so they
    # must never silently fall back to the prepared register.
    assert STAGE.uses_prepared_identity("smoke") is False
    assert STAGE.uses_prepared_identity("word-studio") is False
    prefix = STAGE.stage_entry("benchmark-smoke")["subsetPrefixCount"]
    assert isinstance(prefix, int) and prefix > 0
    assert STAGE.stage_entry("benchmark-smoke")["artifactSha256"] is None


def test_prepared_freeze_binds_artifact_count_and_ordered_ids() -> None:
    """A prepared stage resolves canonical-prepared against the frozen values."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = ["a", "b", "c"]
        screen = fake_screen(directory, ids)
        register_path, receipt_path = write_prepared_register(
            directory, register_stages={"full": full_stage_freeze(screen, ids)}
        )
        assert register_path.is_file()
        with patch.object(STAGE, "canonical_path", lambda stage: screen), patch.object(
            STAGE, "PREPARED_REGISTER_PATH", register_path
        ):
            identity = STAGE.resolve_stage_tasks("full", preparation_receipt=receipt_path)
            assert identity.kind == "canonical-prepared"
            assert identity.promotion_eligible is True
            assert identity.expected_count == len(ids)
            assert identity.ids_sha256 == STAGE.ordered_ids_sha256(ids)
            assert identity.sha256 == K.sha256_file(screen)
            assert STAGE.stage_manifest_sha256() in identity.reason


def test_prepared_freeze_rejects_edited_bytes_and_reordered_ids() -> None:
    """Bytes and ordered IDs each fail closed against the freeze."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = ["a", "b", "c"]
        screen = fake_screen(directory, ids)
        register_path, receipt_path = write_prepared_register(
            directory, register_stages={"full": full_stage_freeze(screen, ids)}
        )
        with patch.object(STAGE, "canonical_path", lambda stage: screen), patch.object(
            STAGE, "PREPARED_REGISTER_PATH", register_path
        ):
            screen.write_text(
                screen.read_text(encoding="utf-8") + '{"id":"d","prompt":"p3"}\n',
                encoding="utf-8",
            )
            raised = False
            try:
                STAGE.resolve_stage_tasks("full", preparation_receipt=receipt_path)
            except K.CheckpointError:
                raised = True
            assert raised, "edited screen bytes were accepted against the prepared freeze"

            fake_screen(directory, ["c", "b", "a"])
            raised = False
            try:
                STAGE.resolve_stage_tasks("full", preparation_receipt=receipt_path)
            except K.CheckpointError:
                raised = True
            assert raised, "a reordered screen was accepted against the prepared freeze"


def test_prepared_register_must_match_its_binding() -> None:
    """A register bound elsewhere, or one the receipt does not match, is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = ["a", "b", "c"]
        screen = fake_screen(directory, ids)
        stages = {"full": full_stage_freeze(screen, ids)}
        register_path = directory / STAGE.PREPARED_REGISTER_FILENAME
        with patch.object(STAGE, "canonical_path", lambda stage: screen), patch.object(
            STAGE, "PREPARED_REGISTER_PATH", register_path
        ):
            _, receipt_path = write_prepared_register(
                directory, manifest_sha="f" * 64, register_stages=stages
            )
            raised = False
            try:
                STAGE.resolve_stage_tasks("full", preparation_receipt=receipt_path)
            except K.CheckpointError:
                raised = True
            assert raised, "a register bound to another stage manifest was accepted"

            _, receipt_path = write_prepared_register(
                directory,
                register_stages=stages,
                benchmark_revision="1" * 40,
                receipt_revision="2" * 40,
            )
            raised = False
            try:
                STAGE.resolve_stage_tasks("full", preparation_receipt=receipt_path)
            except K.CheckpointError:
                raised = True
            assert raised, "a register frozen for another benchmark revision was accepted"

            _, receipt_path = write_prepared_register(directory, register_stages=stages)
            tampered = json.loads(register_path.read_text(encoding="utf-8"))
            tampered["stages"]["full"]["taskCount"] = 999
            register_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
            raised = False
            try:
                STAGE.resolve_stage_tasks("full", preparation_receipt=receipt_path)
            except K.CheckpointError:
                raised = True
            assert raised, "a tampered bundled register was accepted"


def test_bundled_register_without_a_receipt_fails_closed() -> None:
    """An unvetted register dropped into the tree cannot freeze a stage."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = ["a", "b", "c"]
        screen = fake_screen(directory, ids)
        register_path, _ = write_prepared_register(
            directory, register_stages={"full": full_stage_freeze(screen, ids)}
        )
        raised = False
        with patch.object(STAGE, "canonical_path", lambda stage: screen), patch.object(
            STAGE, "PREPARED_REGISTER_PATH", register_path
        ):
            try:
                STAGE.resolve_stage_tasks(
                    "full", preparation_receipt=directory / "no-receipt.json"
                )
            except K.CheckpointError:
                raised = True
        assert raised, "an unvetted bundled register was accepted with no receipt"


def test_q3_prefix_digest_is_frozen_and_enforced() -> None:
    """Q3's registered prefix ordered-ID digest is part of its frozen identity."""
    declared_prefix = int(STAGE.stage_entry("benchmark-smoke")["subsetPrefixCount"])
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = [f"task-{index}" for index in range(declared_prefix + 5)]
        screen = fake_screen(directory, ids)
        prefix_ids = ids[:declared_prefix]
        stages = {
            "benchmark-smoke": {
                "path": screen.name,
                "gate": "q3",
                "taskCount": len(ids),
                "artifactSha256": K.sha256_file(screen),
                "artifactBytes": screen.stat().st_size,
                "orderedTaskIdsSha256": STAGE.ordered_ids_sha256(ids),
                "subsetPrefixCount": declared_prefix,
                "subsetOrderedTaskIdsSha256": STAGE.ordered_ids_sha256(prefix_ids),
            }
        }
        register_path, receipt_path = write_prepared_register(
            directory, register_stages=stages
        )
        with patch.object(STAGE, "canonical_path", lambda stage: screen), patch.object(
            STAGE, "frozen_subset_ids", lambda stage: prefix_ids
        ), patch.object(STAGE, "PREPARED_REGISTER_PATH", register_path):
            identity = STAGE.resolve_stage_tasks(
                "benchmark-smoke", preparation_receipt=receipt_path
            )
            assert identity.kind == "canonical-subset-prepared"
            assert identity.expected_count == declared_prefix
            assert identity.ids_sha256 == STAGE.ordered_ids_sha256(prefix_ids)
            assert identity.subset_count == declared_prefix

            bad = json.loads(register_path.read_text(encoding="utf-8"))
            bad["stages"]["benchmark-smoke"]["subsetOrderedTaskIdsSha256"] = "d" * 64
            register_path.write_text(json.dumps(bad, indent=2) + "\n", encoding="utf-8")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt[STAGE.PREPARED_REGISTER_KEY]["fileSha256"] = K.sha256_file(register_path)
            receipt[STAGE.PREPARED_REGISTER_KEY]["stages"] = bad["stages"]
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            raised = False
            try:
                STAGE.resolve_stage_tasks(
                    "benchmark-smoke", preparation_receipt=receipt_path
                )
            except K.CheckpointError:
                raised = True
            assert raised, "a mismatched Q3 prefix digest was accepted"


def test_generated_stage_never_accepts_an_unregistered_promotion_path() -> None:
    """A prepared stage keeps the exploratory-only override rule."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = ["a", "b", "c"]
        screen = fake_screen(directory, ids)
        register_path, receipt_path = write_prepared_register(
            directory, register_stages={"full": full_stage_freeze(screen, ids)}
        )
        custom = write_jsonl(directory / "custom.jsonl", [{"id": "x", "prompt": "p"}])
        with patch.object(STAGE, "canonical_path", lambda stage: screen), patch.object(
            STAGE, "PREPARED_REGISTER_PATH", register_path
        ):
            raised = False
            try:
                STAGE.resolve_stage_tasks(
                    "full", custom, promotion_run=True, preparation_receipt=receipt_path
                )
            except K.CheckpointError:
                raised = True
            assert raised, "a prepared stage accepted an unregistered promotion path"
            exploratory = STAGE.resolve_stage_tasks(
                "full", custom, promotion_run=False, preparation_receipt=receipt_path
            )
            assert exploratory.kind == "exploratory"
            assert exploratory.promotion_eligible is False


def test_preparation_freezes_the_registered_prefix_not_a_restated_one() -> None:
    """Preparation reads the prefix size and digest shape from the one register."""
    prefix = PREP.declared_subset_prefix_counts()
    assert prefix["benchmark-smoke"] == STAGE.stage_entry("benchmark-smoke")["subsetPrefixCount"]
    assert PREP.PREPARED_STAGES["benchmark-smoke"]["subsetPrefixCount"] == prefix["benchmark-smoke"]
    assert PREP.ordered_ids_sha256(["a", "b"]) == STAGE.ordered_ids_sha256(["a", "b"])
    assert PREP.ordered_ids_sha256(["a", "b"]) != STAGE.ordered_ids_sha256(["b", "a"])


def test_preparation_freeze_rejects_a_divergent_prefix_size() -> None:
    """A preparation run that would freeze a different prefix fails closed."""
    original = PREP.PREPARED_STAGES["benchmark-smoke"]["subsetPrefixCount"]
    declared = int(STAGE.stage_entry("benchmark-smoke")["subsetPrefixCount"])
    total = PREP.EXPECTED["english-core-fixed-screen.jsonl"]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = [f"t{index}" for index in range(total)]
        screen = fake_screen(directory, ids)
        files = {
            screen.name: {
                "cases": total,
                "sha256": K.sha256_file(screen),
                "bytes": screen.stat().st_size,
            }
        }
        try:
            PREP.PREPARED_STAGES["benchmark-smoke"]["subsetPrefixCount"] = declared + 1
            raised = False
            with patch.object(PREP, "HERE", directory):
                try:
                    PREP.freeze_prepared_stage_identity(files)
                except SystemExit:
                    raised = True
            assert raised, "preparation froze a prefix the stage manifest does not register"
        finally:
            PREP.PREPARED_STAGES["benchmark-smoke"]["subsetPrefixCount"] = original


def test_preparation_freeze_records_full_and_prefix_identity() -> None:
    """The prepared freeze carries artifact SHA, count, and both ordered-ID digests."""
    declared_prefix = int(STAGE.stage_entry("benchmark-smoke")["subsetPrefixCount"])
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ids = [f"t{index}" for index in range(PREP.EXPECTED["english-core-fixed-screen.jsonl"])]
        screen = fake_screen(directory, ids)
        with patch.object(PREP, "HERE", directory):
            files = {
                screen.name: {
                    "cases": PREP.EXPECTED[screen.name],
                    "sha256": K.sha256_file(screen),
                    "bytes": screen.stat().st_size,
                }
            }
            assert len(ids) == PREP.EXPECTED[screen.name]
            register = PREP.freeze_prepared_stage_identity(files)
            full = register["stages"]["full"]
            q3 = register["stages"]["benchmark-smoke"]
            assert full["taskCount"] == len(ids)
            assert full["artifactSha256"] == K.sha256_file(screen)
            assert full["orderedTaskIdsSha256"] == STAGE.ordered_ids_sha256(ids)
            assert q3["subsetPrefixCount"] == declared_prefix
            assert q3["subsetOrderedTaskIdsSha256"] == STAGE.ordered_ids_sha256(
                ids[:declared_prefix]
            )
            assert q3["orderedTaskIdsSha256"] == full["orderedTaskIdsSha256"]
            assert register["stageManifestSha256"] == STAGE.stage_manifest_sha256()


def test_preparation_freeze_reads_no_gold_answer_key() -> None:
    """The freeze hashes model-visible task files only."""
    for stage, spec in PREP.PREPARED_STAGES.items():
        assert str(spec["path"]) in PREP.EXPECTED
        assert str(spec["path"]).endswith(".jsonl")
        assert not str(spec["path"]).endswith(".answers.json")


def test_verifier_reports_the_prepared_freeze_state() -> None:
    """The preparation verifier checks the prepared register and its binding."""
    generated = VERIFY.generated_stage_entries()
    assert set(generated) == {"full", "benchmark-smoke"}
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        failures = VERIFY.validate_prepared_stage_register({}, directory / "r.json")
        assert failures, "a receipt with no prepared register passed verification"

        ids = [f"t{index}" for index in range(10)]
        screen = fake_screen(directory, ids)
        register = {
            "version": 1,
            "stageManifestSha256": VERIFY.sha256_file(VERIFY.STAGE_MANIFEST),
            "stages": {
                "full": {
                    "path": screen.name,
                    "taskCount": len(ids),
                    "artifactSha256": VERIFY.sha256_file(screen),
                    "orderedTaskIdsSha256": VERIFY.ordered_ids_sha256(ids),
                }
            },
        }
        register_path = directory / VERIFY.PREPARED_REGISTER_NAME
        register_path.write_text(json.dumps(register, indent=2) + "\n", encoding="utf-8")
        receipt_path = directory / "benchmark-preparation.json"
        receipt = {
            "benchmarkRevision": "0" * 40,
            VERIFY.PREPARED_REGISTER_KEY: {
                "fileSha256": "e" * 64,
                "stageManifestSha256": register["stageManifestSha256"],
                "benchmarkRevision": "0" * 40,
                "stages": register["stages"],
            },
        }
        failures = VERIFY.validate_prepared_stage_register(receipt, receipt_path)
        assert any("digest" in failure for failure in failures), failures


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok " + test.__name__)
    print("Stage identity + qualification ladder tests passed (%d cases)." % len(tests))


if __name__ == "__main__":
    main()
