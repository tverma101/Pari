#!/usr/bin/env python3
"""CPU-only tests for the issue #56 weight-sensitivity lane.

No GPU, no network, no model, no private data. The fixtures here are
synthetic *score-report* doubles written into a temp directory; they exist only
to prove the fail-closed behaviour (provenance mismatch, incomplete coverage,
ranking flip, withheld interval). They are not evidence about any real model.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import kaggle_weight_sensitivity as WS

HERE = Path(__file__).resolve().parent
DIMENSIONS = json.loads(
    (HERE / "kaggle-weight-sensitivity-grid.json").read_text(encoding="utf-8")
)["dimensionOrder"]

FAKE_INPUTS = {
    "configSha256": "a" * 64,
    "shadowSeedSha256": "b" * 64,
    "shadowTaskSha256": "c" * 64,
    "shadowManifestSha256": "d" * 64,
    "generativeMetricContractSha256": "e" * 64,
}


def make_score(
    values: dict, *, complete: bool = True, inputs: dict | None = None, name: str = "alpha"
) -> dict:
    dimension_scores = {}
    for d in DIMENSIONS:
        dimension_scores[d] = {
            "cases": 10,
            "scored": 10 if complete else 9,
            "missing": 0 if complete else 1,
            "complete": complete,
            "score100": values[d] if complete else None,
        }
    inputs = inputs or FAKE_INPUTS
    return {
        "version": 8,
        "schemaVersion": 1,
        "artifactType": "pari.english-core.shadow-score",
        "inputResultSchema": {
            "validatorContractVersion": 1,
            "validationMode": "promotion",
            "resultSchemaVersion": 1,
            "schemaSha256": WS.RESULT_SCHEMA_SHA256,
            "compatibilityMode": None,
        },
        "runId": f"run-{name}",
        "model": {"name": name},
        "taskFileSha256": inputs["shadowTaskSha256"],
        "benchmarkInputs": dict(inputs),
        "dimensionScores": dimension_scores,
        "englishCoreShadow100": None,
        "equalWeightDimensionMean100": None,
        "complete": complete,
    }


def balanced() -> dict:
    return {d: 70.0 for d in DIMENSIONS}


def lexically_strong() -> dict:
    # Leads on the highest-weight dimension, trails the low-weight one.
    v = balanced()
    v["lexical_context"] = 86.0
    v["discourse"] = 52.0
    return v


def write_case(tmp: Path, scores: list[dict], *, contender_extra: dict | None = None) -> Path:
    contender_file = tmp / "contenders.json"
    contenders = []
    for i, score in enumerate(scores):
        name = score["model"]["name"]
        (tmp / f"{name}.score.json").write_text(json.dumps(score), encoding="utf-8")
        entry = {
            "id": name,
            "scorePath": f"{name}.score.json",
            "runtimeQualified": True,
        }
        entry.update((contender_extra or {}).get(name, {}))
        contenders.append(entry)
    contender_file.write_text(json.dumps({"contenders": contenders}, indent=2), encoding="utf-8")
    return contender_file


def test_grid_is_valid_and_covers_config_dimensions() -> None:
    grid = WS.load_grid()
    config = json.loads(WS.CONFIG_PATH.read_text(encoding="utf-8"))
    assert set(grid["dimensionOrder"]) == set(config["composite"]["weights"])
    WS.validate_grid(grid)


def test_grid_vectors_all_sum_to_one_hundred() -> None:
    for name, weights in WS.normalized_vectors(WS.load_grid()).items():
        assert abs(sum(weights.values()) - 100.0) < 1e-6, name


def test_leave_one_out_is_derived_from_product_not_hand_edited() -> None:
    grid = WS.load_grid()
    vectors = WS.normalized_vectors(grid)
    product = vectors["product"]
    loo = {k: v for k, v in vectors.items() if k.startswith("leave_out_")}
    assert len(loo) == len(DIMENSIONS)
    for dropped in DIMENSIONS:
        key = f"leave_out_{dropped}"
        assert key in vectors
        assert dropped not in vectors[key]
        expected = 100.0 - product[dropped]
        assert abs(sum(vectors[key].values()) - 100.0) < 1e-6, key
        # surviving dimensions keep their relative product proportions and are
        # renormalized back to a full 100 percent
        for d in vectors[key]:
            want = product[d] * 100.0 / expected
            assert abs(vectors[key][d] - want) < 1e-6, f"{key}.{d}"


def test_grid_rejects_a_vector_that_does_not_sum_to_one_hundred() -> None:
    grid = WS.load_grid()
    grid["vectors"]["product"]["weights"]["discourse"] = 9
    try:
        WS.validate_grid(grid)
    except ValueError as exc:
        assert "100" in str(exc)
    else:
        raise AssertionError("a grid vector that does not sum to 100 must be rejected")


def test_grid_rejects_missing_dimension_coverage() -> None:
    grid = WS.load_grid()
    grid["vectors"]["product"]["weights"].pop("discourse")
    try:
        WS.validate_grid(grid)
    except ValueError as exc:
        assert "declared dimensions" in str(exc)
    else:
        raise AssertionError("a partial grid vector must be rejected")


def test_a_clean_pair_produces_a_report() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp,
            [
                make_score(balanced(), name="alpha"),
                make_score(lexically_strong(), name="beta"),
            ],
        )
        report = WS.build_report(contender_file, 2000)
    assert report["status"] == "computed"
    assert report["excluded"] == []
    assert len(report["weightGridSha256"]) == 64
    assert report["bootstrapSeedHex"].startswith("0x")
    assert report["sharedBenchmarkInputs"] == FAKE_INPUTS
    assert "product" in report["rankings"] and "equal_weight" in report["rankings"]


def test_provenance_mismatch_withholds_instead_of_ranking() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        drifted = dict(FAKE_INPUTS)
        drifted["shadowSeedSha256"] = "f" * 64
        contender_file = write_case(
            tmp,
            [
                make_score(balanced(), name="alpha"),
                make_score(lexically_strong(), name="beta", inputs=drifted),
            ],
        )
        report = WS.build_report(contender_file, 1000)
    assert report["status"] == "withheld"
    assert "benchmarkInputs" in report["withheldReason"]
    assert "rankings" not in report


def test_expected_case_count_mismatch_withholds_the_contender() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp,
            [make_score(balanced(), name="alpha"), make_score(lexically_strong(), name="beta")],
            contender_extra={"beta": {"expectedDimensionCases": {"discourse": 99}}},
        )
        report = WS.build_report(contender_file, 1000)
    assert report["status"] == "withheld"
    assert "fewer than two fully provenance-clean score reports" in report["withheldReason"]


def test_incomplete_dimension_is_never_silently_averaged() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp,
            [
                make_score(balanced(), name="alpha"),
                make_score(lexically_strong(), name="beta", complete=False),
            ],
        )
        report = WS.build_report(contender_file, 1000)
    assert report["status"] == "withheld"


def test_runtime_unqualified_candidate_is_excluded() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp,
            [make_score(balanced(), name="alpha"), make_score(lexically_strong(), name="beta")],
            contender_extra={"beta": {"runtimeQualified": False}},
        )
        report = WS.build_report(contender_file, 1000)
    assert report["status"] == "withheld"


def test_missing_result_schema_provenance_withholds_score_report() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        score = make_score(balanced())
        score.pop("inputResultSchema")
        path = tmp / "alpha.score.json"
        path.write_text(json.dumps(score), encoding="utf-8")
        loaded = WS.load_score({"id": "alpha", "scorePath": path.name, "runtimeQualified": True}, tmp, DIMENSIONS)
    assert any("inputResultSchema" in reason for reason in loaded["withheldReasons"])


def test_schema_version_drift_withholds_score_report() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        score = make_score(balanced())
        score["inputResultSchema"]["resultSchemaVersion"] = 2
        path = tmp / "alpha.score.json"
        path.write_text(json.dumps(score), encoding="utf-8")
        loaded = WS.load_score({"id": "alpha", "scorePath": path.name, "runtimeQualified": True}, tmp, DIMENSIONS)
    assert any("current English Core result schema" in reason for reason in loaded["withheldReasons"])


def test_missing_score_file_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = tmp / "contenders.json"
        contender_file.write_text(
            json.dumps(
                {
                    "contenders": [
                        {"id": "ghost-a", "scorePath": "nope-a.json"},
                        {"id": "ghost-b", "scorePath": "nope-b.json"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        report = WS.build_report(contender_file, 1000)
    assert report["status"] == "withheld"
    assert all("not found" in r for c in report["contenders"] for r in c["withheldReasons"])


def test_weight_grid_reports_ranking_flips_instead_of_a_winner() -> None:
    """A contender that leads only on the heaviest dimension must be flagged."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp,
            [make_score(balanced(), name="alpha"), make_score(lexically_strong(), name="beta")],
        )
        report = WS.build_report(contender_file, 4000)
    assert report["status"] == "computed"
    flip = report["productVsEqualWeights"]
    assert flip["productLeader"] != flip["equalWeightLeader"]
    assert flip["rankingFlipsUnderEqualWeights"] is True
    assert report["rankingStability"]["leaderStableAcrossGrid"] is False
    assert len(report["rankingStability"]["distinctLeaders"]) > 1
    largest = report["leaveOneDimensionDriver"]["largestSingleDimensionContribution"]
    assert largest["dimension"] == "lexical_context"
    # beta leads the product composite and trails the equal-weight mean, so the
    # paired product delta (alpha minus beta) must be negative.
    delta = report["leaveOneDimensionDriver"]["productDeltaAminusB100"]
    assert delta < 0
    assert (delta < 0) == (flip["productLeader"] == "beta")


def test_tied_competitors_stay_inconclusive() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp,
            [make_score(balanced(), name="alpha"), make_score(balanced(), name="beta")],
        )
        report = WS.build_report(contender_file, 2000)
    assert report["status"] == "computed"
    paired = report["pairedByVector"]["product"]
    assert paired["deltaAminusB100"] == 0
    assert paired["conclusion"] == "inconclusive"
    assert paired["pairedDimensionBootstrap95"] == [0.0, 0.0]


def test_leave_one_out_flip_is_reported_when_a_dimension_carries_the_lead() -> None:
    # Beta's lead is entirely lexical_context, the 25% dimension. Alpha leads
    # the other six dimensions by 10 points each. Product weights still favour
    # Beta (0.25 * 40 - 0.75 * 10 = +4); dropping and renormalizing
    # lexical_context must flip the sign to Alpha. That is exactly the
    # "one dimension drives the entire lead" case from the issue.
    alpha = balanced()
    alpha["lexical_context"] = 40.0
    beta = balanced()
    beta["lexical_context"] = 80.0
    for d in DIMENSIONS:
        if d != "lexical_context":
            beta[d] = 60.0
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp, [make_score(alpha, name="alpha"), make_score(beta, name="beta")]
        )
        report = WS.build_report(contender_file, 2000)
    assert report["status"] == "computed"
    driver = report["leaveOneDimensionDriver"]
    assert driver["productDeltaAminusB100"] < 0
    assert "leave_out_lexical_context" in driver["leaveOneOutSignFlips"]
    assert driver["leaveOneOutSignFlips"]
    assert driver["leadSurvivesEveryLeaveOneOut"] is False


def test_bootstrap_is_deterministic_for_a_frozen_seed() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp,
            [make_score(balanced(), name="alpha"), make_score(lexically_strong(), name="beta")],
        )
        first = WS.build_report(contender_file, 2000)
        second = WS.build_report(contender_file, 2000)
    assert first["pairedByVector"] == second["pairedByVector"]


def test_iterations_below_the_floor_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = write_case(
            tmp, [make_score(balanced(), name="alpha"), make_score(lexically_strong(), name="beta")]
        )
        try:
            WS.build_report(contender_file, 10)
        except ValueError as exc:
            assert "1000" in str(exc)
        else:
            raise AssertionError("an undersized bootstrap must be rejected")


def test_single_contender_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = tmp / "contenders.json"
        contender_file.write_text(
            json.dumps({"contenders": [{"id": "solo", "scorePath": "solo.json"}]}),
            encoding="utf-8",
        )
        try:
            WS.build_report(contender_file, 1000)
        except ValueError as exc:
            assert "at least two" in str(exc)
        else:
            raise AssertionError("a single contender cannot support a paired claim")


def test_duplicate_contender_ids_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        contender_file = tmp / "contenders.json"
        contender_file.write_text(
            json.dumps(
                {
                    "contenders": [
                        {"id": "same", "scorePath": "a.json"},
                        {"id": "same", "scorePath": "b.json"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        try:
            WS.build_report(contender_file, 1000)
        except ValueError as exc:
            assert "unique" in str(exc)
        else:
            raise AssertionError("duplicate contender ids must be rejected")


def main() -> None:
    tests = [v for name, v in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok " + test.__name__)
    print("Weight-sensitivity tests passed (%d cases)." % len(tests))


if __name__ == "__main__":
    main()
