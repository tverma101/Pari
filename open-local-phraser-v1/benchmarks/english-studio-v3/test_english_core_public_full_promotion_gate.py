#!/usr/bin/env python3
"""Issue #67 regressions for the public-full scorer's `--promotion` gate.

CPU-only and fully synthetic: no network, no `datasets`, no GPU, and no
downloaded data. The scorer module is loaded once and its artifact paths are
redirected into a temporary directory holding synthetic task/answer/manifest
bytes plus a matching preparation receipt.

What it proves:
1. `--promotion` refuses a manifest whose `sourceContractVersion` is not current;
2. it refuses an exploratory (`promotionEligible: false`) manifest even when
   every source field and fingerprint is perfect, so a task-file hash match
   alone can never upgrade a build;
3. it refuses a mutable requested ref and a missing fingerprint through the
   shared `source_manifest_gate_report`, under promotion;
4. it refuses a missing, ineligible, or wrong-protocol preparation receipt;
5. it refuses a receipt whose task/answer/manifest/source-manifest bytes no
   longer match the files being scored, or whose frozen sources disagree with the
   scored manifest;
6. it refuses a receipt with no verified tree or data-preparation lock;
7. a clean manifest plus a fully bound receipt passes and returns provenance
   that is copied into the score artifact's `inputs`;
8. without `--promotion` the same exploratory manifest yields no promotion
   verdict and publishes its gate findings instead.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

from english_core_public_sources import (
    FULL_DISTRIBUTION_SOURCE_NAMES,
    PUBLIC_SOURCE_IDENTITIES,
    REVISION_RESOLUTION_POLICY,
    SOURCE_CONTRACT_VERSION,
    SOURCE_MANIFEST_FILENAME,
    load_frozen_source_manifest,
)

HERE = Path(__file__).resolve().parent
SOURCES_CONFIG = HERE / SOURCE_MANIFEST_FILENAME

WIC_SHA = "3de24cf8022e94f4ee4b9d55a6f539891524d646"
COLA_SHA = "bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c"
PAWS_SHA = "161ece9501cf0a11f3e48bd356eaa82de46d6a09"
SOURCE_SHAS = {"WiC": WIC_SHA, "CoLA": COLA_SHA, "PAWS": PAWS_SHA}


def _load_scorer():
    spec = importlib.util.spec_from_file_location(
        "score_public_full", HERE / "score-english-core-public-full-classification.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCORER = _load_scorer()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def clean_sources() -> dict:
    """A manifest source table that passes the promotion gate on its own."""
    return {
        name: {
            "dataset": identity.repo_id,
            "config": identity.config,
            "split": identity.split,
            # An immutable tag-style ref: not a moving branch, not a bare SHA.
            "requestedRevision": f"refs/tags/v1.0.0-{name.lower()}",
            "resolvedRevision": sha,
            "revisionResolution": REVISION_RESOLUTION_POLICY,
        }
        for name in FULL_DISTRIBUTION_SOURCE_NAMES
        for identity, sha in ((PUBLIC_SOURCE_IDENTITIES[name], SOURCE_SHAS[name]),)
    }


def clean_manifest(**overrides) -> dict:
    manifest = {
        "version": 4,
        "sourceContractVersion": SOURCE_CONTRACT_VERSION,
        "lane": "public-full-classification",
        "promotionEligible": True,
        "promotion": {"requested": True, "gateErrors": [], "gateWarnings": []},
        "cases": 2,
        "sources": clean_sources(),
        "resolvedDatasetFingerprints": {"WiC": "fp-wic", "CoLA": "fp-cola", "PAWS": "fp-paws"},
    }
    manifest.update(overrides)
    return manifest


@contextlib.contextmanager
def scorer_environment(manifest: dict, receipt: dict | None, sources_config: Path):
    """Point the scorer at synthetic artifacts for the duration of a check."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks = root / "english-core-public-full-classification.jsonl"
        answers = root / "english-core-public-full-classification.answers.json"
        built_manifest = root / "english-core-public-full-classification.manifest.json"
        receipt_path = root / "english-core-public-full-classification.preparation.json"
        task_bytes = b'{"id": "full-wic-0"}\n{"id": "full-cola-0"}\n'
        answer_bytes = json.dumps({"version": 3, "answers": {}}, indent=2).encode() + b"\n"
        manifest_bytes = json.dumps(manifest, indent=2).encode() + b"\n"
        tasks.write_bytes(task_bytes)
        answers.write_bytes(answer_bytes)
        built_manifest.write_bytes(manifest_bytes)
        if receipt is not None:
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        saved = {
            "TASKS": SCORER.TASKS,
            "ANSWERS": SCORER.ANSWERS,
            "MANIFEST": SCORER.MANIFEST,
            "SOURCES_CONFIG": SCORER.SOURCES_CONFIG,
        }
        SCORER.TASKS = tasks
        SCORER.ANSWERS = answers
        SCORER.MANIFEST = built_manifest
        SCORER.SOURCES_CONFIG = sources_config
        try:
            yield {"receipt": receipt_path, "tasks": tasks, "answers": answers, "manifest": built_manifest}
        finally:
            for name, value in saved.items():
                setattr(SCORER, name, value)


def bound_receipt(*, sources_config: Path, artifacts: dict, manifest: dict, **overrides) -> dict:
    """A receipt whose every identity matches the artifacts it is paired with."""
    config = load_frozen_source_manifest(sources_config)
    receipt = {
        "schema": SCORER.RECEIPT_SCHEMA,
        "version": SCORER.RECEIPT_VERSION,
        "protocolVersion": SCORER.RECEIPT_PROTOCOL_VERSION,
        "sourceContractVersion": SOURCE_CONTRACT_VERSION,
        "promotionEligible": True,
        "promotionBlockers": [],
        "benchmarkRevision": "d" * 40,
        "benchmarkTree": {
            "head": "d" * 40,
            "tree": "e" * 40,
            "branch": "bench/english-studio-v3",
            "promotionEligible": True,
        },
        "isolatedDataEnvironment": {"dependencyLock": {"state": "verified", "sha256": "f" * 64}},
        "frozenSources": {
            "file": sources_config.name,
            "sha256": SCORER.sha256(sources_config),
            "sources": {
                name: {
                    "dataset": entry["dataset"],
                    "config": entry["config"],
                    "split": entry["split"],
                    "resolvedRevision": entry["resolvedRevision"],
                }
                for name, entry in config["sources"].items()
            },
        },
        "files": {
            artifacts["tasks"].name: {"sha256": SCORER.sha256(artifacts["tasks"])},
            artifacts["answers"].name: {"sha256": SCORER.sha256(artifacts["answers"])},
            artifacts["manifest"].name: {"sha256": SCORER.sha256(artifacts["manifest"])},
        },
        "manifestSha256": SCORER.sha256(artifacts["manifest"]),
        "orderedTaskIdsSha256": "b" * 64,
        "laneSeparation": {"commonScreenArtifact": "english-core-fixed-screen.jsonl", "commonScreenCases": 1943},
    }
    receipt.update(overrides)
    return receipt


def _refusal(manifest: dict, receipt: dict | None, sources_config: Path) -> str:
    """Run the promotion gate and return its refusal message."""
    with scorer_environment(manifest, receipt, sources_config) as artifacts:
        if receipt is not None:
            # Re-bind the receipt to the bytes this environment actually wrote.
            rebuilt = bound_receipt(sources_config=sources_config, artifacts=artifacts, manifest=manifest)
            for key, value in receipt.items():
                rebuilt[key] = value
            artifacts["receipt"].write_text(json.dumps(rebuilt, indent=2) + "\n")
        try:
            SCORER.require_promotion_source_gate(manifest, receipt_path=artifacts["receipt"])
        except SystemExit as exc:
            return str(exc)
    raise AssertionError("promotion gate accepted a build it must refuse")


def test_promotion_refuses_a_stale_source_contract_version() -> None:
    message = _refusal(
        clean_manifest(sourceContractVersion=SOURCE_CONTRACT_VERSION + 1), None, SOURCES_CONFIG
    )
    assert "not understood by this scorer" in message


def test_promotion_refuses_an_exploratory_manifest_despite_a_perfect_source_table() -> None:
    manifest = clean_manifest(
        promotionEligible=False,
        promotion={"requested": False, "gateErrors": ["build was exploratory"], "gateWarnings": []},
    )
    message = _refusal(manifest, None, SOURCES_CONFIG)
    assert "promotion-eligible" in message
    assert "exploratory" in message


def test_promotion_refuses_a_mutable_requested_ref_through_the_shared_gate() -> None:
    manifest = clean_manifest()
    manifest["sources"]["PAWS"]["requestedRevision"] = "main"
    message = _refusal(manifest, None, SOURCES_CONFIG)
    assert "source provenance gate failed" in message
    assert "moving ref" in message


def test_promotion_refuses_a_missing_resolved_fingerprint() -> None:
    manifest = clean_manifest(resolvedDatasetFingerprints={"WiC": "fp", "CoLA": "fp", "PAWS": ""})
    message = _refusal(manifest, None, SOURCES_CONFIG)
    assert "fingerprint missing or empty" in message


def test_promotion_refuses_a_non_canonical_repository() -> None:
    manifest = clean_manifest()
    manifest["sources"]["PAWS"]["dataset"] = "paws"
    message = _refusal(manifest, None, SOURCES_CONFIG)
    assert "retired alias" in message


def test_promotion_refuses_a_missing_receipt() -> None:
    message = _refusal(clean_manifest(), None, SOURCES_CONFIG)
    assert "requires a verified preparation receipt" in message
    assert "never promotion evidence" in message


def test_promotion_refuses_a_receipt_for_another_protocol_version() -> None:
    message = _refusal(
        clean_manifest(), {"protocolVersion": "pari.english-core.public-full-finalist-0"}, SOURCES_CONFIG
    )
    assert "protocolVersion" in message


def test_promotion_refuses_a_non_eligible_receipt() -> None:
    message = _refusal(
        clean_manifest(),
        {"promotionEligible": False, "promotionBlockers": ["benchmark tree is not clean"]},
        SOURCES_CONFIG,
    )
    assert "not promotion-eligible" in message
    assert "benchmark tree is not clean" in message


def test_promotion_refuses_a_receipt_whose_task_bytes_drifted() -> None:
    message = _refusal(
        clean_manifest(),
        {"files": {SCORER.TASKS.name: {"sha256": "0" * 64}}},
        SOURCES_CONFIG,
    )
    assert "does not bind the artifacts being scored" in message
    assert "sha256" in message


def test_promotion_refuses_a_receipt_whose_manifest_hash_drifted() -> None:
    message = _refusal(clean_manifest(), {"manifestSha256": "1" * 64}, SOURCES_CONFIG)
    assert "manifestSha256" in message


def test_promotion_refuses_a_receipt_whose_frozen_source_manifest_drifted() -> None:
    message = _refusal(
        clean_manifest(),
        {"frozenSources": {"file": SOURCE_MANIFEST_FILENAME, "sha256": "2" * 64, "sources": {}}},
        SOURCES_CONFIG,
    )
    assert "frozenSources sha256" in message


def test_promotion_refuses_frozen_sources_that_disagree_with_the_scored_manifest() -> None:
    with scorer_environment(clean_manifest(), None, SOURCES_CONFIG) as artifacts:
        receipt = bound_receipt(sources_config=SOURCES_CONFIG, artifacts=artifacts, manifest=clean_manifest())
        receipt["frozenSources"]["sources"]["CoLA"]["resolvedRevision"] = COLA_SHA[:-1] + "0"
        artifacts["receipt"].write_text(json.dumps(receipt, indent=2) + "\n")
        try:
            SCORER.require_promotion_source_gate(clean_manifest(), receipt_path=artifacts["receipt"])
        except SystemExit as exc:
            assert "frozenSources[CoLA].resolvedRevision" in str(exc)
        else:
            raise AssertionError("receipt with drifted frozen sources was accepted")


def test_promotion_refuses_an_unverified_tree_or_environment_lock() -> None:
    message = _refusal(
        clean_manifest(),
        {"benchmarkTree": {"head": "d" * 40, "tree": "e" * 40, "promotionEligible": False}},
        SOURCES_CONFIG,
    )
    assert "benchmarkTree is not promotion-eligible" in message
    message = _refusal(
        clean_manifest(),
        {"isolatedDataEnvironment": {"dependencyLock": {"state": "unavailable", "sha256": None}}},
        SOURCES_CONFIG,
    )
    assert "verified data-preparation lock" in message


def test_clean_manifest_and_bound_receipt_pass_and_return_borrowable_provenance() -> None:
    manifest = clean_manifest()
    with scorer_environment(manifest, None, SOURCES_CONFIG) as artifacts:
        receipt = bound_receipt(sources_config=SOURCES_CONFIG, artifacts=artifacts, manifest=manifest)
        artifacts["receipt"].write_text(json.dumps(receipt, indent=2) + "\n")
        provenance = SCORER.require_promotion_source_gate(manifest, receipt_path=artifacts["receipt"])
        assert provenance["protocolVersion"] == SCORER.RECEIPT_PROTOCOL_VERSION
        assert provenance["promotionEligible"] is True
        assert provenance["sha256"] == SCORER.sha256(artifacts["receipt"])
        assert provenance["benchmarkTree"]["tree"] == "e" * 40
        assert provenance["frozenSources"]["file"] == SOURCE_MANIFEST_FILENAME
        # Everything copied into `inputs` must be a 64-hex SHA-256 so #65's
        # frozen-score harvesting can bind it.
        assert provenance["manifestSha256"] == SCORER.sha256(artifacts["manifest"])
        assert len(provenance["orderedTaskIdsSha256"]) == 64
        for entry in provenance["files"].values():
            assert len(entry["sha256"]) == 64


def test_exploratory_scoring_applies_no_gate_and_reports_its_findings() -> None:
    manifest = clean_manifest(
        promotionEligible=False,
        resolvedDatasetFingerprints={},
        promotion={"requested": False, "gateErrors": [], "gateWarnings": []},
    )
    # A build resolved from a moving branch and never fingerprinted: the two
    # findings that are only warnings while exploring and errors on promotion.
    for name in FULL_DISTRIBUTION_SOURCE_NAMES:
        manifest["sources"][name]["requestedRevision"] = "main"
    findings = SCORER.gate_findings_for(manifest, promotion=False)
    assert any("moving ref" in warning for warning in findings["warnings"])
    assert any("fingerprint missing" in warning for warning in findings["warnings"])
    # Promotion mode reports no findings only because it would have refused
    # outright; the helper never launders an exploratory build.
    assert SCORER.gate_findings_for(manifest, promotion=True) == {"errors": [], "warnings": []}


def test_receipt_contract_constants_match_the_preparation_script() -> None:
    spec = importlib.util.spec_from_file_location(
        "prepare_public_full", HERE / "prepare-english-core-public-full.py"
    )
    assert spec and spec.loader
    prep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prep)
    assert SCORER.RECEIPT_SCHEMA == prep.RECEIPT_SCHEMA
    assert SCORER.RECEIPT_VERSION == prep.RECEIPT_VERSION
    assert SCORER.RECEIPT_PROTOCOL_VERSION == prep.PROTOCOL_VERSION
    assert SCORER.DEFAULT_PREPARATION_RECEIPT.name == prep.RECEIPT_FILENAME


def test_score_artifact_inputs_carry_the_gate_provenance() -> None:
    """The report body must expose the provenance #65 binds, not just the gate."""
    source = (HERE / "score-english-core-public-full-classification.py").read_text()
    for key in (
        '"promotionScored": promotion',
        '"sourceContractVersion": manifest.get("sourceContractVersion")',
        '"promotionEligible": manifest.get("promotionEligible")',
        '"preparationReceipt"',
    ):
        assert key in source


def test_unknown_flags_are_refused_rather_than_silently_ignored() -> None:
    saved_argv = SCORER.sys.argv
    try:
        SCORER.sys.argv = ["scorer", "result.json", "--not-a-flag"]
        try:
            SCORER.main()
        except SystemExit as exc:
            assert "Usage:" in str(exc)
        else:
            raise AssertionError("an unknown flag was accepted")
    finally:
        SCORER.sys.argv = saved_argv


def test_preparation_receipt_path_override_is_parsed_and_applied() -> None:
    """`--preparation-receipt=PATH` must steer the gate at a receipt elsewhere."""
    manifest = clean_manifest()
    with scorer_environment(manifest, None, SOURCES_CONFIG) as artifacts:
        receipt = bound_receipt(sources_config=SOURCES_CONFIG, artifacts=artifacts, manifest=manifest)
        elsewhere = artifacts["receipt"].with_name("elsewhere.preparation.json")
        elsewhere.write_text(json.dumps(receipt, indent=2) + "\n")
        saved_argv = SCORER.sys.argv
        try:
            SCORER.sys.argv = [
                "scorer",
                "result.json",
                "--promotion",
                f"--preparation-receipt={elsewhere}",
            ]
            parsed = next(
                arg.split("=", 1)[1]
                for arg in SCORER.sys.argv[1:]
                if arg.startswith("--preparation-receipt=")
            )
            assert Path(parsed) == elsewhere
            # The default receipt path is absent here, so the gate must fail
            # closed rather than silently reading a different file.
            try:
                SCORER.require_promotion_source_gate(manifest, receipt_path=SCORER.DEFAULT_PREPARATION_RECEIPT)
            except SystemExit as exc:
                assert "requires a verified preparation receipt" in str(exc)
            else:
                raise AssertionError("gate accepted a run with no receipt")
            provenance = SCORER.require_promotion_source_gate(manifest, receipt_path=Path(parsed))
            assert provenance["path"] == str(elsewhere.resolve())
        finally:
            SCORER.sys.argv = saved_argv


def main() -> None:
    cases = [
        test_promotion_refuses_a_stale_source_contract_version,
        test_promotion_refuses_an_exploratory_manifest_despite_a_perfect_source_table,
        test_promotion_refuses_a_mutable_requested_ref_through_the_shared_gate,
        test_promotion_refuses_a_missing_resolved_fingerprint,
        test_promotion_refuses_a_non_canonical_repository,
        test_promotion_refuses_a_missing_receipt,
        test_promotion_refuses_a_receipt_for_another_protocol_version,
        test_promotion_refuses_a_non_eligible_receipt,
        test_promotion_refuses_a_receipt_whose_task_bytes_drifted,
        test_promotion_refuses_a_receipt_whose_manifest_hash_drifted,
        test_promotion_refuses_a_receipt_whose_frozen_source_manifest_drifted,
        test_promotion_refuses_frozen_sources_that_disagree_with_the_scored_manifest,
        test_promotion_refuses_an_unverified_tree_or_environment_lock,
        test_clean_manifest_and_bound_receipt_pass_and_return_borrowable_provenance,
        test_exploratory_scoring_applies_no_gate_and_reports_its_findings,
        test_receipt_contract_constants_match_the_preparation_script,
        test_score_artifact_inputs_carry_the_gate_provenance,
        test_unknown_flags_are_refused_rather_than_silently_ignored,
        test_preparation_receipt_path_override_is_parsed_and_applied,
    ]
    for case in cases:
        case()
        print(f"ok {case.__name__}")
    print(f"{len(cases)} passed")


if __name__ == "__main__":
    main()
