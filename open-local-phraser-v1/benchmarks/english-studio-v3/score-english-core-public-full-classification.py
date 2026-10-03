"""Score the full-distribution prompted WiC / CoLA / PAWS lane.

Usage:
    python score-english-core-public-full-classification.py result.json

Important:
- This is prompted zero-shot classification on the benchmark distribution.
- It is not identical to a supervised benchmark-native model adaptation.
- CoLA reports MCC only when every item has a valid class prediction; invalid or
  missing outputs are never silently dropped.
- The scorer binds itself to the exact generated task/answer files by SHA-256 and
  rejects duplicate/extra outputs rather than silently taking the last record.

Issue #64: like public-fast, this prompted lane publishes strict letter-only and
recoverable anchored accuracy as two separate frozen views over one fixed
denominator. The per-item class predictions used for MCC/F1/accuracy come from the
recoverable anchored view, and the report names that explicitly; the strict view
is published alongside it and never silently substituted.

Issue #67: `--promotion` is a fail-closed source-provenance gate. It requires the
manifest's current `sourceContractVersion`, `promotionEligible`, and a clean
`source_manifest_gate_report` verdict, plus a preparation receipt that binds the
exact task/answer/manifest/source-manifest/tree identities this scorer hashed.
Exploratory scoring (no `--promotion`) applies none of those gates and always
reports `promotionScored: false`, so an exploratory score can never be mistaken
for promotion evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from english_core_choice_parser import allowed_choices_from_task, normalize_allowed_choices
from english_core_choice_views import (
    PRIMARY_SCREENING_VIEW,
    run_runtime_qualification,
    score_choice_views,
    score_view_contract,
    summarize_choice_views,
    with_score_view,
)
from english_core_public_sources import (
    SOURCE_CONTRACT_VERSION,
    SOURCE_MANIFEST_FILENAME,
    load_frozen_source_manifest,
    protocol_overrides,
    source_manifest_gate_report,
)
from english_core_result_contract import validate_result

HERE = Path(__file__).resolve().parent
CONTRACT = HERE / "english_core_choice_views.py"
TASKS = HERE / "english-core-public-full-classification.jsonl"
ANSWERS = HERE / "english-core-public-full-classification.answers.json"
MANIFEST = HERE / "english-core-public-full-classification.manifest.json"
SOURCES_CONFIG = HERE / SOURCE_MANIFEST_FILENAME
#: Written by ``prepare-english-core-public-full.py``. The scorer never creates
#: it; promotion scoring refuses to run without a verified one.
DEFAULT_PREPARATION_RECEIPT = HERE / "english-core-public-full-classification.preparation.json"

#: Must match ``prepare-english-core-public-full.py``'s receipt contract. It is
#: restated rather than imported so a changed preparation script becomes a loud
#: contract break here instead of silently widening what this scorer accepts.
RECEIPT_SCHEMA = "pari.english-core.public-full-preparation-receipt"
RECEIPT_VERSION = 1
RECEIPT_PROTOCOL_VERSION = f"pari.english-core.public-full-finalist-{SOURCE_CONTRACT_VERSION}"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def confusion(gold: list[int], pred: list[int]) -> dict[str, int]:
    tp = sum(1 for g, p in zip(gold, pred) if g == 1 and p == 1)
    tn = sum(1 for g, p in zip(gold, pred) if g == 0 and p == 0)
    fp = sum(1 for g, p in zip(gold, pred) if g == 0 and p == 1)
    fn = sum(1 for g, p in zip(gold, pred) if g == 1 and p == 0)
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def mcc_sklearn_convention(cm: dict[str, int]) -> float:
    """Binary MCC with the zero-denominator convention used by sklearn.

    GLUE/CoLA tooling commonly delegates to sklearn.metrics.matthews_corrcoef.
    Scikit-learn returns 0.0 for degenerate constant-class predictions where the
    denominator is zero. We reproduce that convention without adding a runtime
    sklearn dependency to this scorer.
    """
    tp, tn, fp, fn = cm["tp"], cm["tn"], cm["fp"], cm["fn"]
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denom == 0:
        return 0.0
    return (tp * tn - fp * fn) / denom


def binary_metrics(gold: list[int], pred: list[int]) -> dict:
    cm = confusion(gold, pred)
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    correct = sum(int(g == p) for g, p in zip(gold, pred))
    return {
        "cases": len(gold),
        "accuracy": round(correct / len(gold), 6) if gold else None,
        "accuracyWilson95": wilson_interval(correct, len(gold)),
        "mcc": round(mcc_sklearn_convention(cm), 6) if gold else None,
        "precisionPositive": None if precision is None else round(precision, 6),
        "recallPositive": None if recall is None else round(recall, 6),
        "f1Positive": None if f1 is None else round(f1, 6),
        "confusion": cm,
        "goldLabelCounts": dict(sorted(Counter(gold).items())),
        "predictedLabelCounts": dict(sorted(Counter(pred).items())),
    }


def gate_findings_for(manifest: dict, *, promotion: bool) -> dict:
    """Exploratory findings only, so a non-promotion score states why it is not
    promotion evidence instead of silently looking clean (#67)."""
    if not promotion:
        errors, warnings = source_manifest_gate_report(
            manifest.get("sources"),
            manifest.get("resolvedDatasetFingerprints"),
            promotion=False,
            overrides=_exploratory_overrides(),
        )
        return {"errors": errors, "warnings": warnings}
    return {"errors": [], "warnings": []}


def _exploratory_overrides() -> dict:
    """Reviewed-override declarations, when the frozen source config is present.

    A missing or unreadable config must not crash an exploratory score, so the
    helper degrades to no overrides; that only makes the findings stricter.
    """
    if not SOURCES_CONFIG.is_file():
        return {}
    try:
        return protocol_overrides(load_frozen_source_manifest(SOURCES_CONFIG))
    except (OSError, ValueError):
        return {}


def require_promotion_source_gate(manifest: dict, *, receipt_path: Path) -> dict:
    """Fail closed unless the manifest and its preparation receipt qualify (#67).

    Returns the verified receipt provenance block that is copied into the score
    artifact's ``inputs`` so #65 analysis can bind the finalist lane. Every
    refusal raises ``SystemExit``; there is no partial promotion.
    """
    contract_version = manifest.get("sourceContractVersion")
    if contract_version != SOURCE_CONTRACT_VERSION:
        raise SystemExit(
            f"Public-full manifest source contract {contract_version!r} is not "
            f"understood by this scorer (expected {SOURCE_CONTRACT_VERSION})"
        )
    if not manifest.get("promotionEligible"):
        raise SystemExit(
            "Public-full promotion scoring requires a promotion-eligible manifest; "
            "this build is exploratory and its gate findings are: "
            + json.dumps(
                (manifest.get("promotion") or {}).get("gateErrors", [])
                + (manifest.get("promotion") or {}).get("gateWarnings", [])
            )
        )
    if not SOURCES_CONFIG.is_file():
        raise SystemExit(
            f"Promotion scoring needs the versioned source manifest {SOURCES_CONFIG.name}; it is missing."
        )
    sources_config = load_frozen_source_manifest(SOURCES_CONFIG)
    errors, warnings = source_manifest_gate_report(
        manifest.get("sources"),
        manifest.get("resolvedDatasetFingerprints"),
        promotion=True,
        overrides=protocol_overrides(sources_config),
    )
    if errors or warnings:
        raise SystemExit(
            "Public-full promotion scoring refused; source provenance gate failed:\n- "
            + "\n- ".join(errors + warnings)
        )
    return _verified_preparation_receipt(manifest, sources_config, receipt_path=receipt_path)


def _verified_preparation_receipt(
    manifest: dict, sources_config: dict, *, receipt_path: Path
) -> dict:
    """Verify the preparation receipt binds the exact artifacts being scored.

    The receipt is not trusted on its own: its task, answer, and manifest hashes
    are recomputed against the files this scorer just loaded, its source-manifest
    hash is recomputed against the frozen config, and its frozen source
    identities must match the manifest the gate accepted.
    """
    receipt_path = Path(receipt_path).resolve()
    if not receipt_path.is_file():
        raise SystemExit(
            "Public-full promotion scoring requires a verified preparation receipt at "
            f"{receipt_path}; run prepare-english-core-public-full.py first. A task-file "
            "hash match alone is never promotion evidence."
        )
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("version") != RECEIPT_VERSION:
        raise SystemExit(
            f"Preparation receipt {receipt_path.name} is not the expected "
            f"{RECEIPT_SCHEMA} v{RECEIPT_VERSION} contract"
        )
    if receipt.get("protocolVersion") != RECEIPT_PROTOCOL_VERSION:
        raise SystemExit(
            f"Preparation receipt protocolVersion {receipt.get('protocolVersion')!r} is "
            f"not {RECEIPT_PROTOCOL_VERSION!r}"
        )
    if receipt.get("sourceContractVersion") != SOURCE_CONTRACT_VERSION:
        raise SystemExit(
            "Preparation receipt source contract "
            f"{receipt.get('sourceContractVersion')!r} is not understood by this scorer "
            f"(expected {SOURCE_CONTRACT_VERSION})"
        )
    if not receipt.get("promotionEligible"):
        raise SystemExit(
            "Preparation receipt is not promotion-eligible; its blockers are: "
            + json.dumps(receipt.get("promotionBlockers", []))
        )

    failures: list[str] = []
    files = receipt.get("files")
    if not isinstance(files, dict):
        raise SystemExit("Preparation receipt does not bind the prepared files")
    expected_hashes = {TASKS.name: sha256(TASKS), ANSWERS.name: sha256(ANSWERS), MANIFEST.name: sha256(MANIFEST)}
    for name, digest in expected_hashes.items():
        recorded = (files.get(name) or {}).get("sha256")
        if recorded != digest:
            failures.append(
                f"{name} sha256 {recorded!r} does not match the scored bytes {digest!r}"
            )
    if receipt.get("manifestSha256") != expected_hashes[MANIFEST.name]:
        failures.append(
            f"receipt manifestSha256 {receipt.get('manifestSha256')!r} does not match "
            f"the scored manifest {expected_hashes[MANIFEST.name]!r}"
        )

    frozen = receipt.get("frozenSources") or {}
    if frozen.get("file") != SOURCES_CONFIG.name:
        failures.append(
            f"receipt frozenSources file {frozen.get('file')!r} is not {SOURCES_CONFIG.name!r}"
        )
    elif frozen.get("sha256") != sha256(SOURCES_CONFIG):
        failures.append(
            f"receipt frozenSources sha256 {frozen.get('sha256')!r} does not match "
            f"{SOURCES_CONFIG.name}"
        )
    receipt_sources = frozen.get("sources")
    manifest_sources = manifest.get("sources") or {}
    for name, expected in (sources_config.get("sources") or {}).items():
        recorded = (receipt_sources or {}).get(name) or {}
        for field in ("dataset", "config", "split", "resolvedRevision"):
            if recorded.get(field) != expected.get(field):
                failures.append(
                    f"receipt frozenSources[{name}].{field} {recorded.get(field)!r} does not "
                    f"match the frozen source manifest {expected.get(field)!r}"
                )
            if (manifest_sources.get(name) or {}).get(field) != expected.get(field):
                failures.append(
                    f"scored manifest sources[{name}].{field} "
                    f"{(manifest_sources.get(name) or {}).get(field)!r} does not match "
                    f"the receipted frozen source {expected.get(field)!r}"
                )

    tree = receipt.get("benchmarkTree") or {}
    if not tree.get("promotionEligible"):
        failures.append("receipt benchmarkTree is not promotion-eligible")
    if not (tree.get("head") and tree.get("tree")):
        failures.append("receipt benchmarkTree does not bind both a head and a tree identity")
    if (receipt.get("isolatedDataEnvironment") or {}).get("dependencyLock", {}).get("state") != "verified":
        failures.append("receipt does not bind a verified data-preparation lock")

    if failures:
        raise SystemExit(
            "Public-full promotion scoring refused; the preparation receipt does not bind "
            "the artifacts being scored:\n- " + "\n- ".join(failures)
        )
    return {
        "path": str(receipt_path),
        "sha256": sha256(receipt_path),
        "protocolVersion": receipt["protocolVersion"],
        "promotionEligible": receipt["promotionEligible"],
        "benchmarkRevision": receipt.get("benchmarkRevision"),
        "benchmarkTree": tree,
        "files": files,
        "manifestSha256": receipt["manifestSha256"],
        "orderedTaskIdsSha256": receipt.get("orderedTaskIdsSha256"),
        "frozenSources": frozen,
        "isolatedDataEnvironment": receipt.get("isolatedDataEnvironment"),
        "laneSeparation": receipt.get("laneSeparation"),
    }


def main() -> None:
    flags = {arg for arg in sys.argv[1:] if arg.startswith("--") and "=" not in arg}
    valued = {arg.split("=", 1)[0] for arg in sys.argv[1:] if arg.startswith("--") and "=" in arg}
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    receipt_flag = next(
        (arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--preparation-receipt=")), None
    )
    known = {"--promotion", "--compat-legacy-v0", "--preparation-receipt"}
    if len(paths) != 1 or (flags | valued) - known:
        raise SystemExit(
            "Usage: python score-english-core-public-full-classification.py <result.json> "
            "[--promotion] [--compat-legacy-v0] [--preparation-receipt=PATH]"
        )
    promotion = "--promotion" in flags
    receipt_path = Path(receipt_flag).resolve() if receipt_flag else DEFAULT_PREPARATION_RECEIPT
    if not TASKS.exists() or not ANSWERS.exists() or not MANIFEST.exists():
        raise SystemExit("Build the full classification tasks first; task, answer, and manifest files are required.")

    result_path = Path(paths[0]).resolve()
    validation = validate_result(result_path, promotion=promotion, compat_legacy_v0="--compat-legacy-v0" in flags)
    run = json.loads(result_path.read_text())
    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
    answer_file = json.loads(ANSWERS.read_text())
    answer_data = answer_file["answers"]
    manifest = json.loads(MANIFEST.read_text())

    task_ids = [task["id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise SystemExit("Public-full task file contains duplicate IDs")
    if set(answer_data) != set(task_ids):
        raise SystemExit("Public-full answer keys do not exactly match task IDs")
    if int(manifest.get("cases", -1)) != len(tasks):
        raise SystemExit("Public-full manifest case count does not match task file")

    # Issue #67: the source-provenance gate runs before any metric is computed
    # and before the task-file hash is trusted, so an exploratory build's hash
    # match can never upgrade it into promotion evidence.
    preparation_receipt: dict | None = None
    if promotion:
        preparation_receipt = require_promotion_source_gate(manifest, receipt_path=receipt_path)
    else:
        manifest_gate_findings = gate_findings_for(manifest, promotion=False)

    expected_task_hash = sha256(TASKS)
    run_task_hash = run.get("taskFileSha256")
    if run_task_hash != expected_task_hash:
        raise SystemExit("Result taskFileSha256 does not match english-core-public-full-classification.jsonl")
    if run.get("taskCount") != len(tasks):
        raise SystemExit("Result taskCount does not match public-full task count")

    run_outputs = run.get("outputs", [])
    if not isinstance(run_outputs, list):
        raise SystemExit("Result outputs is not an array")
    output_ids = [row.get("id") for row in run_outputs if isinstance(row, dict)]
    if len(output_ids) != len(run_outputs):
        raise SystemExit("Result contains a non-object output row")
    if any(not value for value in output_ids):
        raise SystemExit("Result contains an output without an ID")
    if len(output_ids) != len(set(output_ids)):
        raise SystemExit("Result contains duplicate output IDs")
    extra = sorted(set(output_ids) - set(task_ids))
    if extra:
        raise SystemExit(f"Result contains {len(extra)} IDs not present in the public-full task file")
    outputs = {row["id"]: row for row in run_outputs}

    by_source: dict[str, list[dict]] = defaultdict(list)
    detail = []
    runtime = run_runtime_qualification(run)

    for task in tasks:
        meta = answer_data[task["id"]]
        got = outputs.get(task["id"])
        # The frozen allowed set comes from the task's model-visible
        # allowedChoices when present. Older full-classification task files do not
        # carry it, and their rendered prompt has exactly one option per entry in
        # the frozen answer metadata's letter map, so the letter set is derived
        # from that map. It is task metadata, never the gold answer.
        allowed_choices = allowed_choices_from_task(task)
        if allowed_choices is None:
            letter_map = meta.get("labelByLetter")
            if not isinstance(letter_map, dict) or not letter_map:
                raise SystemExit(
                    f"Full-classification task {task['id']} exposes neither allowedChoices "
                    "nor a letter map, so the issue #64 strict/recoverable views cannot be derived."
                )
            allowed_choices = normalize_allowed_choices(sorted(letter_map))
        expected_letter = meta["letter"]
        if expected_letter not in allowed_choices:
            raise SystemExit(
                f"Answer letter {expected_letter} for {task['id']} is outside its frozen allowed set"
            )
        views = score_choice_views(
            got.get("output", "") if got else "",
            task=task,
            allowed_choices=allowed_choices,
            gold=expected_letter,
            finish_reason=got.get("finishReason") if got else None,
            truncated=bool(got.get("truncated")) if got else False,
            missing=got is None,
            runtime_unqualified=not runtime["runtimeQualified"],
        )
        predicted_letter = views["recoverableParsedChoice"]
        strict_letter = views["strictParsedChoice"]
        predicted_label = None
        if predicted_letter is not None:
            predicted_label = meta["labelByLetter"].get(predicted_letter)
        # A runtime-unqualified run is infrastructure state, not English evidence
        # (#28/#64): no item from it becomes a class prediction or a zero.
        valid = predicted_label in (0, 1) and runtime["runtimeQualified"]
        gold_label = int(meta["goldLabel"])
        correct = bool(valid and predicted_label == gold_label)
        strict_predicted_label = None
        if strict_letter is not None:
            strict_predicted_label = meta["labelByLetter"].get(strict_letter)
        row = {
            "id": task["id"],
            "source": task["source"],
            "dimension": task["dimension"],
            "goldLabel": gold_label,
            "expectedLetter": expected_letter,
            "allowedChoices": list(allowed_choices),
            "predictedLetter": predicted_letter,
            "predictedLabel": predicted_label,
            "correct": correct,
            "status": "scored" if valid else ("missing" if got is None else "invalid_output"),
            # Issue #64 per-item views. The class prediction above is the
            # recoverable anchored view; the strict view is published beside it
            # and never merged into it.
            "choiceViews": views,
            "strictParsedChoice": strict_letter,
            "recoverableParsedChoice": predicted_letter,
            "strictPredictedLabel": strict_predicted_label,
            "strictProtocolValid": views["strictProtocolValid"],
            "recoverableProtocolValid": views["recoverableProtocolValid"],
            "strictCorrect": views["strictCorrect"],
            "recoverableCorrect": views["recoverableCorrect"],
            "viewsDisagree": views["viewsDisagree"],
            "outcome": views["outcome"],
        }
        detail.append(row)
        by_source[task["source"]].append(row)

    source_reports = {}
    for source, rows in sorted(by_source.items()):
        views = summarize_choice_views(rows)
        valid_rows = [row for row in rows if row["status"] == "scored"]
        correct_all = views["recoverableCorrectCount"]
        complete = len(valid_rows) == len(rows)
        report = {
            "cases": len(rows),
            # Named separately so the fixed denominator is never inferred from
            # the raw case count.
            "fixedDenominator": views["fixedDenominator"],
            "excludedRuntimeUnqualified": views["excludedRuntimeUnqualified"],
            "choiceViews": views,
            "strictCorrect": views["strictCorrectCount"],
            "recoverableCorrect": views["recoverableCorrectCount"],
            "validPredictions": len(valid_rows),
            "validOutputCoverage": views["recoverableValidOutputCoverage"],
            "accuracyInvalidAsWrong": views["recoverableAccuracyFixedDenominator"],
            "accuracyInvalidAsWrongScoreView": PRIMARY_SCREENING_VIEW,
            "validOutputCoverageScoreView": PRIMARY_SCREENING_VIEW,
            "accuracyInvalidAsWrongWilson95": wilson_interval(correct_all, views["fixedDenominator"]),
            "completeForClassificationMetrics": complete,
        }
        if complete:
            gold = [int(row["goldLabel"]) for row in rows]
            pred = [int(row["predictedLabel"]) for row in rows]
            report.update(binary_metrics(gold, pred))
        else:
            report["classificationMetrics"] = None
            report["reason"] = "MCC/F1/native-distribution classification metrics withheld because one or more outputs are missing/invalid; invalid cases are not silently excluded."
        source_reports[source] = report

    headline = {
        "WiC": {"metric": "accuracy", "value": source_reports.get("WiC", {}).get("accuracy")},
        "CoLA": {"metric": "Matthews correlation coefficient", "value": source_reports.get("CoLA", {}).get("mcc")},
        "PAWS": {"metric": "accuracy", "value": source_reports.get("PAWS", {}).get("accuracy")},
    }
    overall_views = summarize_choice_views(detail)

    report = {
        "version": 4,
        "schemaVersion": 1,
        "artifactType": "pari.english-core.public-full-classification-score",
        "inputResultSchema": validation.get("schemaValidation"),
        "runId": run.get("runId"),
        "model": run.get("model"),
        "adaptation": "zero-shot prompted classification on full locally scoreable validation distributions",
        # Mirrors the shadow scorer's top-level task binding so a #64 score view
        # can be reconciled against the exact model-visible task bytes.
        "taskFile": str(TASKS),
        "taskFileSha256": expected_task_hash,
        "runtimeQualification": runtime,
        # Issue #67: false unless every promotion gate above cleared. An
        # exploratory score therefore never reads as promotion evidence.
        "promotionScored": promotion,
        # Exploratory mode still publishes why the build is not promotion
        # evidence, so it can never look clean by omission.
        "exploratorySourceGateFindings": None if promotion else manifest_gate_findings,
        "excludedRuntimeUnqualified": overall_views["excludedRuntimeUnqualified"],
        "fixedDenominator": overall_views["fixedDenominator"],
        "cases": len(detail),
        "choiceViews": overall_views,
        "strictCorrect": overall_views["strictCorrectCount"],
        "recoverableCorrect": overall_views["recoverableCorrectCount"],
        "inputs": {
            "resultFile": str(result_path),
            "resultFileSha256": sha256(result_path),
            "taskFile": str(TASKS),
            "taskFileSha256": expected_task_hash,
            "answerFileSha256": sha256(ANSWERS),
            "manifestSha256": sha256(MANIFEST),
            "manifestSources": manifest.get("sources"),
            "resolvedDatasetFingerprints": manifest.get("resolvedDatasetFingerprints"),
            "datasetsLibraryVersion": manifest.get("datasetsLibraryVersion"),
            # Issue #67 provenance so #65 analysis can bind the finalist lane to
            # the exact prepared bytes and source identity that were gated.
            "sourceContractVersion": manifest.get("sourceContractVersion"),
            "promotionEligible": manifest.get("promotionEligible"),
            "preparationReceipt": preparation_receipt
            or {
                "path": str(receipt_path) if receipt_path.is_file() else None,
                "sha256": sha256(receipt_path) if receipt_path.is_file() else None,
                "verified": False,
                "note": (
                    "exploratory scoring does not verify or require a preparation receipt; "
                    "this build is not promotion evidence"
                ),
            },
        },
        "headline": headline,
        "bySource": source_reports,
        "notes": [
            "This lane preserves the public validation distribution; it is separate from Pari's balanced public-fast screen.",
            "The scorer requires an exact task-file hash/count match and rejects duplicate or extra output IDs before computing metrics.",
            "Missing/invalid expected outputs remain visible as coverage failures and prevent MCC/F1/native-distribution headline metrics from being computed; they are never silently dropped.",
            "Issue #64: strictAccuracyFixedDenominator and recoverableAccuracyFixedDenominator are separate frozen views over one fixed denominator. The class predictions behind accuracy/MCC/F1 come from the recoverable anchored view, and the report names that explicitly.",
            "The shared choice parser accepts only unambiguous letter forms such as A, A., Answer: A, The answer is A, or Option A; free-form prose remains invalid.",
            "A runtime-unqualified or short run is excluded from the correctness denominator and reported under runtimeQualification instead of becoming an English zero.",
            "Prompted zero-shot classification is not identical to the supervised model adaptation used in the original benchmark literature.",
            "CoLA headline reporting uses the standard GLUE MCC convention: Hugging Face GLUE and other established GLUE tooling delegate to sklearn.metrics.matthews_corrcoef; zero-denominator/constant-prediction cases therefore map to MCC 0.0 rather than an undefined score.",
            "Balanced-screen accuracy must not be called an official CoLA score.",
            "Issue #67: promotionScored is true only when --promotion cleared the sourceContractVersion, promotionEligible, source-provenance gate, and preparation-receipt checks. Without that flag this score is exploratory and is never promotion evidence.",
            "Report exact prompt/adaptation/model/runtime/source provenance alongside these metrics."
        ],
        "researchReferences": {
            "WiC": "https://aclanthology.org/N19-1128/",
            "CoLA": "https://aclanthology.org/Q19-1040/",
            "PAWS": "https://aclanthology.org/N19-1131/",
            "GLUE_metric_implementation": "https://github.com/huggingface/evaluate/blob/main/metrics/glue/glue.py"
        },
        "detail": detail,
    }
    with_score_view(
        report,
        score_view_contract(
            contract_path=CONTRACT,
            task_file_sha256=expected_task_hash,
            task_manifest_sha256=sha256(MANIFEST),
            source_result_sha256=sha256(result_path),
            source_run_id=run.get("runId"),
        ),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
