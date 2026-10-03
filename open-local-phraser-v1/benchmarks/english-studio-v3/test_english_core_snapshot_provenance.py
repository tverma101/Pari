"""Issue #65 fail-closed tests for English Core snapshot/scorer provenance.

All evidence in this file is FABRICATED. No model, GPU, Kaggle session, or real
score report is involved. The fixtures rebuild the current in-tree benchmark
snapshot with ``build-english-core.mjs`` (the same no-model builder
``self-check-english-core.sh`` runs) and score a synthetic, fully-populated
result through ``english_core_choice_views.score_view_contract`` so the
declarations under test are exactly the ones a real #64 scorer emits.

The behaviours pinned here are:

* a source score whose bytes no longer match a frozen manifest is rejected,
* a stale config or stale private seed cannot be re-analyzed,
* a legacy score with missing/partial ``benchmarkInputs`` fails closed,
* a fully matching current fixture analyzes and records its provenance.

Run: python3 test_english_core_snapshot_provenance.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANALYZE = HERE / "analyze-english-core-statistics.mjs"
COMPARE = HERE / "compare-english-core-models.mjs"
BUILDER = HERE / "build-english-core.mjs"

SNAPSHOT_FILES = {
    "configSha256": "english-core-config.json",
    "shadowSeedSha256": "english-core-shadow.seed.json",
    "shadowTaskSha256": "english-core-shadow.jsonl",
    "shadowManifestSha256": "english-core-shadow.manifest.json",
    "generativeMetricContractSha256": "english-core-generative-metric-contract.json",
}

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


def load_choice_views():
    spec = importlib.util.spec_from_file_location(
        "english_core_choice_views_under_test", HERE / "english_core_choice_views.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_node(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["node", *args], capture_output=True, text=True, cwd=HERE)


def analyze(score_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return run_node([str(ANALYZE), str(score_path), "1000", *extra])


def compare(a_path: Path, b_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return run_node([str(COMPARE), str(a_path), str(b_path), "1000", *extra])


def fails_with(result: subprocess.CompletedProcess, *fragments: str) -> bool:
    if result.returncode == 0:
        return False
    stderr = result.stderr or ""
    return all(fragment in stderr for fragment in fragments)


def ensure_snapshot() -> None:
    """Regenerate the no-model shadow snapshot so its bytes are current."""
    built = run_node([str(BUILDER)])
    if built.returncode != 0:
        raise RuntimeError(f"build-english-core.mjs failed: {built.stderr[:400]}")
    missing = [name for name in SNAPSHOT_FILES.values() if not (HERE / name).is_file()]
    if missing:
        raise RuntimeError(f"benchmark snapshot incomplete; missing {missing}")


def build_fixture_scores(root: Path) -> tuple[Path, Path, Path]:
    """Return (scoreA, scoreB, frozenManifest) built from the live snapshot."""
    choice_views = load_choice_views()
    seed = json.loads((HERE / SNAPSHOT_FILES["shadowSeedSha256"]).read_text())
    task_text = (HERE / SNAPSHOT_FILES["shadowTaskSha256"]).read_text()
    task_rows = [json.loads(line) for line in task_text.split("\n") if line.strip()]
    task_sha = sha256_text(task_text)

    benchmark_inputs = {
        "configSha256": sha256_file(HERE / SNAPSHOT_FILES["configSha256"]),
        "shadowSeedSha256": sha256_file(HERE / SNAPSHOT_FILES["shadowSeedSha256"]),
        "shadowTaskSha256": task_sha,
        "shadowManifestSha256": sha256_file(HERE / SNAPSHOT_FILES["shadowManifestSha256"]),
        "generativeMetricContractSha256": sha256_file(
            HERE / SNAPSHOT_FILES["generativeMetricContractSha256"]
        ),
    }

    def score_report(score: float, run_id: str, selected_view: str | None = None) -> dict:
        dimension_scores: dict[str, dict] = {}
        detail = []
        for row in seed["cases"]:
            detail.append(
                {
                    "id": row["id"],
                    "dimension": row["dimension"],
                    "phenomenon": row.get("phenomenon"),
                    "score": score,
                }
            )
            bucket = dimension_scores.setdefault(
                row["dimension"], {"cases": 0, "scored": 0, "missing": 0, "complete": True}
            )
            bucket["cases"] += 1
            bucket["scored"] += 1

        report = {
            "version": 8,
            "schemaVersion": 1,
            "artifactType": "pari.english-core.shadow-score",
            "inputResultSchema": {
                "validatorContractVersion": 2,
                "validationMode": "promotion",
                "resultSchemaVersion": 1,
                "schemaSha256": sha256_file(HERE / "english-core-result-schema.json"),
                "compatibilityMode": None,
            },
            "runId": run_id,
            "model": {"name": f"fixture-{run_id}"},
            "taskFile": SNAPSHOT_FILES["shadowTaskSha256"],
            "taskFileSha256": task_sha,
            "taskCount": len(task_rows),
            "shadowCases": len(seed["cases"]),
            "benchmarkInputs": dict(benchmark_inputs),
            "dimensionScores": dimension_scores,
            "englishCoreShadow100": score * 100,
            "complete": True,
            "detail": detail,
        }
        contract = choice_views.score_view_contract(
            contract_path=HERE / "english_core_choice_views.py",
            task_file_sha256=task_sha,
            task_manifest_sha256=benchmark_inputs["shadowManifestSha256"],
            source_run_id=run_id,
        )
        if selected_view is not None:
            contract["selected"] = selected_view
            contract["primaryScreeningView"] = selected_view
        return choice_views.with_score_view(report, contract)

    def write(name: str, report: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return path

    score_a = write("score-a.json", score_report(0.8, "fixture-a"))
    score_b = write("score-b.json", score_report(0.6, "fixture-b"))

    frozen = root / "frozen-score-manifest.json"
    frozen.write_text(
        json.dumps(
            {
                "description": "Frozen hashes of the score artifacts as recorded at scoring time.",
                "scores": [
                    {"path": str(score_a), "scoreSha256": sha256_file(score_a)},
                    {"path": str(score_b), "scoreSha256": sha256_file(score_b)},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return score_a, score_b, frozen


def mutate(root: Path, source: Path, name: str, mutate_fn) -> Path:
    report = json.loads(source.read_text())
    mutate_fn(report)
    path = root / name
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def test_current_fixture_fully_analyzes(root: Path) -> None:
    score_a, _score_b, frozen = build_fixture_scores(root)
    result = analyze(score_a, "--source-score-manifest", str(frozen))
    check(result.returncode == 0, f"matching fixture must analyze; stderr: {result.stderr[:400]}")
    if result.returncode != 0:
        return
    report = json.loads(result.stdout)
    provenance = report["provenance"]

    check(
        provenance["sourceScore"]["fileSha256"] == sha256_file(score_a),
        "provenance must record the exact source score file hash",
    )
    check(
        provenance["analysis"]["sha256"] == sha256_file(ANALYZE),
        "provenance must record the analysis script hash",
    )
    check(
        provenance["scorer"]["sha256"] == sha256_file(HERE / "score-english-core.mjs"),
        "provenance must record the scorer script hash",
    )
    check(
        provenance["benchmarkSnapshot"]["allConsumedInputsVerified"] is True,
        "provenance must assert every consumed benchmark input was hash-verified",
    )
    for key, filename in SNAPSHOT_FILES.items():
        consumed = provenance["benchmarkSnapshot"]["consumedInputs"][key]
        check(consumed["file"] == filename, f"consumed input {key} must name {filename}")
        check(
            consumed["sha256"] == sha256_file(HERE / filename),
            f"consumed input {key} hash must be the on-disk snapshot hash",
        )
    check(
        provenance["bootstrap"]["seed"] == report["bootstrapSeed"],
        "provenance bootstrap seed must match the report's bootstrap seed",
    )
    check(
        provenance["bootstrap"]["iterations"] == report["bootstrapIterations"],
        "provenance bootstrap iterations must match the report's bootstrap iterations",
    )
    check(
        provenance["scoreView"]["selected"] == "recoverable_anchored",
        "the primary screening view declared by #64 must be the analyzed view",
    )
    check(
        provenance["scoreView"]["contract"]["verifiedLocally"] is True,
        "the #64 score-view contract bytes must be verified against the snapshot",
    )
    check(
        provenance["frozenScoreManifest"]["verifiedScoreFiles"]["score-a.json"]["sha256"]
        == sha256_file(score_a),
        "the frozen manifest verification must bind the analyzed score file",
    )
    check(
        report["structureReconciliation"]["reconciledComplete"] is True,
        "the fully matching fixture must reconcile as complete",
    )
    check(report["compositeComplete"] is True, "the fully matching fixture must complete the composite")


def test_tampered_source_score_is_rejected(root: Path) -> None:
    score_a, _score_b, frozen = build_fixture_scores(root)
    tampered = mutate(
        root,
        score_a,
        "score-a-edited-after-scoring.json",
        lambda report: report.update({"englishCoreShadow100": 99.9}),
    )
    result = analyze(tampered, "--source-score-manifest", str(frozen))
    check(
        fails_with(result, "not recorded in the frozen manifest"),
        f"a score edited after scoring must fail closed; stderr: {result.stderr[:300]}",
    )

    compared = compare(tampered, score_a, "--source-score-manifest", str(frozen))
    check(
        fails_with(compared, "not recorded in the frozen manifest"),
        f"paired comparison must reject an edited score; stderr: {compared.stderr[:300]}",
    )


def test_stale_config_and_seed_are_rejected(root: Path) -> None:
    score_a, _score_b, frozen = build_fixture_scores(root)
    stale_config = mutate(
        root,
        score_a,
        "score-a-stale-config.json",
        lambda report: report["benchmarkInputs"].update({"configSha256": "c" * 64}),
    )
    result = analyze(stale_config, "--source-score-manifest", str(frozen))
    check(
        fails_with(result, "benchmarkInputs.configSha256 does not match"),
        f"a stale config hash must fail closed; stderr: {result.stderr[:300]}",
    )

    stale_seed = mutate(
        root,
        score_a,
        "score-a-stale-seed.json",
        lambda report: report["benchmarkInputs"].update({"shadowSeedSha256": "d" * 64}),
    )
    seed_result = analyze(stale_seed, "--source-score-manifest", str(frozen))
    check(
        fails_with(seed_result, "benchmarkInputs.shadowSeedSha256 does not match"),
        f"a stale private seed hash must fail closed; stderr: {seed_result.stderr[:300]}",
    )


def test_missing_legacy_input_hashes_fail_closed(root: Path) -> None:
    score_a, _score_b, _frozen = build_fixture_scores(root)

    no_inputs = mutate(
        root,
        score_a,
        "score-a-no-benchmark-inputs.json",
        lambda report: report.pop("benchmarkInputs"),
    )
    result = analyze(no_inputs)
    check(
        fails_with(result, "carries no benchmarkInputs hashes"),
        f"a legacy score with no benchmarkInputs must fail closed; stderr: {result.stderr[:300]}",
    )

    partial = mutate(
        root,
        score_a,
        "score-a-partial-benchmark-inputs.json",
        lambda report: report.update(
            {
                "benchmarkInputs": {
                    "configSha256": report["benchmarkInputs"]["configSha256"],
                    "shadowSeedSha256": report["benchmarkInputs"]["shadowSeedSha256"],
                }
            }
        ),
    )
    partial_result = analyze(partial)
    check(
        fails_with(partial_result, "is missing benchmarkInputs.shadowTaskSha256"),
        f"a partially declared legacy identity must fail closed; stderr: {partial_result.stderr[:300]}",
    )

    compared = compare(no_inputs, score_a)
    check(
        fails_with(compared, "carries no benchmarkInputs hashes"),
        f"paired comparison must fail closed on a legacy score; stderr: {compared.stderr[:300]}",
    )


def test_score_view_identity_is_bound_to_issue_64(root: Path) -> None:
    """The JS analysis must accept only the score-view identity #64 declares."""
    score_a, score_b, frozen = build_fixture_scores(root)

    strict_report = analyze(score_a, "--source-score-manifest", str(frozen), "--score-view", "strict")
    check(strict_report.returncode == 0, "an explicitly requested declared view must be selectable")
    if strict_report.returncode == 0:
        selected = json.loads(strict_report.stdout)["scoreView"]
        check(selected["selected"] == "strict", "the requested view must be the selected view")
        check(
            selected["primaryScreeningView"] == "recoverable_anchored",
            "substituting the primary view must be recorded, not silent",
        )
        check(
            selected["substitutedPrimary"] is True,
            "a substituted primary view must be flagged in the report",
        )

    undeclared = analyze(score_a, "--score-view", "recoverable")
    check(
        fails_with(undeclared, "is not a declared issue #64 view"),
        f"an undeclared view name must fail closed; stderr: {undeclared.stderr[:300]}",
    )

    version_drift = mutate(
        root,
        score_a,
        "score-a-view-version-drift.json",
        lambda report: report["scoreView"].update(
            {"parseViewContractVersion": "strict-recoverable-choice-views-v2"}
        ),
    )
    check(
        fails_with(analyze(version_drift), "declares contract version"),
        "a drifted #64 contract version must fail closed",
    )

    metric_drift = mutate(
        root,
        score_a,
        "score-a-view-metric-drift.json",
        lambda report: report["scoreView"]["metricKeys"].update({"strict": "strictAccuracy"}),
    )
    check(
        fails_with(analyze(metric_drift), "publishes strictAccuracyFixedDenominator"),
        "a renamed #64 metric key must fail closed",
    )

    contract_drift = mutate(
        root,
        score_a,
        "score-a-view-contract-drift.json",
        lambda report: report["scoreView"].update({"contractSha256": "e" * 64}),
    )
    check(
        fails_with(analyze(contract_drift), "score-view contract english_core_choice_views.py is"),
        "drifted #64 contract bytes must fail closed",
    )

    task_drift = mutate(
        root,
        score_a,
        "score-a-view-task-drift.json",
        lambda report: report["scoreView"].update({"taskFileSha256": "f" * 64}),
    )
    check(
        fails_with(analyze(task_drift), "score view measured"),
        "a score view measured over different task bytes must fail closed",
    )

    strict_b = mutate(
        root,
        score_b,
        "score-b-strict-view.json",
        lambda report: report["scoreView"].update(
            {"selected": "strict", "primaryScreeningView": "strict"}
        ),
    )
    cross_view = compare(score_a, strict_b, "--source-score-manifest", str(frozen))
    check(
        fails_with(cross_view, "Cannot form a headline comparison across score views"),
        f"headline comparison must refuse mixed views; stderr: {cross_view.stderr[:300]}",
    )


def test_paired_comparison_binds_both_scores(root: Path) -> None:
    score_a, score_b, frozen = build_fixture_scores(root)
    result = compare(score_a, score_b, "--source-score-manifest", str(frozen))
    check(result.returncode == 0, f"matching paired comparison must run; stderr: {result.stderr[:400]}")
    if result.returncode != 0:
        return
    report = json.loads(result.stdout)
    check(report["completeForHeadlineComparison"] is True, "matched fixtures must complete the comparison")
    check(
        report["compositeComparison"]["productWeightedDeltaAminusB100"] == 20.0,
        "the fixture delta must come from the snapshot weights, not a re-derived scale",
    )
    check(
        len(report["provenance"]["frozenScoreManifest"]["verifiedScoreFiles"]) == 2,
        "the frozen manifest must bind both source score files",
    )
    check(
        report["provenance"]["scoreView"]["identicalAcrossBothScores"] is True,
        "paired provenance must record that both scores declare the same view",
    )
    check(
        report["provenance"]["benchmarkSnapshot"]["identicalAcrossBothScores"] is True,
        "paired provenance must record that both scores declare the same benchmark inputs",
    )
    check(
        report["provenance"]["bootstrap"]["iterations"] == report["bootstrapIterations"],
        "paired provenance bootstrap iterations must match the report",
    )
    check(
        report["provenance"]["analysis"]["sha256"] == sha256_file(COMPARE),
        "paired provenance must record the comparison script hash",
    )


def main() -> int:
    ensure_snapshot()
    workspace = Path(tempfile.mkdtemp(prefix="english-core-snapshot-provenance-"))
    try:
        for test in (
            test_current_fixture_fully_analyzes,
            test_tampered_source_score_is_rejected,
            test_stale_config_and_seed_are_rejected,
            test_missing_legacy_input_hashes_fail_closed,
            test_score_view_identity_is_bound_to_issue_64,
            test_paired_comparison_binds_both_scores,
        ):
            test(workspace)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} checks failed", file=sys.stderr)
        for failure in FAILURES:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {CHECKS} snapshot-provenance checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
