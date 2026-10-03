#!/usr/bin/env python3
"""Semantic-validation tests for recognized official evaluator artifacts.

Covers the three recognized families (SWORDS, JFLEG, SemanticQA LCC), the
versioned validation contract, byte-hashability of unknown artifact types, and
the rule that a recognized-but-invalid artifact fails promotion readiness.

Run directly (matching the other benchmark tests) or under pytest:
    python3 test_official_evidence_semantic_validation.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / "build-english-core-repro-manifest.py"
SCHEMA = HERE / "english-core-official-evidence-schema.json"

sys.path.insert(0, str(HERE))

from english_core_converter_provenance import (  # noqa: E402
    CONTRACT_VERSION,
    SEMANTICQA_PROTOCOL_ID,
    conversion_identity,
    protocol_contract_sha256,
)

SHA = "b" * 64
GIT_SHA = "a" * 40
OTHER_GIT_SHA = "c" * 40

# The SemanticQA fixture needs distinct digests so the postprocessor binding is
# actually checked (sourceCommit must agree with postprocessor.commit) and the
# converter source hash can be told apart from the surrounding generic SHA.
SEMANTICQA_BENCHMARK = "semanticqa_lcc"
SEMANTICQA_PROTOCOL_VERSION = 1
SEMANTICQA_CONVERTER_SHA = "1" * 64
SEMANTICQA_POSTPROCESSOR_SHA = "2" * 64
SEMANTICQA_EVALUATOR_SHA = "3" * 64
SEMANTICQA_CONVERTED_RESULT_SHA = "5" * 64


def load_builder():
    spec = importlib.util.spec_from_file_location("pari_repro_manifest", BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load repro manifest builder module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Fixtures. Each returns a *valid* official artifact; tests mutate one field at
# a time so a failure identifies exactly which semantic rule fired.
# --------------------------------------------------------------------------


def swords_fixture() -> dict:
    return {
        "version": 2,
        "purpose": "Frozen output from SWORDS' official evaluator",
        "swordsRepository": "/tmp/swords",
        "swordsRepositoryRevision": GIT_SHA,
        "swordsWorktreeDirty": False,
        "officialDatasetId": "swords_parsed_en",
        "officialDatasetSha256": SHA,
        "expectedBenchmarkSha256": SHA,
        "officialModuleSha256": {
            "swords/cli.py": SHA,
            "swords/eval.py": SHA,
            "swords/datasets.py": SHA,
            "swords/lemma.py": SHA,
            "swords/run.py": SHA,
            "swords/__init__.py": SHA,
        },
        "lsrSha256": SHA,
        "conversionManifestSha256": SHA,
        "metricsJsonSha256": SHA,
        # #66: Pari's candidate parser is score-affecting, so the archived result
        # carries the verified converter chain, not just the converted artifact.
        "conversionChain": {
            "converterSource": {"path": "convert-swords-english-core-output.py", "sha256": SHA},
            "converterProtocol": {
                "id": "pari-swords-candidate-parser",
                "version": 1,
                "contractSha256": SHA,
            },
            "conversionIdentity": SHA,
            "conversionConfig": {"maxCandidates": 40, "substitutesLemmatized": False},
            "coverage": {
                "targets": 2,
                "convertedTargets": 2,
                "missingOutputs": 0,
                "extraOutputs": 0,
                "emptyCandidateOutputs": 0,
                "truncatedTargets": 0,
            },
            "verifiedByWrapper": True,
        },
        "metrics": {
            "lenient_a_f@10": 0.5,
            "lenient_c_f@10": 0.4,
            "strict_a_f@10": 0.3,
            "strict_c_f@10": 0.2,
            "strict_c_p@1": 0.1,
            # Optional official metric outside the required core set.
            "strict_c_p@10": 0.45,
        },
    }


def jfleg_fixture() -> dict:
    return {
        "version": 4,
        "purpose": "Frozen output from JFLEG's official GLEU evaluator",
        "jflegRepository": "/tmp/jfleg",
        "jflegRepositoryRevision": GIT_SHA,
        "jflegWorktreeDirty": False,
        "evaluatorSha256": SHA,
        "sourceSha256": SHA,
        "hypothesisSha256": SHA,
        "conversionManifestSha256": SHA,
        "references": [
            {"path": f"/tmp/jfleg/refs/ref{i}.txt", "sha256": f"{i:064x}"} for i in range(1, 5)
        ],
        # #66: the one-line normalizer is a versioned, bound conversion contract.
        "conversionChain": {
            "converterSource": {"path": "convert-jfleg-english-core-output.py", "sha256": SHA},
            "converterProtocol": {
                "id": "pari-jfleg-one-line-normalizer",
                "version": 1,
                "contractSha256": SHA,
            },
            "conversionIdentity": SHA,
            "conversionConfig": {"normalizerProtocol": "pari-jfleg-one-line-normalizer@1"},
            "coverage": {
                "cases": 2,
                "hypotheses": 2,
                "missingOutputs": 0,
                "extraOutputs": 0,
                "emptyOutputs": 0,
                "normalizedChangedRows": 1,
            },
            "rawHypotheses": [
                {
                    "id": "j1",
                    "rawHypothesis": "  a\nb ",
                    "normalizedHypothesis": "a b",
                    "missingOutput": False,
                    "changedByNormalization": True,
                }
            ],
            "verifiedByWrapper": True,
        },
        "protocol": {
            "metric": "official JFLEG GLEU",
            "iterations": 500,
            "referencesUsed": 4,
        },
        "returnCode": 0,
        "stdout": "GLEU score: 12.3456\nConfidence interval: [11.9, 12.8]\n",
        "stdoutSha256": SHA,
    }


def semanticqa_converter_provenance() -> dict:
    """Re-derivable converter chain, built with the converter's own helpers."""
    contract_sha = protocol_contract_sha256(
        SEMANTICQA_BENCHMARK, SEMANTICQA_PROTOCOL_ID, SEMANTICQA_PROTOCOL_VERSION
    )
    conversion_config = {
        "postprocessorSource": "official-pinned-import",
        "postprocessorCommit": GIT_SHA,
        "postprocessorModuleSha256": SEMANTICQA_POSTPROCESSOR_SHA,
    }
    return {
        "contractVersion": CONTRACT_VERSION,
        "benchmark": SEMANTICQA_BENCHMARK,
        "protocol": {
            "id": SEMANTICQA_PROTOCOL_ID,
            "version": SEMANTICQA_PROTOCOL_VERSION,
            "label": "Pari SemanticQA LCC postprocess v1",
            "contractSha256": contract_sha,
        },
        "converterSource": {
            "path": "convert-semanticqa-lcc-official-output.py",
            "sha256": SEMANTICQA_CONVERTER_SHA,
            "bytes": 1234,
        },
        "benchmarkGit": {
            "available": True,
            "reason": None,
            "repositoryRoot": "/tmp/pari",
            "commit": "d" * 40,
            "tree": "e" * 40,
            "branch": "codex/english-studio-integration",
            "dirty": False,
        },
        "conversionConfig": conversion_config,
        "identity": conversion_identity(
            benchmark=SEMANTICQA_BENCHMARK,
            protocol_id=SEMANTICQA_PROTOCOL_ID,
            protocol_version=SEMANTICQA_PROTOCOL_VERSION,
            contract_sha256=contract_sha,
            converter_source_sha256=SEMANTICQA_CONVERTER_SHA,
            conversion_config=conversion_config,
        ),
    }


def semanticqa_fixture() -> dict:
    correct = 305
    provenance = semanticqa_converter_provenance()
    return {
        "version": 2,
        "benchmark": "SemanticQA LCC official protocol evaluation",
        "sourceCommit": GIT_SHA,
        "checkoutDirty": False,
        "promotionEvaluation": True,
        "promotionReady": True,
        "officialEvaluator": {
            "path": "semantic_qa/eval.py",
            "sha256": SEMANTICQA_EVALUATOR_SHA,
            "pythonExecutable": "/usr/bin/python3",
            # #66: the recorded environment describes the *selected* interpreter,
            # not the wrapper process.
            "environmentSource": "queried-from --python executable via subprocess probe",
            "environment": {
                "resolvedExecutable": "/opt/venv/bin/python3",
                "pythonVersion": "3.11.9 (main, Jan 1 1970, 00:00:00)",
                "pythonImplementation": "CPython",
                "platform": "Linux-6.1-x86_64",
                "machine": "x86_64",
                "packages": {
                    "numpy": "1.26.4",
                    "scikit-learn": "1.4.2",
                    "evaluate": "0.4.2",
                    "nltk": "3.8.1",
                    "pandas": "2.1.4",
                    "sacrebleu": "2.4.0",
                    "datasets": "2.18.0",
                },
            },
        },
        "conversion": {
            "manifestSha256": SHA,
            "manifestVersion": 3,
            "predictionPolicy": (
                "Documentation only: whitespace normalization, then the suffix after "
                "the last 'is: ' if present, else the suffix after the last 'Output:'."
            ),
            # #66: the prose above is documentation. Fidelity is proven by these.
            "postprocessor": {
                "kind": "official-pinned-import",
                "commit": GIT_SHA,
                "clean": True,
                "moduleSha256": SEMANTICQA_POSTPROCESSOR_SHA,
            },
            "converterProvenance": provenance,
            "conversionIdentity": provenance["identity"],
            "provenanceErrors": [],
            "promotionProvenanceReady": True,
        },
        "convertedResult": {
            "path": "/tmp/converted.json",
            "sha256": SEMANTICQA_CONVERTED_RESULT_SHA,
        },
        "metrics": {"cases": 305, "correct": correct, "accuracy": 1.0},
    }


FIXTURES = {
    "swords": swords_fixture,
    "jfleg": jfleg_fixture,
    "semanticqa_lcc": semanticqa_fixture,
}


def must_block(module, label: str, data: dict, suffix: str) -> None:
    _kind, blockers, _summary, validation = module.official_evidence_blockers(label, data)
    expected = f"{label}:{suffix}"
    assert expected in blockers, f"expected blocker {expected!r}, got {blockers!r}"
    assert validation["status"] == "failed"
    failed = {row["id"] for row in validation["checks"] if not row["ok"]}
    assert suffix in failed, f"check list does not record {suffix!r}: {failed!r}"


def must_pass(module, label: str, data: dict) -> dict:
    kind, blockers, summary, validation = module.official_evidence_blockers(label, data)
    assert not blockers, f"unexpected blockers for {kind}: {blockers!r}"
    assert validation["status"] == "passed"
    assert validation["kind"] == kind
    assert all(row["ok"] for row in validation["checks"])
    return validation


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_valid_fixtures_pass() -> None:
    for kind, fixture in FIXTURES.items():
        validation = must_pass(module, kind, fixture())
        assert validation["kind"] == kind
        assert validation["checks"], f"{kind} recorded no checks"
        assert module.official_evidence_is_valid(fixture())


# --------------------------------------------------------------------------
# #66 regression: archived official artifacts must carry a verified converter
# chain. The wrappers enforce this; these assertions pin the artifact shape so a
# future wrapper edit that drops the chain fails here instead of silently
# producing promotion-ready evidence with no converter identity.
# --------------------------------------------------------------------------


def _converter_chain(data: dict) -> dict:
    chain = data.get("conversionChain")
    if not isinstance(chain, dict):
        chain = data.get("conversion")
    assert isinstance(chain, dict), "archived official artifact lost its conversion chain"
    return chain


def test_swords_artifact_carries_verified_converter_chain() -> None:
    chain = _converter_chain(swords_fixture())
    assert chain["verifiedByWrapper"] is True
    assert chain["converterProtocol"]["id"] == "pari-swords-candidate-parser"
    assert chain["converterProtocol"]["version"] == 1
    assert module.is_sha256(chain["converterProtocol"]["contractSha256"])
    assert module.is_sha256(chain["converterSource"]["sha256"])
    assert module.is_sha256(chain["conversionIdentity"])
    assert chain["conversionConfig"] == {"maxCandidates": 40, "substitutesLemmatized": False}
    assert chain["coverage"]["truncatedTargets"] == 0


def test_jfleg_artifact_carries_versioned_normalization_chain() -> None:
    chain = _converter_chain(jfleg_fixture())
    assert chain["verifiedByWrapper"] is True
    assert chain["converterProtocol"]["id"] == "pari-jfleg-one-line-normalizer"
    assert chain["conversionConfig"] == {
        "normalizerProtocol": "pari-jfleg-one-line-normalizer@1"
    }
    assert chain["coverage"]["normalizedChangedRows"] == 1
    raw = chain["rawHypotheses"][0]
    assert raw["changedByNormalization"] is True
    assert raw["rawHypothesis"] != raw["normalizedHypothesis"]


def test_semanticqa_artifact_carries_official_postprocessor_provenance() -> None:
    conversion = semanticqa_fixture()["conversion"]
    assert conversion["promotionProvenanceReady"] is True
    assert conversion["provenanceErrors"] == []
    assert module.is_sha256(conversion["conversionIdentity"])
    assert conversion["manifestVersion"] >= module.SEMANTICQA_MIN_CONVERSION_MANIFEST_VERSION
    postprocessor = conversion["postprocessor"]
    assert postprocessor["kind"] == "official-pinned-import"
    assert module.is_git_sha(postprocessor["commit"])
    assert postprocessor["clean"] is True
    assert module.is_sha256(postprocessor["moduleSha256"])

    # #65/#66: the promotion proof is the re-derivable chain, not the prose above.
    provenance = conversion["converterProvenance"]
    assert provenance["contractVersion"] == CONTRACT_VERSION
    assert provenance["protocol"]["id"] == SEMANTICQA_PROTOCOL_ID
    assert provenance["protocol"]["version"] == SEMANTICQA_PROTOCOL_VERSION
    assert provenance["protocol"]["contractSha256"] == protocol_contract_sha256(
        SEMANTICQA_BENCHMARK, SEMANTICQA_PROTOCOL_ID, SEMANTICQA_PROTOCOL_VERSION
    )
    assert provenance["benchmarkGit"]["available"] is True
    assert module.is_git_sha(provenance["benchmarkGit"]["commit"])
    assert module.is_git_sha(provenance["benchmarkGit"]["tree"])
    assert provenance["conversionConfig"] == {
        "postprocessorSource": postprocessor["kind"],
        "postprocessorCommit": postprocessor["commit"],
        "postprocessorModuleSha256": postprocessor["moduleSha256"],
    }
    # Recomputing from the recorded chain must reproduce both identity copies,
    # so a hand-written constant cannot stand in for the real content address.
    recomputed = conversion_identity(
        benchmark=provenance["benchmark"],
        protocol_id=provenance["protocol"]["id"],
        protocol_version=provenance["protocol"]["version"],
        contract_sha256=provenance["protocol"]["contractSha256"],
        converter_source_sha256=provenance["converterSource"]["sha256"],
        conversion_config=provenance["conversionConfig"],
    )
    assert provenance["identity"] == recomputed
    assert conversion["conversionIdentity"] == recomputed


def test_semanticqa_environment_comes_from_the_selected_interpreter() -> None:
    evaluator = semanticqa_fixture()["officialEvaluator"]
    assert "queried-from --python executable" in evaluator["environmentSource"]
    env = evaluator["environment"]
    assert env["resolvedExecutable"] != evaluator["pythonExecutable"]
    assert env["resolvedExecutable"].startswith("/opt/")
    assert env["pythonImplementation"] == "CPython"
    assert env["machine"]
    packages = env["packages"]
    for critical in ("numpy", "scikit-learn", "evaluate"):
        assert packages[critical], f"{critical} version missing from evaluator environment"


def test_validation_is_deterministic() -> None:
    """Same bytes in, same verdict and same ordered check list out."""
    for fixture in FIXTURES.values():
        data = fixture()
        first = module.official_evidence_blockers("lbl", data)
        second = module.official_evidence_blockers("lbl", json.loads(json.dumps(data)))
        assert first == second, "semantic validation is not deterministic"


def test_validation_metadata_is_versioned() -> None:
    manifest_level = {
        "version": module.SEMANTIC_VALIDATION_VERSION,
        "schema": "english-core-official-evidence-schema.json",
        "recognizedKinds": list(module.RECOGNIZED_OFFICIAL_KINDS),
        "unknownArtifactPolicy": "byte-hash-only",
    }
    assert isinstance(manifest_level["version"], int)
    assert manifest_level["version"] >= 1
    assert sorted(manifest_level["recognizedKinds"]) == ["jfleg", "semanticqa_lcc", "swords"]

    for kind, fixture in FIXTURES.items():
        validation = module.official_evidence_blockers(kind, fixture())[3]
        assert validation["version"] == module.SEMANTIC_VALIDATION_VERSION
        assert set(validation) == {"version", "kind", "status", "checks", "summary"}
        for row in validation["checks"]:
            assert set(row) == {"id", "ok"}
            assert isinstance(row["ok"], bool)
            assert isinstance(row["id"], str) and row["id"]


def test_schema_file_matches_emitted_records() -> None:
    """The dedicated schema must stay in step with the builder's output."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) == set(module.official_evidence_blockers("l", {})[3])
    assert schema["properties"]["status"]["enum"] == ["passed", "failed", "unrecognized"]
    assert set(schema["properties"]["kind"]["enum"]) == {"swords", "jfleg", "semanticqa_lcc", None}
    assert set(module.RECOGNIZED_OFFICIAL_KINDS) == set(schema["properties"]["kind"]["enum"]) - {None}

    # Every check id the builder can emit must satisfy the schema's id contract.
    check_schema = schema["properties"]["checks"]["items"]
    for fixture in FIXTURES.values():
        for row in module.official_evidence_blockers("l", fixture())[3]["checks"]:
            assert set(row) == set(check_schema["required"])
            assert row["id"] and isinstance(row["ok"], bool)


def test_unknown_artifact_is_unrecognized_but_byte_hashable() -> None:
    unknown = {"benchmark": "some-other-benchmark v2", "score": 0.42}
    kind, blockers, _summary, validation = module.official_evidence_blockers("weird", unknown)
    assert kind is None
    assert blockers == ["weird:official_evidence_unrecognized"]
    assert validation["status"] == "unrecognized"
    assert validation["kind"] is None
    assert validation["checks"] == []
    assert module.official_evidence_is_valid(unknown) is False

    # An unknown type must never be mistaken for a recognized one by accident.
    assert module.detect_official_evidence_kind(unknown) is None
    assert module.looks_like_official_evidence(unknown) is False

    # Non-JSON unknown artifacts remain byte-hashable: the generic path only
    # hashes bytes and never attempts semantic parsing.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "notes.txt"
        path.write_text("free-form notes\n", encoding="utf-8")
        assert module.sha256_file(path) == module.sha256_bytes(path.read_bytes())
        try:
            module.load_json(path)
        except Exception:
            pass
        else:
            raise AssertionError("non-JSON artifact unexpectedly parsed as JSON")


def test_swords_mismatched_provenance() -> None:
    # Digest recorded for the prompt source disagrees with the archived one.
    data = swords_fixture()
    data["expectedBenchmarkSha256"] = "d" * 64
    must_block(module, "sw", data, "swords_expected_benchmark_hash_mismatch")

    # A short/mutable revision cannot stand in for a pinned commit.
    data = swords_fixture()
    data["swordsRepositoryRevision"] = "main"
    must_block(module, "sw", data, "swords_revision_not_full_sha")

    data = swords_fixture()
    data["swordsWorktreeDirty"] = True
    must_block(module, "sw", data, "swords_checkout_not_clean")

    data = swords_fixture()
    data["officialModuleSha256"] = {"swords/cli.py": "not-a-hash"}
    must_block(module, "sw", data, "swords_missing_official_module_hashes")


def test_swords_malformed_metrics() -> None:
    data = swords_fixture()
    data["metrics"]["strict_c_p@1"] = None
    must_block(module, "sw", data, "swords_missing_core_metric:strict_c_p@1")

    # A rate outside [0, 1] is malformed, not merely unusual.
    data = swords_fixture()
    data["metrics"]["strict_a_f@10"] = 1.4
    must_block(module, "sw", data, "swords_missing_core_metric:strict_a_f@10")

    for bogus in ("NaN", "high", True, [], float("nan"), float("inf"), -0.1):
        data = swords_fixture()
        data["metrics"]["lenient_c_f@10"] = bogus
        must_block(module, "sw", data, "swords_missing_core_metric:lenient_c_f@10")


def test_jfleg_mismatched_provenance() -> None:
    data = jfleg_fixture()
    data["jflegWorktreeDirty"] = True
    must_block(module, "jf", data, "jfleg_checkout_not_clean")

    data = jfleg_fixture()
    data["returnCode"] = 1
    must_block(module, "jf", data, "jfleg_returncode_not_zero")

    # Duplicate reference digests mean fewer than four distinct references.
    data = jfleg_fixture()
    data["references"][3]["sha256"] = data["references"][0]["sha256"]
    must_block(module, "jf", data, "jfleg_reference_hashes_not_unique")

    data = jfleg_fixture()
    data["references"] = data["references"][:3]
    must_block(module, "jf", data, "jfleg_requires_four_references")

    data = jfleg_fixture()
    data["hypothesisSha256"] = "short"
    must_block(module, "jf", data, "jfleg_missing_hypothesis_sha256")


def test_jfleg_non_official_protocol() -> None:
    data = jfleg_fixture()
    data["protocol"]["iterations"] = 100
    must_block(module, "jf", data, "jfleg_nonofficial_iteration_count")

    data = jfleg_fixture()
    data["protocol"]["metric"] = "Pari fluent-metric"
    must_block(module, "jf", data, "jfleg_metric_not_official_gleu")

    # Malformed protocol counts must become blockers, never a traceback.
    for bogus in (None, "many", [], True, 500.5):
        data = jfleg_fixture()
        data["protocol"]["iterations"] = bogus
        must_block(module, "jf", data, "jfleg_nonofficial_iteration_count")

    data = jfleg_fixture()
    data["stdout"] = "   \n"
    must_block(module, "jf", data, "jfleg_empty_evaluator_stdout")


def test_semanticqa_mismatched_provenance() -> None:
    data = semanticqa_fixture()
    data["checkoutDirty"] = True
    must_block(module, "sq", data, "semanticqa_checkout_not_clean")

    # Promotion-shaped metadata that contradicts its own recorded provenance.
    data = semanticqa_fixture()
    data["promotionReady"] = False
    must_block(module, "sq", data, "semanticqa_not_promotion_ready")

    data = semanticqa_fixture()
    data["conversion"]["manifestVersion"] = 1
    must_block(module, "sq", data, "semanticqa_conversion_manifest_too_old")

    # The postprocessing policy is what makes this lane official at all.
    data = semanticqa_fixture()
    data["conversion"]["predictionPolicy"] = "just take the first line"
    must_block(module, "sq", data, "semanticqa_missing_official_postprocess_provenance")

    data = semanticqa_fixture()
    data["officialEvaluator"]["sha256"] = None
    must_block(module, "sq", data, "semanticqa_missing_evaluator_sha256")


def test_semanticqa_malformed_metrics() -> None:
    # None and unparsable strings must not raise inside the validator.
    for bogus in (None, "305", "many", [], True, 305.5):
        data = semanticqa_fixture()
        data["metrics"]["cases"] = bogus
        must_block(module, "sq", data, "semanticqa_case_count_not_305")

    data = semanticqa_fixture()
    data["metrics"]["cases"] = 300
    must_block(module, "sq", data, "semanticqa_case_count_not_305")

    for bogus in (None, "NaN", "high", True, [], 1.5, -0.2, float("nan")):
        data = semanticqa_fixture()
        data["metrics"]["accuracy"] = bogus
        must_block(module, "sq", data, "semanticqa_missing_accuracy")

    data = semanticqa_fixture()
    data["metrics"]["correct"] = 400
    must_block(module, "sq", data, "semanticqa_correct_exceeds_cases")

    # Accuracy must agree with correct/cases; a ratio that is in range but
    # inconsistent with its own counts is still a malformed artifact.
    data = semanticqa_fixture()
    data["metrics"]["correct"] = 100
    data["metrics"]["accuracy"] = 1.0
    must_block(module, "sq", data, "semanticqa_accuracy_inconsistent_with_counts")


def test_promotion_readiness_fails_on_recognized_invalid_artifact() -> None:
    """Recognized-but-invalid evidence must block, and unknown must too."""
    for kind, fixture in FIXTURES.items():
        broken = fixture()
        broken["__break__"] = True
        if kind == "swords":
            broken["swordsWorktreeDirty"] = True
        elif kind == "jfleg":
            broken["protocol"]["iterations"] = 1
        else:
            broken["metrics"]["cases"] = 12
        assert not module.official_evidence_is_valid(broken), f"{kind} invalid artifact accepted"

    assert not module.official_evidence_is_valid({"benchmark": "unknown-benchmark"})


def _run_jsonl(here: Path, tmp: Path, name: str, rows: list[dict]) -> Path:
    path = tmp / name
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_cli_end_to_end_emits_metadata_and_fails_promotion() -> None:
    """Drive the real CLI: versioned metadata is emitted, and a recognized
    invalid artifact makes --require-promotion-ready exit non-zero."""
    import subprocess
    import sys
    import tempfile as _tempfile

    builder = sys.executable
    with _tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        task_file = _run_jsonl(HERE, tmp, "tasks.jsonl", [{"id": "t1"}, {"id": "t2"}])
        outputs = [{"id": "t1", "output": "a", "latencySeconds": 0.1}, {"id": "t2", "output": "b", "latencySeconds": 0.2}]
        run = {
            "schemaVersion": 1,
            "runId": "fixture-run",
            "model": {
                "name": "m",
                "repoOrName": "org/m",
                "revision": "d" * 40,
                "quantization": "q8_0",
                "checkpointType": "base",
                "runtimeVersion": "0.1.0",
                "runtime": "fixture-runtime",
                "tokenizerName": "t",
                "artifactSha256": SHA,
            },
            "decoding": {
                "temperature": 0.0,
                "topP": 1.0,
                "topK": 0,
                "maxNewTokens": 220,
                "forcedChoiceMaxNewTokens": 8,
                "seed": 0,
            },
            "promptModeRequested": "plain",
            "promptAdaptationModesObserved": ["plain"],
            "taskFile": str(task_file),
            "taskFileSha256": module.sha256_file(task_file),
            "taskCount": len(outputs),
            "outputs": outputs,
            "reproducibility": {
                "benchmarkRevision": module.git_value(["rev-parse", "HEAD"]) or "e" * 40,
                "rawOutputSha256": module.canonical_outputs_sha256(outputs),
                "resultSchemaVersion": 1,
                "resultSchemaSha256": __import__("hashlib").sha256(module.HERE.joinpath("english-core-result-schema.json").read_bytes()).hexdigest(),
            },
        }
        run_path = tmp / "run.json"
        run_path.write_text(json.dumps(run), encoding="utf-8")
        score = {
            "schemaVersion": 1,
            "artifactType": "pari.english-core.shadow-score",
            "inputResultSchema": {
                "validatorContractVersion": 1,
                "validationMode": "promotion",
                "resultSchemaVersion": 1,
                "schemaSha256": run["reproducibility"]["resultSchemaSha256"],
                "compatibilityMode": None,
            },
            "taskFileSha256": run["taskFileSha256"],
            "complete": True,
            "benchmarkInputs": {
                "configSha256": SHA,
                "shadowSeedSha256": SHA,
                "generativeMetricContractSha256": SHA,
            },
            "detail": [],
        }
        score_path = tmp / "score.json"
        score_path.write_text(json.dumps(score), encoding="utf-8")

        good = swords_fixture()
        good_path = tmp / "swords.json"
        good_path.write_text(json.dumps(good), encoding="utf-8")
        bad = swords_fixture()
        bad["metrics"]["strict_a_f@10"] = 42.0
        bad_path = tmp / "swords-bad.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        unknown_path = tmp / "unknown.json"
        unknown_path.write_text(json.dumps({"benchmark": "unrelated-benchmark"}), encoding="utf-8")

        def invoke(evidence: list[tuple[str, Path]], out_name: str) -> tuple[int, dict]:
            out = tmp / out_name
            cmd = [
                builder,
                str(BUILDER),
                "--run", str(run_path),
                "--score", str(score_path),
                "--output", str(out),
                "--require-promotion-ready",
            ]
            for label, path in evidence:
                cmd += ["--official-evidence", f"{label}={path}"]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            return proc.returncode, json.loads(out.read_text(encoding="utf-8"))

        # Environmental blockers (dirty checkout, etc.) depend on the caller's
        # working state, so compare against the same run without evidence.
        baseline_code, baseline = invoke([], "baseline.json")

        code, manifest = invoke([("sw", good_path)], "ok.json")
        new_blockers = [
            b for b in manifest["promotionBlockers"] if b not in baseline["promotionBlockers"]
        ]
        assert not new_blockers, f"valid SWORDS evidence added blockers: {new_blockers}"
        assert code == (1 if baseline_code else 0)
        contract = manifest["semanticValidationContract"]
        assert contract["version"] == module.SEMANTIC_VALIDATION_VERSION
        assert contract["unknownArtifactPolicy"] == "byte-hash-only"
        row = manifest["officialEvidence"][0]
        assert row["semanticValidation"]["status"] == "passed"
        assert row["semanticValidation"]["kind"] == "swords"

        # Recognized but malformed metrics must fail promotion readiness.
        code, manifest = invoke([("sw", bad_path)], "bad.json")
        assert code == 1, "malformed SWORDS metric did not fail promotion"
        assert "sw:swords_missing_core_metric:strict_a_f@10" in manifest["promotionBlockers"]
        assert manifest["officialEvidence"][0]["semanticValidation"]["status"] == "failed"

        # An unknown type is byte-hashed and reported unrecognized, and blocks.
        code, manifest = invoke([("other", unknown_path)], "unknown-manifest.json")
        assert code == 1, "unrecognized official evidence did not block promotion"
        row = manifest["officialEvidence"][0]
        assert row["kind"] is None
        assert row["semanticValidation"]["status"] == "unrecognized"
        assert row["semanticValidation"]["checks"] == []
        assert row["sha256"] == module.sha256_file(unknown_path)
        assert any(a["label"] == "other" for a in manifest["artifacts"])

        # Generic --artifact stays byte-hash-only for unknown artifact types.
        cmd = [
            builder,
            str(BUILDER),
            "--run", str(run_path),
            "--score", str(score_path),
            "--output", str(tmp / "generic.json"),
            "--artifact", f"notes={unknown_path}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        manifest = json.loads((tmp / "generic.json").read_text(encoding="utf-8"))
        assert not any(b.startswith("notes:") for b in manifest["promotionBlockers"])
        artifact = next(a for a in manifest["artifacts"] if a["label"] == "notes")
        assert artifact["sha256"] == module.sha256_file(unknown_path)
        assert artifact["bytes"] == unknown_path.stat().st_size

        # ...but a recognized official artifact misrouted to --artifact blocks,
        # so official evidence cannot be smuggled in as an opaque byte blob.
        cmd = [
            builder,
            str(BUILDER),
            "--run", str(run_path),
            "--score", str(score_path),
            "--output", str(tmp / "smuggled.json"),
            "--artifact", f"sw={good_path}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        manifest = json.loads((tmp / "smuggled.json").read_text(encoding="utf-8"))
        assert "sw:official_evidence_must_use_official_evidence_flag" in manifest["promotionBlockers"]


module = load_builder()
TESTS = [
    test_valid_fixtures_pass,
    test_swords_artifact_carries_verified_converter_chain,
    test_jfleg_artifact_carries_versioned_normalization_chain,
    test_semanticqa_artifact_carries_official_postprocessor_provenance,
    test_semanticqa_environment_comes_from_the_selected_interpreter,
    test_validation_is_deterministic,
    test_validation_metadata_is_versioned,
    test_schema_file_matches_emitted_records,
    test_unknown_artifact_is_unrecognized_but_byte_hashable,
    test_swords_mismatched_provenance,
    test_swords_malformed_metrics,
    test_jfleg_mismatched_provenance,
    test_jfleg_non_official_protocol,
    test_semanticqa_mismatched_provenance,
    test_semanticqa_malformed_metrics,
    test_promotion_readiness_fails_on_recognized_invalid_artifact,
    test_cli_end_to_end_emits_metadata_and_fails_promotion,
]


def main() -> None:
    for test in TESTS:
        test()
        print(f"  ok  {test.__name__}")
    print("Official evidence semantic validation tests passed.")


if __name__ == "__main__":
    main()
