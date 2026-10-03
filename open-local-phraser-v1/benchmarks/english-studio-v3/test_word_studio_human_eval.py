#!/usr/bin/env python3
"""Synthetic CPU-only fixtures for the blinded human-eval pipeline (issue #69).

Covers the twelve regression cases named in the issue plus the provenance
refusals:

1.  same inputs + seed produce byte-identical packets and private mapping;
2.  changing a finalist output hash changes the frozen packet and its digest;
3.  model/runtime/latency metadata never appears in a reviewer-visible packet;
4.  A/B sides are genuinely balanced and randomized per rater;
5.  private review-key text never leaks unless explicitly preregistered as
    reviewer rubric material;
6.  unknown and duplicate rating rows fail validation;
7.  intentional-compression items use their own criterion contract;
8.  strength variants preserve source grouping and ordered strength identity;
9.  ties and both-unacceptable remain first-class analysis outcomes;
10. analysis refuses to pair ratings across different rubric/preregistration
    bindings;
11. a post-hoc exclusion with no preregistered rule is surfaced as exploratory;
12. the blinded mapping is revealed only in analysis, with its digest retained.

No model, no GPU, no network, no real raters, no answer keys. All fixtures are
generated locally and deterministically.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import word_studio_human_eval as HE

SEED = "frozen-seed-69"
SYSTEM_A = "alpha-model"
SYSTEM_B = "bravo-model"
#: Fixture systems still write visibly different English. The markers stand in
#: for that difference without embedding the finalist id, so the blinding
#: assertions keep testing blinding rather than the fixture's own naming.
MARKER_A = "crimson rewrite"
MARKER_B = "azure rewrite"


def _options(options: list[str]) -> str:
    return json.dumps({"options": options}, ensure_ascii=False)


def _candidates(prefix: str) -> list[str]:
    # Ten materially different, non-duplicate alternatives that clear the
    # parser's near-duplicate threshold and never equal the source.
    return [
        f"{prefix} alpha option",
        f"{prefix} beta option",
        f"{prefix} gamma option",
        f"{prefix} delta option",
        f"{prefix} epsilon option",
        f"{prefix} zeta option",
        f"{prefix} eta option",
        f"{prefix} theta option",
        f"{prefix} iota option",
        f"{prefix} kappa option",
    ]


def _write_tasks(directory: Path, *, marker: str = "", prefix: str = "t") -> Path:
    rows = [
        {
            "id": f"{prefix}-alt",
            "suite": "synthetic_human_eval",
            "marker": marker,
            "route": "alternatives",
            "operation": "rewrite the selected word",
            "sourceText": "The council approved the revised budget on Tuesday.",
            "selectedText": "approved",
            "requestedCount": 10,
        },
        {
            "id": f"{prefix}-comp",
            "suite": "synthetic_human_eval",
            "operation": "gist3",
            "semanticMode": "intentional_compression",
            "sourceText": "The council approved the revised budget on Tuesday.",
            "selectedText": "The council approved the revised budget on Tuesday.",
            "requestedCount": 10,
        },
        {
            "id": f"{prefix}-prot",
            "suite": "synthetic_human_eval",
            "sourceCategory": "protected_context",
            "operation": "protected",
            "sourceText": "Ada shipped Report-9 to the lab on 2024-05-01.",
            "selectedText": "shipped",
            "requestedCount": 10,
        },
        {
            "id": f"{prefix}-prot-comp",
            "suite": "synthetic_human_eval",
            "sourceCategory": "protected_context",
            "semanticMode": "intentional_compression",
            "operation": "gist3",
            "sourceText": "Ada shipped Report-9 to the lab on 2024-05-01.",
            "selectedText": "Ada shipped Report-9 to the lab on 2024-05-01.",
            "requestedCount": 10,
        },
    ]
    for strength in (15, 40, 60, 90):
        rows.append(
            {
                "id": f"{prefix}-str-s{strength}",
                "suite": "synthetic_human_eval",
                "sourceId": "src-one",
                "source": "synthetic",
                "task": "paragraph_rewrite",
                "strength": strength,
                "sourceText": "The council approved the revised budget on Tuesday.",
                "selectedText": None,
                "requestedCount": 10,
            }
        )
    path = directory / "tasks.jsonl"
    HE.atomic_write(
        path,
        ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8"),
    )
    return path


def _write_result(directory: Path, tasks_path: Path, system_id: str, revision: str, prefix: str) -> Path:
    task_sha = HE.sha256_file(tasks_path)
    rows = [json.loads(line) for line in tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    outputs = []
    for row in rows:
        # Every system returns ten distinct usable options for every task. The two
        # systems differ only in wording so the blinding scan can never be fooled
        # by content, only by metadata.
        outputs.append({"id": row["id"], "output": _options(_candidates(prefix))})
    payload = {
        "version": 1,
        "model": f"{system_id}-hf",
        "modelRevision": revision,
        "runtime": "vllm",
        "endpoint": "http://127.0.0.1:8000",
        # Deliberately the file name, not the absolute path: the frozen digest
        # binds exact artifact bytes, so a machine-specific path would make an
        # otherwise identical packet non-reproducible across directories.
        "taskFile": tasks_path.name,
        "taskFileSha256": task_sha,
        "taskCount": len(rows),
        "hardware": {"gpu": "NVIDIA T4"},
        "decoding": {"temperature": 0.0, "topP": 1.0, "seed": 7},
        "outputs": outputs,
    }
    path = directory / f"{system_id}.result.json"
    HE.atomic_write(path, HE.document_bytes(payload))
    return path


def _build(directory: Path, *, depth_policy=HE.DEFAULT_DEPTHS, raters=HE.DEFAULT_RATERS, checklist=None, expectation_mode="not_used"):
    tasks = _write_tasks(directory)
    results = [
        _write_result(directory, tasks, SYSTEM_A, "rev-aaaa1111", MARKER_A),
        _write_result(directory, tasks, SYSTEM_B, "rev-bbbb2222", MARKER_B),
    ]
    inputs = HE.load_inputs(task_files=[tasks], result_files=results)
    comparisons = HE.build_comparisons(inputs)
    preregistration = HE.build_preregistration(
        inputs,
        comparisons,
        seed=SEED,
        depths=depth_policy,
        rater_ids=raters,
        author_expectation_mode=expectation_mode,
    )
    built = HE.build_packets(
        inputs,
        comparisons,
        preregistration,
        depth=max(depth_policy),
        reviewer_checklist=checklist,
    )
    return inputs, comparisons, preregistration, built


def _packet_for(built, rater_id):
    return built["packets"][rater_id]


def _all_rating_rows(packet):
    pair_rows = []
    for item in packet["items"]:
        if item["kind"] != "pair_comparison":
            continue
        for criterion in item["criteria"]:
            pair_rows.append((item["pairId"], criterion["criterion"]))
    candidate_rows = []
    for item in packet["items"]:
        if item["kind"] != "pair_comparison":
            continue
        for side in ("A", "B"):
            for candidate in item["sides"][side]["candidates"]:
                candidate_rows.append((item["pairId"], side, candidate["candidateId"]))
    strength_rows = []
    for item in packet["items"]:
        if item["kind"] != "strength_trajectory":
            continue
        for variant in item["variants"]:
            strength_rows.append((item["sourceGroupId"], variant["requestedStrength"]))
    return pair_rows, candidate_rows, strength_rows


def _synthetic_ratings(packet, *, label_cycle=("A", "tie", "B", "both_unacceptable")):
    """Deterministic *fixture* ratings. These are not human judgments."""
    pair_rows, candidate_rows, strength_rows = _all_rating_rows(packet)
    pair_ratings = []
    for index, (pair_id, criterion) in enumerate(pair_rows):
        label = label_cycle[index % len(label_cycle)]
        pair_ratings.append({"pairId": pair_id, "criterion": criterion, "label": label, "note": None})
    candidate_ratings = [
        {"pairId": pair_id, "side": side, "candidateId": candidate_id, "label": "usable", "note": None}
        for pair_id, side, candidate_id in candidate_rows
    ]
    strength_ratings = [
        {
            "sourceGroupId": group,
            "requestedStrength": strength,
            "edit_usefulness": "usable",
            "semantic_register_stable": "yes",
            "intensity_increased": "no",
        }
        for group, strength in strength_rows
    ]
    return {
        "schemaVersion": HE.RATING_SCHEMA_VERSION,
        "packetId": packet["packetId"],
        "packetSha256": packet["packetSha256"],
        "preregistrationSha256": packet["preregistrationSha256"],
        "rubricSha256": packet["rubricSha256"],
        "raterId": packet["raterId"],
        "pairRatings": pair_ratings,
        "candidateRatings": candidate_ratings,
        "strengthRatings": strength_ratings,
    }


# --- 1: determinism ---------------------------------------------------------


def test_same_inputs_and_seed_are_byte_identical() -> None:
    first_dir = Path(tempfile.mkdtemp())
    second_dir = Path(tempfile.mkdtemp())
    try:
        _, _, _, built_a = _build(first_dir)
        _, _, _, built_b = _build(second_dir)
        assert list(built_a["packets"]) == list(built_b["packets"])
        for rater_id in built_a["packets"]:
            assert (
                HE.document_bytes(built_a["packets"][rater_id])
                == HE.document_bytes(built_b["packets"][rater_id])
            ), rater_id
        assert (
            HE.document_bytes(built_a["privateMapping"])
            == HE.document_bytes(built_b["privateMapping"])
        )
        assert (
            built_a["privateMapping"]["mappingSha256"]
            == built_b["privateMapping"]["mappingSha256"]
        )
    finally:
        shutil.rmtree(first_dir, ignore_errors=True)
        shutil.rmtree(second_dir, ignore_errors=True)


# --- 2: changed output hash invalidates the packet --------------------------


def test_changing_finalist_output_changes_frozen_packet() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        inputs_a, comparisons_a, prereg_a, built_a = _build(directory)
        packet_a = _packet_for(built_a, HE.DEFAULT_RATERS[0])
        digest_a = packet_a["packetSha256"]

        # Mutate one raw output byte inside the finalist result artifact. The
        # preregistration result digest must move, and the packet must differ.
        result_path = inputs_a.systems[0].result_path
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["outputs"][0]["output"] = _options(_candidates("mutated"))
        HE.atomic_write(result_path, HE.document_bytes(payload))

        inputs_b = HE.load_inputs(
            task_files=[inputs_a.tasks_by_file[next(iter(inputs_a.tasks_by_file))].path],
            result_files=[inputs_a.systems[0].result_path, inputs_a.systems[1].result_path],
        )
        comparisons_b = HE.build_comparisons(inputs_b)
        prereg_b = HE.build_preregistration(
            inputs_b, comparisons_b, seed=SEED, rater_ids=HE.DEFAULT_RATERS
        )
        built_b = HE.build_packets(
            inputs_b, comparisons_b, prereg_b, depth=max(HE.DEFAULT_DEPTHS)
        )
        packet_b = _packet_for(built_b, HE.DEFAULT_RATERS[0])

        assert prereg_a["resultArtifacts"] != prereg_b["resultArtifacts"]
        assert prereg_a["preregistrationSha256"] != prereg_b["preregistrationSha256"]
        assert packet_b["packetSha256"] != digest_a
        assert inputs_b.systems[0].result_sha256 != inputs_a.systems[0].result_sha256
        assert inputs_b.systems[0].result_sha256 == HE.sha256_file(result_path)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 3: no model/runtime metadata in reviewer packet ------------------------


def test_no_model_or_runtime_metadata_in_packet() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        inputs, _, _, built = _build(directory)
        forbidden = HE.system_public_tokens(inputs)
        system_ids = [system.system_id for system in inputs.systems]
        assert sorted(system_ids) == sorted([SYSTEM_A + "-hf", SYSTEM_B + "-hf"])
        for system_id in system_ids:
            assert system_id in forbidden
            assert any(token.endswith(".result.json") for token in forbidden)
        assert "vllm" in forbidden
        for rater_id, packet in built["packets"].items():
            blob = HE.canonical_json(packet).lower()
            for token in (*system_ids, "vllm", "nvidia", "t4", "http://", "rev-aaaa1111"):
                assert token.lower() not in blob, (rater_id, token)
            assert HE.scan_for_leaks(packet, forbidden) == []
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 4: A/B sides balanced and randomized -----------------------------------


def test_ab_sides_balanced_and_randomized() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        inputs, _, _, built = _build(directory, raters=("r-alpha", "r-beta", "r-gamma"))
        # Fixture candidates are prefixed with a system marker, so the displayed
        # side can be read straight off the packet text without any mapping.
        marker = {SYSTEM_A: MARKER_A, SYSTEM_B: MARKER_B}
        for system_id, text_prefix in marker.items():
            a_count = 0
            b_count = 0
            for packet in built["packets"].values():
                for item in packet["items"]:
                    if item["kind"] != "pair_comparison":
                        continue
                    side_a = item["sides"]["A"]["candidates"][0]["text"]
                    if side_a.startswith(text_prefix):
                        a_count += 1
                    else:
                        b_count += 1
            assert abs(a_count - b_count) <= 1, (system_id, a_count, b_count)
            assert a_count > 0 and b_count > 0, (system_id, a_count, b_count)
        # Randomization: the two raters see different A/B orderings.
        def _alpha_first_system(packet):
            out = []
            for item in packet["items"]:
                if item["kind"] == "pair_comparison":
                    first = item["sides"]["A"]["candidates"][0]["text"]
                    out.append(SYSTEM_A if first.startswith(marker[SYSTEM_A]) else SYSTEM_B)
            return out

        alpha_pattern = _alpha_first_system(built["packets"]["r-alpha"])
        beta_pattern = _alpha_first_system(built["packets"]["r-beta"])
        gamma_pattern = _alpha_first_system(built["packets"]["r-gamma"])
        assert alpha_pattern != beta_pattern
        assert beta_pattern != gamma_pattern or alpha_pattern != gamma_pattern
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 5: private review-key text does not leak unless preregistered ----------


def test_review_key_text_only_when_preregistered() -> None:
    secret = "MATCHES_SOURCE_PROFILE_ALPHA_MARKER"
    directory = Path(tempfile.mkdtemp())
    try:
        # Default: expectations are unused, so the marker cannot appear.
        _, _, prereg_default, built_default = _build(directory)
        assert prereg_default["authorExpectationPolicy"]["mode"] == "not_used"
        for packet in built_default["packets"].values():
            assert secret not in HE.canonical_json(packet)

        checklist_dir = Path(tempfile.mkdtemp())
        try:
            checklist = {"t-alt": [secret]}
            _, _, prereg_check, built_check = _build(
                checklist_dir, expectation_mode="reviewer_checklist", checklist=checklist
            )
            assert prereg_check["authorExpectationPolicy"]["mode"] == "reviewer_checklist"
            # Now the explicitly preregistered checklist IS visible, and only as
            # reviewer checklist material labelled not-validated-gold.
            found = False
            for packet in built_check["packets"].values():
                for item in packet["items"]:
                    checklist_block = item.get("reviewerChecklist")
                    if checklist_block and secret in checklist_block["items"]:
                        found = True
                        assert "not human-validated gold" in checklist_block["status"]
            assert found, "preregistered checklist should be visible as reviewer material"
            # Still no model identity for the expectation author to see.
            assert SYSTEM_A not in HE.canonical_json(built_check["packets"]["r-alpha"])
        finally:
            shutil.rmtree(checklist_dir, ignore_errors=True)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 6: unknown / duplicate rating rows fail validation ---------------------


def test_unknown_and_duplicate_rows_fail_validation() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        packet = _packet_for(built, HE.DEFAULT_RATERS[0])
        mapping = built["privateMapping"]
        good = _synthetic_ratings(packet)

        clean = HE.validate_rating_document(
            good, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert clean.ok, clean.errors

        unknown = json.loads(json.dumps(good))
        unknown["pairRatings"].append(
            {"pairId": "pair-does-not-exist", "criterion": "edit_usefulness", "label": "A"}
        )
        report = HE.validate_rating_document(
            unknown, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert not report.ok
        assert any("unknown pairId" in error for error in report.errors)

        duplicate = json.loads(json.dumps(good))
        first = duplicate["pairRatings"][0]
        duplicate["pairRatings"].append(dict(first))
        report = HE.validate_rating_document(
            duplicate, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert not report.ok
        assert any("duplicates an existing rating" in error for error in report.errors)

        impossible = json.loads(json.dumps(good))
        impossible["pairRatings"][0]["label"] = "C"
        report = HE.validate_rating_document(
            impossible, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert not report.ok
        assert any("impossible label" in error for error in report.errors)

        missing = json.loads(json.dumps(good))
        missing["pairRatings"] = [
            row for row in missing["pairRatings"] if row["criterion"] != "edit_usefulness"
        ]
        report = HE.validate_rating_document(
            missing, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert not report.ok
        assert any("missing required criteria" in error for error in report.errors)

        stale = json.loads(json.dumps(good))
        stale["packetSha256"] = "0" * 64
        report = HE.validate_rating_document(
            stale, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert not report.ok
        assert any("outdated" in error for error in report.errors)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 7: intentional-compression uses its own criterion contract ------------


def test_compression_items_use_separate_criterion() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, _, built = _build(directory)
        packet = _packet_for(built, HE.DEFAULT_RATERS[0])
        by_task = {
            item["taskId"]: item
            for item in packet["items"]
            if item["kind"] == "pair_comparison"
        }
        normal = by_task["t-alt"]
        compression = by_task["t-comp"]
        normal_criteria = {entry["criterion"] for entry in normal["criteria"]}
        compression_criteria = {entry["criterion"] for entry in compression["criteria"]}
        assert "meaning_preservation" in normal_criteria
        assert "compression_quality" not in normal_criteria
        assert "compression_quality" in compression_criteria
        assert "meaning_preservation" not in compression_criteria
        assert compression["semanticMode"] == HE.SEMANTIC_MODE_COMPRESSION
        # The protected-context criterion is added only for protected tasks.
        assert "protected_content_correctness" in {e["criterion"] for e in by_task["t-prot"]["criteria"]}
        assert "protected_content_correctness" not in normal_criteria
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 8: strength grouping and ordered identity ------------------------------


def test_strength_variants_grouped_and_ordered() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        packet = _packet_for(built, HE.DEFAULT_RATERS[0])
        trajectories = [
            item for item in packet["items"] if item["kind"] == "strength_trajectory"
        ]
        assert len(trajectories) == 1
        trajectory = trajectories[0]
        assert trajectory["strengths"] == [15, 40, 60, 90]
        assert [v["requestedStrength"] for v in trajectory["variants"]] == [15, 40, 60, 90]
        assert trajectory["taskIds"] == [f"t-str-s{s}" for s in (15, 40, 60, 90)]
        assert preregistration["strengthSlider"]["sourceGroupCount"] == 1
        assert preregistration["strengthSlider"]["repeatedMeasures"] is True
        assert preregistration["strengthSlider"]["editDistanceAloneIsNotQuality"] is True
        # Change diagnostics travel with each ordered variant, deterministically.
        for variant in trajectory["variants"]:
            assert variant["changeDiagnostics"] is not None
            assert "charSimilarity" in variant["changeDiagnostics"]
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 9: ties and both-unacceptable are first-class ---------------------------


def test_ties_and_both_unacceptable_are_first_class() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        mapping = built["privateMapping"]
        validated = []
        for rater_id in ("r-alpha", "r-beta"):
            packet = _packet_for(built, rater_id)
            document = _synthetic_ratings(packet)
            report = HE.validate_rating_document(
                document, packet=packet, preregistration=preregistration, private_mapping=mapping
            )
            assert report.ok, report.errors
            validated.append(report.normalized)

        analysis = HE.analyze(
            preregistration, mapping, validated, seed=SEED, bootstrap_resamples=64
        )
        assert analysis["collapsedScalar"] is None
        # At least one criterion must have both a tie and a both-unacceptable.
        saw_tie = False
        saw_both = False
        for entry in analysis["perCriterion"]:
            if entry["rawCounts"]["tie"] > 0:
                saw_tie = True
            if entry["rawCounts"]["both_unacceptable"] > 0:
                saw_both = True
            # Directional mean excludes both-unacceptable rows.
            assert (
                entry["directionalAnnotations"]
                + entry["bothUnacceptableAnnotations"] == entry["annotationCount"]
            )
        assert saw_tie and saw_both
        # Reliability is reported with assumptions, not a bare number.
        for entry in analysis["reliability"].values():
            assert entry["fleissKappa"]["assumptions"]
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 10: analysis refuses mixed rubric / preregistration hashes --------------


def test_analysis_refuses_mixed_hashes() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        mapping = built["privateMapping"]
        packet = _packet_for(built, "r-alpha")
        good = _synthetic_ratings(packet)
        report = HE.validate_rating_document(
            good, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert report.ok, report.errors

        other = json.loads(json.dumps(report.normalized))
        other["rubricSha256"] = "1" * 64
        try:
            HE.analyze(preregistration, mapping, [report.normalized, other], seed=SEED)
            raise AssertionError("analysis must refuse mixed rubric bindings")
        except HE.HumanEvalContractError as exc:
            assert "different preregistration/rubric bindings" in str(exc)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 11: post-hoc exclusion surfaced as exploratory -------------------------


def test_posthoc_exclusion_is_exploratory() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        mapping = built["privateMapping"]
        validated = []
        for rater_id in ("r-alpha", "r-beta"):
            packet = _packet_for(built, rater_id)
            document = _synthetic_ratings(packet)
            report = HE.validate_rating_document(
                document, packet=packet, preregistration=preregistration, private_mapping=mapping
            )
            assert report.ok, report.errors
            validated.append(report.normalized)
        # Drop every pairwise row from beta: it now only has candidate+strength
        # ratings, so the preregistered "incomplete" rule excludes it.
        beta = dict(validated[1])
        beta["pairRatings"] = []
        validated[1] = beta

        analysis = HE.analyze(
            preregistration, mapping, validated, seed=SEED, bootstrap_resamples=32
        )
        excluded = [e for e in analysis["exclusions"] if e["raterId"] == "r-beta"]
        assert excluded, "beta should be excluded"
        assert excluded[0]["status"] == "preregistered"
        assert "incomplete" in excluded[0]["reasons"]
        assert analysis["analysedRaterCount"] == 1

        # A rater who submits nothing but candidate/strength rows and matches no
        # preregistered rule is surfaced as exploratory, never silently accepted.
        gamma = {
            "raterId": "r-gamma",
            "packetId": "x",
            "packetSha256": "y" * 64,
            "preregistrationSha256": preregistration["preregistrationSha256"],
            "rubricSha256": preregistration["protocol"]["rubricSha256"],
            "pairRatings": [],
            "candidateRatings": [],
            "strengthRatings": [],
        }
        prereg_no_rule = json.loads(json.dumps(preregistration))
        prereg_no_rule["policies"]["raterEligibilityPolicy"]["preregisteredExclusionRules"] = []
        analysis2 = HE.analyze(
            prereg_no_rule, mapping, [*validated, gamma], seed=SEED, bootstrap_resamples=16
        )
        gamma_exclusions = [e for e in analysis2["exclusions"] if e["raterId"] == "r-gamma"]
        assert gamma_exclusions, "a rule-less exclusion must still be recorded"
        assert gamma_exclusions[0]["status"] == "exploratory"
        assert gamma_exclusions[0]["ruleIds"] == []
        assert "exploratory" in gamma_exclusions[0]["note"]
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- 12: mapping revealed only at analysis, digest retained -----------------


def test_mapping_revealed_only_at_analysis() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        mapping = built["privateMapping"]
        packets_blob = "".join(
            HE.canonical_json(packet) for packet in built["packets"].values()
        ).lower()
        # Before analysis, packets do not reveal identities or the mapping digest.
        assert SYSTEM_A.lower() not in packets_blob
        assert mapping["mappingSha256"].lower() not in packets_blob

        validated = []
        for rater_id in ("r-alpha", "r-beta"):
            packet = _packet_for(built, rater_id)
            document = _synthetic_ratings(packet)
            report = HE.validate_rating_document(
                document, packet=packet, preregistration=preregistration, private_mapping=mapping
            )
            assert report.ok, report.errors
            validated.append(report.normalized)

        blind = HE.analyze(
            preregistration,
            mapping,
            validated,
            seed=SEED,
            reveal_mapping=False,
            bootstrap_resamples=16,
        )
        assert blind["blindingReveal"] is None
        assert SYSTEM_A.lower() not in HE.canonical_json(blind).lower()

        revealed = HE.analyze(
            preregistration,
            mapping,
            validated,
            seed=SEED,
            reveal_mapping=True,
            bootstrap_resamples=16,
        )
        reveal = revealed["blindingReveal"]
        assert reveal is not None
        assert reveal["mappingSha256"] == mapping["mappingSha256"]
        # The reveal reproduces exactly the private mapping's finalist ids.
        assert reveal["systems"] == {
            entry["systemKey"]: {"systemId": entry["systemId"], "revision": entry["revision"]}
            for entry in mapping["systems"]
        }
        assert {entry["systemId"] for entry in mapping["systems"]} == {
            SYSTEM_A + "-hf",
            SYSTEM_B + "-hf",
        }

        # Corrupting the mapping breaks the digest check.
        corrupted = json.loads(json.dumps(mapping))
        corrupted["systems"][0]["systemId"] = "tampered"
        try:
            HE.analyze(
                preregistration,
                corrupted,
                validated,
                seed=SEED,
                bootstrap_resamples=16,
            )
            raise AssertionError("analysis must refuse a tampered mapping")
        except HE.HumanEvalContractError as exc:
            assert "mapping digest does not match" in str(exc)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- extra: mixed task/result identity is refused ----------------------------


def test_preregistration_keeps_finalist_names_in_private_mapping_only() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        blob = HE.canonical_json(preregistration).lower()
        # The preregistration binds result digests and counts, never the names.
        assert "alpha-model" not in blob
        assert "bravo-model" not in blob
        assert preregistration["finalistCount"] == 2
        assert len(preregistration["resultArtifacts"]) == 2
        for entry in preregistration["resultArtifacts"]:
            assert set(entry) == {"resultSha256", "taskFileSha256", "revision"}
        assert preregistration["finalistIdentityPolicy"]["identitiesLiveIn"] == (
            "private mapping artifact only"
        )
        # The private mapping holds them, with its own digest.
        mapping_blob = HE.canonical_json(built["privateMapping"]).lower()
        assert "alpha-model" in mapping_blob
        assert "bravo-model" in mapping_blob
        assert built["privateMapping"]["mappingSha256"]
        # Every digest chain from preregistration through mapping is bound.
        assert built["privateMapping"]["preregistrationSha256"] == (
            preregistration["preregistrationSha256"]
        )
        assert preregistration["protocol"]["sha256"] == HE.sha256_file(
            HE.HERE / HE.PROTOCOL_RELATIVE_PATH
        )
        assert preregistration["usableCandidateContract"]["sha256"] == HE.sha256_file(
            HE.HERE / "word_studio_output_parser.py"
        )
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_rating_data_carrying_private_mapping_is_rejected() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        _, _, preregistration, built = _build(directory)
        packet = _packet_for(built, "r-alpha")
        mapping = built["privateMapping"]
        document = _synthetic_ratings(packet)
        # Smuggle the private system key into a free-text note.
        document["pairRatings"][0]["note"] = (
            "side A looks like " + mapping["systems"][0]["systemKey"]
        )
        report = HE.validate_rating_document(
            document, packet=packet, preregistration=preregistration, private_mapping=mapping
        )
        assert not report.ok
        assert any("private mapping content" in error for error in report.errors)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_standalone_rating_schema_matches_module() -> None:
    """The checked-in schema file must not drift from the module definition."""
    on_disk = HE.HERE / "word-studio-human-eval-rating-schema.json"
    assert on_disk.is_file(), f"missing {on_disk.name}"
    assert json.loads(on_disk.read_text(encoding="utf-8")) == HE.rating_schema()


def test_mixed_result_identity_refused() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        tasks_a = _write_tasks(directory / "a", marker="suite-a", prefix="ta")
        tasks_b = _write_tasks(directory / "b", marker="suite-b", prefix="tb")
        assert HE.sha256_file(tasks_a) != HE.sha256_file(tasks_b)
        result_a = _write_result(directory, tasks_a, SYSTEM_A, "rev-a", MARKER_A)
        result_b = _write_result(directory / "b", tasks_b, SYSTEM_B, "rev-b", MARKER_B)
        # System B's result belongs to task file B, so loading both against task
        # file A alone must be refused rather than silently reconciled.
        try:
            HE.load_inputs(
                task_files=[tasks_a],
                result_files=[result_a, result_b],
            )
            raise AssertionError("must refuse a result artifact from a different task file")
        except HE.HumanEvalContractError as exc:
            assert "refusing to mix identities" in str(exc) or "does not match any frozen task" in str(exc)

        # The same two task files, both frozen, load cleanly.
        both = HE.load_inputs(
            task_files=[tasks_a, tasks_b],
            result_files=[result_a, result_b],
        )
        assert len(both.systems) == 2
        assert len(both.task_index) == 16
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_needs_two_finalists() -> None:
    directory = Path(tempfile.mkdtemp())
    try:
        tasks = _write_tasks(directory)
        single = _write_result(directory, tasks, SYSTEM_A, "rev-a", "one")
        try:
            HE.load_inputs(task_files=[tasks], result_files=[single])
            raise AssertionError("must refuse fewer than two finalists")
        except HE.HumanEvalContractError as exc:
            assert "at least two qualified finalists" in str(exc)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"word studio human-eval pipeline fixtures passed ({len(tests)} tests)")


if __name__ == "__main__":
    main()
