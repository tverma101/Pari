#!/usr/bin/env python3
"""#66 CPU tests: converter code/config identity for official anchors.

The official SWORDS/JFLEG/SemanticQA evaluators are pinned, but the Pari-owned
conversion layer that builds their input is score-affecting. These tests prove the
chain is fail-closed: a one-byte converter edit, an unregistered protocol, a
config change without a new identity, a tampered manifest, or an unavailable
benchmark Git identity must all be rejected before a promotion-ready official
score can be produced. They also pin the SemanticQA postprocessor edge taxonomy
against the verified official semantics and prove the SemanticQA wrapper probes
the *selected* interpreter rather than the wrapper process.

No network, no GPU, no official checkout required. Run directly or under pytest:
    python3 test_official_converter_provenance.py
"""
from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVENANCE = HERE / "english_core_converter_provenance.py"
SWORDS_CONVERTER = HERE / "convert-swords-english-core-output.py"
JFLEG_CONVERTER = HERE / "convert-jfleg-english-core-output.py"
SEMANTICQA_CONVERTER = HERE / "convert-semanticqa-lcc-official-output.py"
SEMANTICQA_WRAPPER = HERE / "run-semanticqa-lcc-official-eval.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


provenance = load("pari_converter_provenance", PROVENANCE)
swords = load("pari_swords_converter", SWORDS_CONVERTER)
jfleg = load("pari_jfleg_converter", JFLEG_CONVERTER)
semanticqa = load("pari_semanticqa_converter", SEMANTICQA_CONVERTER)
semanticqa_runner = load("pari_semanticqa_runner", SEMANTICQA_WRAPPER)

GIT_SHA = "a" * 40


def swords_manifest() -> dict:
    return {
        "version": 5,
        "promotionProvenanceReady": True,
        "converterProvenance": provenance.build_converter_provenance(
            benchmark="swords",
            protocol_id=provenance.SWORDS_PROTOCOL_ID,
            protocol_version=1,
            converter_path=SWORDS_CONVERTER,
            conversion_config={"maxCandidates": 40, "substitutesLemmatized": False},
            repo_root=HERE,
        ),
    }


def jfleg_manifest() -> dict:
    return {
        "version": 4,
        "promotionProvenanceReady": True,
        "converterProvenance": provenance.build_converter_provenance(
            benchmark="jfleg",
            protocol_id=provenance.JFLEG_PROTOCOL_ID,
            protocol_version=1,
            converter_path=JFLEG_CONVERTER,
            conversion_config={"normalizerProtocol": f"{provenance.JFLEG_PROTOCOL_ID}@1"},
            repo_root=HERE,
        ),
    }


def semanticqa_manifest() -> dict:
    return {
        "version": 3,
        "promotionProvenanceReady": True,
        "postprocessor": {
            "kind": "official-pinned-import",
            "commit": GIT_SHA,
            "clean": True,
            "moduleSha256": provenance.sha256_bytes(b"official"),
        },
        "converterProvenance": provenance.build_converter_provenance(
            benchmark="semanticqa_lcc",
            protocol_id=provenance.SEMANTICQA_PROTOCOL_ID,
            protocol_version=1,
            converter_path=SEMANTICQA_CONVERTER,
            conversion_config={
                "postprocessorSource": "official-pinned-import",
                "postprocessorCommit": GIT_SHA,
                "postprocessorModuleSha256": provenance.sha256_bytes(b"official"),
            },
            repo_root=HERE,
        ),
    }


def verify(manifest: dict, benchmark: str, converter_path: Path) -> list[str]:
    return provenance.verify_converter_provenance(
        manifest, benchmark=benchmark, converter_path=converter_path
    )


# --------------------------------------------------------------------------
# Exact frozen chain
# --------------------------------------------------------------------------


def test_frozen_chain_verifies_for_all_three_benchmarks() -> None:
    assert verify(swords_manifest(), "swords", SWORDS_CONVERTER) == []
    assert verify(jfleg_manifest(), "jfleg", JFLEG_CONVERTER) == []
    assert verify(semanticqa_manifest(), "semanticqa_lcc", SEMANTICQA_CONVERTER) == []


def test_converter_source_hash_is_content_addressed() -> None:
    manifest = swords_manifest()
    recorded = manifest["converterProvenance"]["converterSource"]["sha256"]
    assert recorded == provenance.sha256_file(SWORDS_CONVERTER)
    size = manifest["converterProvenance"]["converterSource"]["bytes"]
    assert size == SWORDS_CONVERTER.stat().st_size


# --------------------------------------------------------------------------
# Issue #66 required failure cases
# --------------------------------------------------------------------------


def test_one_byte_converter_edit_is_rejected() -> None:
    manifest = swords_manifest()
    assert manifest["promotionProvenanceReady"] is True
    with tempfile.TemporaryDirectory() as tmp:
        tampered = Path(tmp) / SWORDS_CONVERTER.name
        original = SWORDS_CONVERTER.read_bytes()
        tampered.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))
        errors = verify(manifest, "swords", tampered)
    assert "converter_source_sha256_does_not_match_converter_file" in errors, errors


def test_config_drift_changes_identity_and_is_detected() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["conversionConfig"]["maxCandidates"] = 20
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert "conversion_identity_does_not_match_recorded_chain" in errors, errors


def test_lemmatized_flag_is_part_of_the_identity() -> None:
    a = swords_manifest()
    b = swords_manifest()
    b["converterProvenance"]["conversionConfig"]["substitutesLemmatized"] = True
    b["converterProvenance"]["identity"] = provenance.conversion_identity(
        benchmark="swords",
        protocol_id=provenance.SWORDS_PROTOCOL_ID,
        protocol_version=1,
        contract_sha256=b["converterProvenance"]["protocol"]["contractSha256"],
        converter_source_sha256=b["converterProvenance"]["converterSource"]["sha256"],
        conversion_config=b["converterProvenance"]["conversionConfig"],
    )
    other = a["converterProvenance"]["identity"]
    assert other != b["converterProvenance"]["identity"]
    assert verify(b, "swords", SWORDS_CONVERTER) == []


def test_unregistered_protocol_is_rejected() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["protocol"]["id"] = "pari-swords-candidate-parser-v99"
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert any(e.startswith("converter_protocol_not_registered") for e in errors), errors


def test_unregistered_protocol_version_is_rejected() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["protocol"]["version"] = 2
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert any(e.startswith("converter_protocol_not_registered") for e in errors), errors


def test_contract_hash_drift_is_rejected() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["protocol"]["contractSha256"] = "f" * 64
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert "converter_contract_sha256_does_not_match_registered_protocol" in errors, errors
    assert "conversion_identity_does_not_match_recorded_chain" in errors, errors


def test_missing_converter_provenance_is_rejected() -> None:
    assert verify({"promotionProvenanceReady": True}, "swords", SWORDS_CONVERTER) == [
        "converter_provenance_missing"
    ]
    manifest = swords_manifest()
    del manifest["converterProvenance"]["protocol"]
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert errors == ["converter_protocol_identity_missing"], errors


def test_tampered_manifest_fails_identity_check() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["identity"] = "0" * 64
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert "conversion_identity_does_not_match_recorded_chain" in errors, errors


def test_missing_benchmark_git_identity_fails_closed() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["benchmarkGit"] = {
        "available": False,
        "reason": "benchmark_git_identity_unavailable",
        "repositoryRoot": None,
        "commit": None,
        "tree": None,
        "branch": None,
        "dirty": None,
    }
    manifest["converterProvenance"]["identity"] = provenance.conversion_identity(
        benchmark="swords",
        protocol_id=provenance.SWORDS_PROTOCOL_ID,
        protocol_version=1,
        contract_sha256=manifest["converterProvenance"]["protocol"]["contractSha256"],
        converter_source_sha256=manifest["converterProvenance"]["converterSource"]["sha256"],
        conversion_config=manifest["converterProvenance"]["conversionConfig"],
    )
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert "benchmark_git_identity_unavailable" in errors, errors


def test_malformed_benchmark_git_commit_is_rejected() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["benchmarkGit"]["commit"] = "HEAD"
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert "benchmark_git_commit_not_full_sha" in errors, errors


def test_unregistered_config_keys_are_rejected() -> None:
    manifest = swords_manifest()
    manifest["converterProvenance"]["conversionConfig"]["maxTokens"] = 8
    errors = verify(manifest, "swords", SWORDS_CONVERTER)
    assert any(e.startswith("conversion_config_has_unregistered_keys") for e in errors), errors


# --------------------------------------------------------------------------
# Issue test 3: a parser change cannot silently move one finalist's score
# --------------------------------------------------------------------------


def test_swords_parser_change_yields_a_separate_identity() -> None:
    before = swords_manifest()["converterProvenance"]["identity"]
    with tempfile.TemporaryDirectory() as tmp:
        edited = Path(tmp) / SWORDS_CONVERTER.name
        edited.write_bytes(SWORDS_CONVERTER.read_bytes() + b"\n# parser improvement\n")
        after = provenance.build_converter_provenance(
            benchmark="swords",
            protocol_id=provenance.SWORDS_PROTOCOL_ID,
            protocol_version=1,
            converter_path=edited,
            conversion_config={"maxCandidates": 40, "substitutesLemmatized": False},
            repo_root=HERE,
        )["identity"]
    assert before != after
    replay = swords_manifest()
    replay["converterProvenance"] = {"identity": after}
    mixed = provenance.compare_conversion_identities([swords_manifest(), replay])
    assert len(mixed) == 1 and mixed[0].startswith("mixed_conversion_identity:")


def test_identical_chains_pool_cleanly() -> None:
    assert provenance.compare_conversion_identities([swords_manifest(), swords_manifest()]) == []


def test_replay_under_new_protocol_is_a_separate_evidence_identity() -> None:
    old = swords_manifest()
    replay = copy.deepcopy(old)
    replay["converterProvenance"]["protocol"]["id"] = "pari-swords-candidate-parser-v2"
    replay["converterProvenance"]["identity"] = "1" * 64
    mixed = provenance.compare_conversion_identities([old, replay])
    assert len(mixed) == 1, mixed


def test_missing_identity_is_pooled_as_malformed() -> None:
    # A batch with any unusable identity is unpoolable, fail-closed.
    malformed_only = provenance.compare_conversion_identities(
        [{"converterProvenance": {}}, {"x": 1}]
    )
    assert len(malformed_only) == 1, malformed_only
    assert malformed_only[0].startswith("conversion_identity_missing_for_artifacts:")
    mixed = provenance.compare_conversion_identities([{"converterProvenance": {}}, swords_manifest()])
    assert len(mixed) == 1 and "conversion_identity_missing_for_artifacts:" in mixed[0]


# --------------------------------------------------------------------------
# SemanticQA postprocessor edge taxonomy.
#
# Verified against the pinned official source: jacklanda/SemanticQA @
# 56c82a587f4a6cef609255cd10af372d8c76600a, semantic_qa/data_utils.py
# sha256 52ad7f1642484972cd44a96546e3aa339179db4c5a15eceec1ed66b71c8ce09a,
# lines 1163-1173: s = " ".join(s.split()); for task ==
# "collocation-categorization": if "is: " in s: s = s.split("is: ")[-1].strip()
# / elif "Output:" in s: s = s.split("Output:")[-1].strip(); return s.
# --------------------------------------------------------------------------

SEMANTICQA_EDGE_CASES = [
    ("Output: x is: y", "y", "is: is checked first and short-circuits Output:"),
    ("is: a is: b", "b", "split(...)[-1] takes the last occurrence"),
    ("Output: 1 Output: 2", "2", "same for the Output: marker"),
    ("IS: X", "IS: X", "marker matching is case-sensitive"),
    ("output: X", "output: X", "lowercase output: is not a marker"),
    ("answer\u00a0is:\u3000y\u2028z", "y z", "Unicode whitespace normalizes before matching"),
    ("Output:\u00a0X", "X", "Output: needs no trailing space"),
    ("Output:x", "x", "Output: needs no trailing space"),
    ("Output: x", "x", "marker split then strip"),
    ("", "", "empty output normalizes to empty"),
    ("   ", "", "whitespace-only normalizes to empty"),
    ("xis: y", "y", "no word-boundary check on the is: marker"),
    ("answer is: ", "answer is:", "normalization removes the trailing space"),
    ("is: ", "is:", "trailing space is normalized away before matching"),
    ("is:\n  Magn", "Magn", "a marker broken across a newline normalizes and matches"),
    ("Magn", "Magn", "no marker, normalized string returned unchanged"),
    ('"Magn"', '"Magn"', "no quote stripping in the official LCC branch"),
    ("- Magn", "- Magn", "no bullet stripping in the official LCC branch"),
    ("magn", "magn", "no case folding"),
]


def test_semanticqa_postprocess_matches_official_edge_taxonomy() -> None:
    for text, expected, why in SEMANTICQA_EDGE_CASES:
        got = semanticqa.semanticqa_lcc_postprocess(text)
        assert got == expected, f"{text!r} -> {got!r} != {expected!r} ({why})"


def test_semanticqa_postprocess_marker_counters_match_branch_semantics() -> None:
    for text, expected_is, expected_output in [
        ("Output: x is: y", True, False),
        ("is: a is: b", True, False),
        ("Output: 1 Output: 2", False, True),
        ("IS: X", False, False),
        ("Output:\u00a0X", False, True),
    ]:
        normalized = " ".join(text.split())
        has_is = "is: " in normalized
        has_output = (not has_is) and "Output:" in normalized
        assert (has_is, has_output) == (expected_is, expected_output), text


def test_semanticqa_wrapper_requires_official_pinned_import() -> None:
    source = SEMANTICQA_WRAPPER.read_text(encoding="utf-8")
    assert "semanticqa_postprocessor_not_official_pinned_import" in source
    assert "verify_converter_provenance(" in source
    manifest = semanticqa_manifest()
    manifest["postprocessor"]["kind"] = "local-mirror"
    assert verify(manifest, "semanticqa_lcc", SEMANTICQA_CONVERTER) == []


def test_semanticqa_converter_rejects_dirty_or_wrong_commit_checkout() -> None:
    source = SEMANTICQA_CONVERTER.read_text(encoding="utf-8")
    assert "requires commit {PINNED_COMMIT}" in source
    assert "requires a clean checkout" in source
    assert "official-pinned-import" in source


# --------------------------------------------------------------------------
# Issue test 5: the wrapper probes the exact --python interpreter
# --------------------------------------------------------------------------


def test_semanticqa_environment_probe_reports_the_selected_interpreter() -> None:
    selected = sys.executable
    env = semanticqa_runner.evaluator_environment(
        semanticqa_runner.resolve_python(selected), HERE
    )
    assert "error" not in env, env
    assert env["resolvedExecutable"]
    assert env["pythonVersion"]
    assert env["pythonImplementation"]
    assert isinstance(env["packages"], dict)
    for package in ("numpy", "scikit-learn", "evaluate"):
        assert package in env["packages"], f"{package} not probed from the selected interpreter"


def test_semanticqa_environment_probe_rejects_a_non_interpreter() -> None:
    env = semanticqa_runner.evaluator_environment("/definitely/not/python3", HERE)
    assert "error" in env, env


def test_resolve_python_reports_a_real_interpreter_path() -> None:
    resolved = semanticqa_runner.resolve_python(sys.executable)
    assert resolved and Path(resolved).name.startswith("python")


# --------------------------------------------------------------------------
# Converter audit trails required by the issue
# --------------------------------------------------------------------------


def test_swords_conversion_diagnostics_are_complete() -> None:
    text = "\n".join([
        "Here are some substitutes:",
        "- alpha",
        '"alpha"',
        "* Beta",
        "1. gamma",
        "a) delta",
        "",
        "Alternatives:",
        "epsilon",
        "EPSILON",
    ])
    candidates, diag = swords.parse_candidates_with_diagnostics(text)
    assert candidates == ["alpha", "Beta", "gamma", "delta", "epsilon"]
    assert diag["rawLineCount"] == 10
    assert diag["rawCandidateLines"][0] == "Here are some substitutes:"
    assert diag["emptyLinesDropped"] == 1
    assert diag["filteredMetaCount"] == 2
    assert set(diag["filteredMetaReasons"]) == {"here are", "alternatives:"}
    assert diag["normalizedDeduplicatedCount"] == 2
    assert diag["quoteOrBulletStripChangedText"] >= 1
    assert diag["listPrefixStripped"] >= 4
    assert diag["retainedCandidates"] == candidates


def test_jfleg_normalization_is_exactly_one_line_and_reports_changes() -> None:
    assert jfleg.normalize_one_line("  a\n b\t c  ") == "a b c"
    assert jfleg.normalize_one_line("a\u00a0b\u3000c") == "a b c"
    assert jfleg.normalize_one_line("already one line") == "already one line"
    assert jfleg.normalize_one_line("") == ""


# --------------------------------------------------------------------------
# Registry invariants
# --------------------------------------------------------------------------


def test_every_registered_protocol_declares_config_and_coverage_keys() -> None:
    for benchmark, protocols in provenance.CONVERTER_PROTOCOLS.items():
        for protocol_id, versions in protocols.items():
            for version, entry in versions.items():
                assert entry["configKeys"] is not None
                assert entry["coverageKeys"]
                assert entry["contract"]
                digest = provenance.protocol_contract_sha256(benchmark, protocol_id, version)
                assert digest == provenance.protocol_contract_sha256(
                    benchmark, protocol_id, version
                )


def test_registered_contract_hashes_are_stable_across_processes() -> None:
    script = (
        "import importlib.util,sys;"
        f"spec=importlib.util.spec_from_file_location('m', {str(PROVENANCE)!r});"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "print(m.protocol_contract_sha256('swords', m.SWORDS_PROTOCOL_ID, 1))"
    )
    out = subprocess.check_output([sys.executable, "-c", script], text=True).strip()
    expected = provenance.protocol_contract_sha256("swords", provenance.SWORDS_PROTOCOL_ID, 1)
    assert out == expected


def test_benchmark_git_identity_is_honest_when_git_is_absent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        identity = provenance.benchmark_git_identity(Path(tmp))
    assert identity["available"] is False
    assert identity["commit"] is None
    assert identity["reason"] == "benchmark_git_identity_unavailable"


def test_benchmark_git_identity_records_commit_and_tree_when_available() -> None:
    identity = provenance.benchmark_git_identity(HERE)
    assert provenance.is_git_sha(identity["commit"])
    if identity["available"]:
        assert provenance.is_git_sha(identity["tree"])


TESTS = [
    test_frozen_chain_verifies_for_all_three_benchmarks,
    test_converter_source_hash_is_content_addressed,
    test_one_byte_converter_edit_is_rejected,
    test_config_drift_changes_identity_and_is_detected,
    test_lemmatized_flag_is_part_of_the_identity,
    test_unregistered_protocol_is_rejected,
    test_unregistered_protocol_version_is_rejected,
    test_contract_hash_drift_is_rejected,
    test_missing_converter_provenance_is_rejected,
    test_tampered_manifest_fails_identity_check,
    test_missing_benchmark_git_identity_fails_closed,
    test_malformed_benchmark_git_commit_is_rejected,
    test_unregistered_config_keys_are_rejected,
    test_swords_parser_change_yields_a_separate_identity,
    test_identical_chains_pool_cleanly,
    test_replay_under_new_protocol_is_a_separate_evidence_identity,
    test_missing_identity_is_pooled_as_malformed,
    test_semanticqa_postprocess_matches_official_edge_taxonomy,
    test_semanticqa_postprocess_marker_counters_match_branch_semantics,
    test_semanticqa_wrapper_requires_official_pinned_import,
    test_semanticqa_converter_rejects_dirty_or_wrong_commit_checkout,
    test_semanticqa_environment_probe_reports_the_selected_interpreter,
    test_semanticqa_environment_probe_rejects_a_non_interpreter,
    test_resolve_python_reports_a_real_interpreter_path,
    test_swords_conversion_diagnostics_are_complete,
    test_jfleg_normalization_is_exactly_one_line_and_reports_changes,
    test_every_registered_protocol_declares_config_and_coverage_keys,
    test_registered_contract_hashes_are_stable_across_processes,
    test_benchmark_git_identity_is_honest_when_git_is_absent,
    test_benchmark_git_identity_records_commit_and_tree_when_available,
]


def main() -> None:
    for test in TESTS:
        test()
        print(f"  ok  {test.__name__}")
    print("Official converter provenance tests passed.")


if __name__ == "__main__":
    main()
