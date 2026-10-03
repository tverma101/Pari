#!/usr/bin/env python3
"""Repro-manifest gate tests for the SemanticQA official conversion chain (#66/#65).

build-english-core-repro-manifest.py used to accept a SemanticQA official report
whose only conversion evidence was a `predictionPolicy` sentence plus
`manifestVersion >= 2`. A self-described policy string is exactly what issue #66
forbids as promotion proof, and version 2 manifests carry no converter identity
at all.

These tests pin the replacement behaviour: promotion now requires the current
converter manifest version plus a converter chain the builder can re-derive from
the registered protocol registry, an official pinned postprocessor import bound to
the evaluator checkout, and an empty provenanceErrors list from the wrapper that
ran the official metric.

The fixture builds its hashes with the same helpers the converter uses, so a
"valid" artifact here is a genuinely re-derivable chain rather than a pile of
well-formed constants.

Run directly (matching the other benchmark tests) or under pytest:
    python3 test_repro_manifest_semanticqa_conversion_gate.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / "build-english-core-repro-manifest.py"

sys.path.insert(0, str(HERE))

from english_core_converter_provenance import (  # noqa: E402
    CONTRACT_VERSION,
    SEMANTICQA_PROTOCOL_ID,
    conversion_identity,
    protocol_contract_sha256,
)

BENCHMARK = "semanticqa_lcc"
PROTOCOL_VERSION = 1
EVALUATOR_COMMIT = "a" * 40
BENCHMARK_GIT_COMMIT = "d" * 40
BENCHMARK_GIT_TREE = "e" * 40
CONVERTER_SOURCE_SHA = "1" * 64
POSTPROCESSOR_MODULE_SHA = "2" * 64
EVALUATOR_SHA = "3" * 64
CONVERSION_MANIFEST_SHA = "4" * 64
CONVERTED_RESULT_SHA = "5" * 64
OTHER_COMMIT = "b" * 40


def load_builder():
    spec = importlib.util.spec_from_file_location("pari_repro_manifest", BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load repro manifest builder module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = load_builder()


def _converter_provenance() -> dict:
    """A chain that re-derives exactly, built with the converter's own helpers."""
    contract_sha = protocol_contract_sha256(
        BENCHMARK, SEMANTICQA_PROTOCOL_ID, PROTOCOL_VERSION
    )
    conversion_config = {
        "postprocessorSource": "official-pinned-import",
        "postprocessorCommit": EVALUATOR_COMMIT,
        "postprocessorModuleSha256": POSTPROCESSOR_MODULE_SHA,
    }
    return {
        "contractVersion": CONTRACT_VERSION,
        "benchmark": BENCHMARK,
        "protocol": {
            "id": SEMANTICQA_PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "label": "Pari SemanticQA LCC postprocess v1",
            "contractSha256": contract_sha,
        },
        "converterSource": {
            "path": "convert-semanticqa-lcc-official-output.py",
            "sha256": CONVERTER_SOURCE_SHA,
            "bytes": 1234,
        },
        "benchmarkGit": {
            "available": True,
            "reason": None,
            "repositoryRoot": "/tmp/pari",
            "commit": BENCHMARK_GIT_COMMIT,
            "tree": BENCHMARK_GIT_TREE,
            "branch": "codex/english-studio-integration",
            "dirty": False,
        },
        "conversionConfig": conversion_config,
        "identity": conversion_identity(
            benchmark=BENCHMARK,
            protocol_id=SEMANTICQA_PROTOCOL_ID,
            protocol_version=PROTOCOL_VERSION,
            contract_sha256=contract_sha,
            converter_source_sha256=CONVERTER_SOURCE_SHA,
            conversion_config=conversion_config,
        ),
    }


def semanticqa_report() -> dict:
    """A complete, promotion-ready SemanticQA LCC official evaluator report."""
    provenance = _converter_provenance()
    return {
        "version": 3,
        "benchmark": "SemanticQA LCC official protocol evaluation",
        "sourceCommit": EVALUATOR_COMMIT,
        "checkoutDirty": False,
        "promotionEvaluation": True,
        "promotionReady": True,
        "officialEvaluator": {
            "path": "semantic_qa/eval.py",
            "sha256": EVALUATOR_SHA,
            "pythonExecutable": "/usr/bin/python3",
        },
        "conversion": {
            "manifestSha256": CONVERSION_MANIFEST_SHA,
            "manifestVersion": 3,
            "predictionPolicy": (
                "Documentation only: whitespace normalization, then the suffix after "
                "the last 'is: ' if present, else the suffix after the last 'Output:'."
            ),
            "postprocessor": {
                "kind": "official-pinned-import",
                "commit": EVALUATOR_COMMIT,
                "clean": True,
                "moduleSha256": POSTPROCESSOR_MODULE_SHA,
            },
            "converterProvenance": provenance,
            "conversionIdentity": provenance["identity"],
            "provenanceErrors": [],
            "promotionProvenanceReady": True,
        },
        "convertedResult": {"path": "/tmp/converted.json", "sha256": CONVERTED_RESULT_SHA},
        "metrics": {"cases": 305, "correct": 305, "accuracy": 1.0},
    }


def must_pass(data: dict) -> dict:
    kind, blockers, summary, validation = module.official_evidence_blockers("sq", data)
    assert kind == "semanticqa_lcc", f"unexpected kind: {kind!r}"
    assert not blockers, f"unexpected blockers: {blockers!r}"
    assert validation["status"] == "passed"
    assert all(row["ok"] for row in validation["checks"])
    return summary


def must_block(data: dict, suffix: str) -> None:
    kind, blockers, _summary, validation = module.official_evidence_blockers("sq", data)
    assert kind == "semanticqa_lcc"
    expected = f"sq:{suffix}"
    assert expected in blockers, f"expected blocker {expected!r}, got {blockers!r}"
    assert validation["status"] == "failed"
    failed = {row["id"] for row in validation["checks"] if not row["ok"]}
    assert suffix in failed, f"check list does not record {suffix!r}: {sorted(failed)}"


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_complete_rederivable_chain_passes() -> None:
    summary = must_pass(semanticqa_report())
    assert summary["conversionManifestVersion"] == 3
    assert summary["converterProtocolId"] == SEMANTICQA_PROTOCOL_ID
    assert summary["converterProtocolVersion"] == PROTOCOL_VERSION
    assert summary["postprocessorKind"] == "official-pinned-import"
    assert summary["converterSourceSha256"] == CONVERTER_SOURCE_SHA
    assert summary["converterBenchmarkGitCommit"] == BENCHMARK_GIT_COMMIT
    assert module.is_sha256(summary["conversionIdentity"])


def test_prose_alone_cannot_satisfy_the_gate() -> None:
    """A perfect predictionPolicy sentence with no executable proof must block."""
    data = semanticqa_report()
    data["conversion"]["predictionPolicy"] = (
        "whitespace normalization, is: , Output: -- the official postprocessing was applied"
    )
    data["conversion"].pop("converterProvenance")
    must_block(data, "semanticqa_missing_converter_provenance")
    must_block(data, "semanticqa_converter_protocol_not_registered")
    must_block(data, "semanticqa_conversion_identity_does_not_match_recorded_chain")


def test_old_conversion_manifest_version_blocks() -> None:
    """v2 manifests carry no converter identity and must not reach promotion."""
    for stale in (1, 2):
        data = semanticqa_report()
        data["conversion"]["manifestVersion"] = stale
        must_block(data, "semanticqa_conversion_manifest_too_old")


def test_minimum_version_matches_the_converter_floor() -> None:
    assert module.SEMANTICQA_MIN_CONVERSION_MANIFEST_VERSION == 3


def test_provenance_errors_must_be_an_empty_list() -> None:
    data = semanticqa_report()
    data["conversion"]["provenanceErrors"] = [
        "converter_source_sha256_does_not_match_converter_file"
    ]
    must_block(data, "semanticqa_conversion_provenance_errors_not_empty")

    # A missing or non-list field is not an implicit pass.
    for bogus in (None, {}, "none", 0):
        data = semanticqa_report()
        data["conversion"]["provenanceErrors"] = bogus
        must_block(data, "semanticqa_conversion_provenance_errors_not_empty")


def test_promotion_provenance_must_be_ready() -> None:
    data = semanticqa_report()
    data["conversion"]["promotionProvenanceReady"] = False
    must_block(data, "semanticqa_conversion_promotion_provenance_not_ready")


def test_local_mirror_postprocessor_blocks() -> None:
    """The local mirror reproduces the behavior but is not executable proof."""
    data = semanticqa_report()
    data["conversion"]["postprocessor"]["kind"] = "local-mirror"
    must_block(data, "semanticqa_postprocessor_not_official_pinned_import")
    must_block(data, "semanticqa_conversion_config_does_not_match_postprocessor")

    data = semanticqa_report()
    data["conversion"].pop("postprocessor")
    must_block(data, "semanticqa_postprocessor_not_official_pinned_import")


def test_dirty_or_mismatched_postprocessor_checkout_blocks() -> None:
    data = semanticqa_report()
    data["conversion"]["postprocessor"]["clean"] = False
    must_block(data, "semanticqa_postprocessor_not_official_pinned_import")

    data = semanticqa_report()
    data["conversion"]["postprocessor"]["commit"] = OTHER_COMMIT
    must_block(data, "semanticqa_postprocessor_not_official_pinned_import")

    data = semanticqa_report()
    data["conversion"]["postprocessor"]["moduleSha256"] = "not-a-hash"
    must_block(data, "semanticqa_postprocessor_not_official_pinned_import")


def test_unregistered_protocol_blocks() -> None:
    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["protocol"]["id"] = "pari-semanticqa-lcc-postprocess-v2"
    must_block(data, "semanticqa_converter_protocol_not_registered")

    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["protocol"]["version"] = 99
    must_block(data, "semanticqa_converter_protocol_not_registered")

    # A bare bool must not be read as protocol version 1.
    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["protocol"]["version"] = True
    must_block(data, "semanticqa_converter_protocol_not_registered")


def test_tampered_contract_hash_blocks() -> None:
    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["protocol"]["contractSha256"] = "f" * 64
    must_block(data, "semanticqa_converter_contract_sha256_mismatch")
    must_block(data, "semanticqa_conversion_identity_does_not_match_recorded_chain")


def test_tampered_conversion_identity_blocks() -> None:
    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["identity"] = "0" * 64
    must_block(data, "semanticqa_conversion_identity_does_not_match_recorded_chain")

    # The wrapper's convenience copy must agree with the provenance block.
    data = semanticqa_report()
    data["conversion"]["conversionIdentity"] = "0" * 64
    must_block(data, "semanticqa_recorded_conversion_identity_mismatch")


def test_unresolvable_benchmark_git_identity_blocks() -> None:
    """Fail-closed: evidence that cannot be tied to a tree is not promotion grade."""
    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["benchmarkGit"]["available"] = False
    must_block(data, "semanticqa_converter_benchmark_git_identity_unavailable")

    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["benchmarkGit"]["commit"] = "main"
    must_block(data, "semanticqa_converter_benchmark_git_identity_unavailable")


def test_conversion_config_must_match_the_recorded_postprocessor() -> None:
    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["conversionConfig"]["postprocessorCommit"] = OTHER_COMMIT
    must_block(data, "semanticqa_conversion_config_does_not_match_postprocessor")
    must_block(data, "semanticqa_conversion_identity_does_not_match_recorded_chain")

    data = semanticqa_report()
    data["conversion"]["converterProvenance"]["conversionConfig"]["maxCandidates"] = 40
    must_block(data, "semanticqa_conversion_config_does_not_match_postprocessor")


def test_malformed_chain_never_raises() -> None:
    """Official reports are untrusted input; bad shapes become blockers, not tracebacks."""
    for bogus in (None, "chain", [], 5, {"protocol": "nope"}):
        data = semanticqa_report()
        data["conversion"]["converterProvenance"] = bogus
        _kind, blockers, _summary, validation = module.official_evidence_blockers("sq", data)
        assert validation["status"] == "failed"
        assert blockers

    for bogus in (None, "postprocess", [], 7):
        data = semanticqa_report()
        data["conversion"]["postprocessor"] = bogus
        _kind, blockers, _summary, validation = module.official_evidence_blockers("sq", data)
        assert "sq:semanticqa_postprocessor_not_official_pinned_import" in blockers
        assert validation["status"] == "failed"


def test_validation_is_deterministic_and_versioned() -> None:
    data = semanticqa_report()
    first = module.official_evidence_blockers("sq", json.loads(json.dumps(data)))
    second = module.official_evidence_blockers("sq", semanticqa_report())
    assert first == second
    assert first[3]["version"] == module.SEMANTIC_VALIDATION_VERSION
    assert module.SEMANTIC_VALIDATION_VERSION >= 2

    chain_ids = {row["id"] for row in first[3]["checks"]}
    for required in (
        "semanticqa_conversion_provenance_errors_not_empty",
        "semanticqa_converter_protocol_not_registered",
        "semanticqa_converter_contract_sha256_mismatch",
        "semanticqa_conversion_identity_does_not_match_recorded_chain",
        "semanticqa_postprocessor_not_official_pinned_import",
    ):
        assert required in chain_ids, f"{required} is not part of the recorded checks"


def test_official_evidence_is_valid_requires_the_whole_chain() -> None:
    assert module.official_evidence_is_valid(semanticqa_report()) is True

    data = semanticqa_report()
    data["conversion"]["provenanceErrors"] = ["benchmark_git_identity_unavailable"]
    assert module.official_evidence_is_valid(data) is False


def main() -> None:
    tests = [
        test_complete_rederivable_chain_passes,
        test_prose_alone_cannot_satisfy_the_gate,
        test_old_conversion_manifest_version_blocks,
        test_minimum_version_matches_the_converter_floor,
        test_provenance_errors_must_be_an_empty_list,
        test_promotion_provenance_must_be_ready,
        test_local_mirror_postprocessor_blocks,
        test_dirty_or_mismatched_postprocessor_checkout_blocks,
        test_unregistered_protocol_blocks,
        test_tampered_contract_hash_blocks,
        test_tampered_conversion_identity_blocks,
        test_unresolvable_benchmark_git_identity_blocks,
        test_conversion_config_must_match_the_recorded_postprocessor,
        test_malformed_chain_never_raises,
        test_validation_is_deterministic_and_versioned,
        test_official_evidence_is_valid_requires_the_whole_chain,
    ]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print("Repro-manifest SemanticQA conversion gate tests passed.")


if __name__ == "__main__":
    main()
