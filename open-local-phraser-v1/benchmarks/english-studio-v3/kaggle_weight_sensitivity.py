#!/usr/bin/env python3
"""Weight-sensitivity and paired-uncertainty analysis for issue #56.

This module owns only the analysis side of issue #56. It consumes score
reports already produced by the frozen #17 machinery (``score-english-core.mjs``
version 8+ output) plus the frozen weight grid in
``kaggle-weight-sensitivity-grid.json``. It never regenerates prompts, never
opens raw model outputs, never reads the private gold key, and never invents a
winner.

It deliberately fails closed:

* a candidate whose benchmark-input hashes, task-file hash, or per-dimension
  coverage do not line up with the frozen contender set is excluded from the
  paired headline and reported as ``withheld`` with a reason;
* comparisons whose paired bootstrap interval spans zero stay ``inconclusive``;
* a ranking that changes across the frozen grid is reported as weight-dependent
  ordering rather than a winner.

Usage:

    python3 kaggle_weight_sensitivity.py --contenders contenders.json > out.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
GRID_PATH = HERE / "kaggle-weight-sensitivity-grid.json"
CONFIG_PATH = HERE / "english-core-config.json"
SEED_PATH = HERE / "english-core-shadow.seed.json"
RESULT_SCHEMA_VERSION = 1
RESULT_SCHEMA_SHA256 = hashlib.sha256((HERE / "english-core-result-schema.json").read_bytes()).hexdigest()

MIN_ITERATIONS = 1000
REQUIRED_INPUT_KEYS = (
    "configSha256",
    "shadowSeedSha256",
    "shadowTaskSha256",
    "shadowManifestSha256",
    "generativeMetricContractSha256",
)


# --------------------------------------------------------------------------- #
# hashing / deterministic RNG
# --------------------------------------------------------------------------- #


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Xorshift:
    """xorshift32, the same convention the #17 JS comparators already use."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF
        if self.state == 0:
            raise ValueError("bootstrap seed must be non-zero")

    def next_float(self) -> float:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state / 4294967296.0

    def sample(self, rows: list, count: int | None = None) -> list:
        n = len(rows)
        if n == 0:
            return []
        total = n if count is None else count
        return [rows[int(self.next_float() * n) % n] for _ in range(total)]


def _percentile(sorted_values: list[float], q: float) -> float:
    idx = (len(sorted_values) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    if lo == hi:
        return sorted_values[int(idx)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


def ci95(values: list[float]) -> list[float] | None:
    if not values:
        return None
    s = sorted(values)
    return [round(float(_percentile(s, 0.025)), 3), round(float(_percentile(s, 0.975)), 3)]


def conclusion_from(interval: list[float] | None) -> str:
    if not interval:
        return "withheld"
    if interval[0] > 0:
        return "A_higher_on_this_set"
    if interval[1] < 0:
        return "B_higher_on_this_set"
    return "inconclusive"


# --------------------------------------------------------------------------- #
# frozen weight grid
# --------------------------------------------------------------------------- #


def load_grid() -> dict:
    grid = json.loads(GRID_PATH.read_text(encoding="utf-8"))
    validate_grid(grid)
    return grid


def validate_grid(grid: dict) -> None:
    if grid.get("gridVersion") != 1:
        raise ValueError("unsupported weight-grid version")
    dimensions = grid["dimensionOrder"]
    if len(set(dimensions)) != len(dimensions):
        raise ValueError("grid dimensionOrder contains duplicates")
    names = list(grid["vectors"])
    if names[:2] != ["product", "equal_weight"]:
        raise ValueError("grid must lead with the product and equal-weight vectors")
    for name, spec in grid["vectors"].items():
        weights = spec["weights"]
        if set(weights) != set(dimensions):
            raise ValueError(f"grid vector {name} does not cover exactly the declared dimensions")
        total = sum(weights.values())
        if abs(total - 100.0) > 1e-6:
            raise ValueError(f"grid vector {name} sums to {total}, not 100")
    loo = grid.get("leaveOneOut") or {}
    if loo.get("enabled") and loo.get("sourceVector") != "product":
        raise ValueError("leave-one-out must derive from the product vector")


def normalized_vectors(grid: dict) -> dict:
    """Frozen vectors plus deterministic leave-one-out variants."""
    vectors = {name: dict(spec["weights"]) for name, spec in grid["vectors"].items()}
    loo = grid.get("leaveOneOut") or {}
    if loo.get("enabled"):
        base = vectors[loo["sourceVector"]]
        for dropped in sorted(base):
            remaining = {d: w for d, w in base.items() if d != dropped}
            total = sum(remaining.values())
            if total <= 0:
                raise ValueError(f"leave-one-out of {dropped} leaves no weight mass")
            vectors[f"leave_out_{dropped}"] = {
                d: round(w * 100.0 / total, 9) for d, w in remaining.items()
            }
    return vectors


def composite100(dimension_scores: dict[str, float], weights: dict[str, float]) -> float:
    return sum(dimension_scores[d] * (weights[d] / 100.0) for d in weights)


# --------------------------------------------------------------------------- #
# contender-set loading and fail-closed validation
# --------------------------------------------------------------------------- #


def load_contenders(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    contenders = raw.get("contenders")
    if not isinstance(contenders, list) or len(contenders) < 2:
        raise ValueError("contenders file must list at least two contenders")
    ids = [c.get("id") for c in contenders]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("contender ids must be present and unique")
    return raw


def resolve_score_path(entry: dict, base: Path) -> Path:
    p = Path(entry["scorePath"])
    return p if p.is_absolute() else (base / p)


def load_score(entry: dict, base: Path, dimensions: list[str]) -> dict:
    """Load one score report and return a provenance/verdict bundle.

    Only the score report is read. Raw model outputs and the private gold key
    are never opened here.
    """
    path = resolve_score_path(entry, base)
    if not path.is_file():
        return {
            "scorePath": str(path),
            "available": False,
            "withheldReasons": [f"score report not found: {path.name}"],
        }
    score = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if score.get("schemaVersion") != 1 or score.get("artifactType") != "pari.english-core.shadow-score":
        problems.append("score report is not a supported versioned English Core shadow-score artifact")
    input_schema = score.get("inputResultSchema")
    if not isinstance(input_schema, dict):
        problems.append("score report is missing inputResultSchema validation provenance")
    elif input_schema.get("resultSchemaVersion") != RESULT_SCHEMA_VERSION or input_schema.get("schemaSha256") != RESULT_SCHEMA_SHA256:
        problems.append("score report was not validated against the current English Core result schema")
    elif input_schema.get("validationMode") != "promotion":
        problems.append("score report was not produced after promotion-mode result validation")

    declared = entry.get("expectedBenchmarkInputs") or {}
    inputs = score.get("benchmarkInputs") or {}
    for key in REQUIRED_INPUT_KEYS:
        if not inputs.get(key):
            problems.append(f"score report is missing benchmarkInputs.{key}")
        elif key in declared and declared[key] != inputs[key]:
            problems.append(f"benchmarkInputs.{key} does not match the frozen contender-set value")
    entry_task_sha = entry.get("taskFileSha256")
    if entry_task_sha and entry_task_sha != score.get("taskFileSha256"):
        problems.append("taskFileSha256 does not match the frozen contender-set value")
    if inputs.get("shadowTaskSha256") and score.get("taskFileSha256") != inputs["shadowTaskSha256"]:
        problems.append("score taskFileSha256 is not the canonical shadow task file")
    if entry.get("runtimeQualified") is False:
        problems.append("candidate is not runtime-qualified; it must not enter linguistic paired statistics")

    dimension_scores: dict[str, float] = {}
    coverage: dict[str, Any] = {}
    complete = score.get("complete") is True
    for d in dimensions:
        meta = (score.get("dimensionScores") or {}).get(d) or {}
        coverage[d] = {
            "cases": meta.get("cases"),
            "scored": meta.get("scored"),
            "missing": meta.get("missing"),
            "complete": meta.get("complete"),
        }
        if meta.get("complete") is not True or not isinstance(meta.get("score100"), (int, float)):
            complete = False
            problems.append(f"dimension {d} is not completely scored")
            continue
        expected = (entry.get("expectedDimensionCases") or {}).get(d)
        if expected is not None and meta.get("cases") != expected:
            complete = False
            problems.append(
                f"dimension {d} has {meta.get('cases')} cases but the frozen plan expected {expected}"
            )
        dimension_scores[d] = float(meta["score100"])

    return {
        "scorePath": str(path),
        "scoreSha256": sha256_file(path),
        "available": True,
        "runId": score.get("runId"),
        "model": score.get("model"),
        "benchmarkInputs": inputs,
        "taskFileSha256": score.get("taskFileSha256"),
        "inputResultSchema": input_schema,
        "headlineComplete": complete,
        "dimensionScores": dimension_scores,
        "coverage": coverage,
        "withheldReasons": problems,
    }


def shared_benchmark_inputs(loaded: list[dict]) -> tuple[dict | None, str | None]:
    """Common benchmark-input fingerprint across the usable contenders."""
    usable = [x for x in loaded if x.get("available") and not x["withheldReasons"]]
    if len(usable) < 2:
        return None, "fewer than two fully provenance-clean score reports"
    reference = usable[0]["benchmarkInputs"]
    for other in usable[1:]:
        for key in REQUIRED_INPUT_KEYS:
            if other["benchmarkInputs"].get(key) != reference.get(key):
                return None, f"contenders disagree on benchmarkInputs.{key}"
    return {k: reference.get(k) for k in REQUIRED_INPUT_KEYS}, None


# --------------------------------------------------------------------------- #
# paired comparison under one weight vector
# --------------------------------------------------------------------------- #


def paired_bootstrap(
    a_scores: dict[str, float],
    b_scores: dict[str, float],
    weights: dict[str, float],
    iterations: int,
    rng: Xorshift,
) -> dict:
    """Composite-difference bootstrap using a paired *dimension* resample.

    A score report exposes per-dimension aggregates, not per-item scores, so the
    paired resample here is over the seven aligned dimensions. That is a much
    coarser unit than the per-item paired bootstrap in
    ``compare-english-core-models.mjs`` and is labelled as such: it is a
    weight-grid sensitivity diagnostic, never a replacement for item-level
    paired inference.
    """
    dims = [d for d in weights if d in a_scores and d in b_scores]
    if len(dims) != len(weights):
        missing = sorted(set(weights) - set(dims))
        return {
            "pairedDimensions": len(dims),
            "deltaAminusB100": None,
            "pairedDimensionBootstrap95": None,
            "conclusion": "withheld",
            "withheldReason": f"missing paired dimension scores: {missing}",
        }
    boots = []
    for _ in range(iterations):
        sampled = rng.sample(dims, len(dims))
        da = {d: a_scores[d] for d in sampled}
        db = {d: b_scores[d] for d in sampled}
        # A dimension can be drawn more than once, so collapse the resample to
        # the drawn dimension set and renormalize its weights. That keeps every
        # bootstrap draw a valid weighted composite over exactly the dimensions
        # it sampled, instead of silently summing to less than 100 percent.
        drawn = {d: weights[d] for d in dims if d in set(sampled)}
        mass = sum(drawn.values())
        renormalized = {d: w * 100.0 / mass for d, w in drawn.items()}
        boots.append(composite100(da, renormalized) - composite100(db, renormalized))
    interval = ci95(boots)
    return {
        "pairedDimensions": len(dims),
        "deltaAminusB100": round(
            composite100(a_scores, weights) - composite100(b_scores, weights), 3
        ),
        "pairedDimensionBootstrap95": interval,
        "conclusion": conclusion_from(interval),
    }


def largest_single_dimension_contribution(
    a_scores: dict[str, float], b_scores: dict[str, float], weights: dict[str, float]
) -> dict | None:
    if not weights:
        return None
    contributions = {
        d: round((a_scores[d] - b_scores[d]) * (w / 100.0), 3) for d, w in weights.items()
    }
    top_dim, top_value = max(contributions.items(), key=lambda kv: abs(kv[1]))
    total = round(sum(contributions.values()), 3)
    return {
        "dimension": top_dim,
        "contribution100": top_value,
        "totalDelta100": total,
        "shareOfLead": round(abs(top_value) / abs(total), 3) if total else None,
    }


def leave_one_dimension_driver(
    a_scores: dict[str, float],
    b_scores: dict[str, float],
    product_weights: dict[str, float],
    loo_weights: dict[str, dict[str, float]],
) -> dict:
    """Report whether one dimension alone drives the product-weighted lead."""
    base = composite100(a_scores, product_weights) - composite100(b_scores, product_weights)
    flips = []
    for name in sorted(loo_weights):
        weights = loo_weights[name]
        delta = composite100(a_scores, weights) - composite100(b_scores, weights)
        if delta != 0 and (delta > 0) != (base > 0):
            flips.append(name)
    return {
        "productDeltaAminusB100": round(base, 3),
        "leaveOneOutSignFlips": flips,
        "leadSurvivesEveryLeaveOneOut": not flips,
        "largestSingleDimensionContribution": largest_single_dimension_contribution(
            a_scores, b_scores, product_weights
        ),
    }


def ranking_under(weights: dict[str, float], per_candidate: dict[str, dict[str, float]]) -> list[dict]:
    rows = [
        {"contender": cid, "composite100": round(composite100(scores, weights), 3)}
        for cid, scores in per_candidate.items()
    ]
    rows.sort(key=lambda r: (-r["composite100"], r["contender"]))
    for i, row in enumerate(rows):
        row["rank"] = i + 1
    return rows


# --------------------------------------------------------------------------- #
# report assembly
# --------------------------------------------------------------------------- #


def _withheld_report(
    reason: str, contender_file: Path, entries: list[dict], loaded: list[dict]
) -> dict:
    return {
        "version": 1,
        "artifactType": "pari.english-core.weight-sensitivity-report",
        "schemaVersion": 1,
        "issue": "56",
        "analysis": "weight-sensitivity",
        "status": "withheld",
        "withheldReason": reason,
        "weightGridSha256": sha256_file(GRID_PATH),
        "configSha256": sha256_file(CONFIG_PATH),
        "seedSha256": sha256_file(SEED_PATH),
        "contendersFile": contender_file.name,
        "contendersFileSha256": sha256_file(contender_file),
        "contenders": [
            {
                "id": e["id"],
                "available": b["available"],
                "inputResultSchema": b.get("inputResultSchema"),
                "withheldReasons": b["withheldReasons"],
            }
            for e, b in zip(entries, loaded)
        ],
        "claimRules": [
            "A withheld report is a blocker, not a negative result.",
            "Do not substitute partial overlap, a different benchmark state, or a "
            "hand-picked weight vector to make a ranking appear.",
        ],
    }


def build_report(contender_file: Path, iterations: int) -> dict:
    grid = load_grid()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    dimensions = list(grid["dimensionOrder"])
    config_weights = (config.get("composite") or {}).get("weights") or {}
    if set(config_weights) != set(dimensions):
        raise ValueError("grid dimensions do not match english-core-config.json composite weights")

    declared = load_contenders(contender_file)
    base_dir = contender_file.parent
    seed_hex = declared.get("bootstrapSeedHex") or grid["seeds"]["bootstrapSeedHex"]
    iterations = int(iterations or declared.get("iterations") or grid["defaultBootstrapIterations"])
    if iterations < MIN_ITERATIONS:
        raise ValueError(f"iterations must be >= {MIN_ITERATIONS}")

    entries = declared["contenders"]
    loaded = [load_score(e, base_dir, dimensions) for e in entries]

    per_candidate: dict[str, dict[str, float]] = {}
    excluded = []
    for entry, bundle in zip(entries, loaded):
        cid = entry["id"]
        if bundle["available"] and not bundle["withheldReasons"]:
            per_candidate[cid] = bundle["dimensionScores"]
        else:
            excluded.append(
                {
                    "contender": cid,
                    "reasons": bundle.get("withheldReasons", ["unavailable"]),
                }
            )

    shared_inputs, input_problem = shared_benchmark_inputs(loaded)
    if input_problem:
        return _withheld_report(
            f"shared benchmark identity unavailable: {input_problem}",
            contender_file,
            entries,
            loaded,
        )

    vectors = normalized_vectors(grid)
    loo_weights = {k: v for k, v in vectors.items() if k.startswith("leave_out_")}
    rankings = {name: ranking_under(w, per_candidate) for name, w in vectors.items()}

    leaders = {name: rows[0]["contender"] for name, rows in rankings.items()}
    orderings = {name: tuple(r["contender"] for r in rows) for name, rows in rankings.items()}
    leader_set = sorted(set(leaders.values()))

    pair_ids = sorted(per_candidate)[:2]
    a, b = pair_ids[0], pair_ids[1]
    rng = Xorshift(int(seed_hex, 16))
    paired_by_vector = {
        name: paired_bootstrap(per_candidate[a], per_candidate[b], weights, iterations, rng)
        for name, weights in vectors.items()
    }

    product_rows = ranking_under(vectors["product"], {a: per_candidate[a], b: per_candidate[b]})
    equal_rows = ranking_under(vectors["equal_weight"], {a: per_candidate[a], b: per_candidate[b]})
    driver = leave_one_dimension_driver(
        per_candidate[a], per_candidate[b], vectors["product"], loo_weights
    )

    product_conclusion = paired_by_vector["product"]["conclusion"]
    equal_conclusion = paired_by_vector["equal_weight"]["conclusion"]

    return {
        "version": 1,
        "artifactType": "pari.english-core.weight-sensitivity-report",
        "schemaVersion": 1,
        "issue": "56",
        "analysis": "weight-sensitivity",
        "status": "computed",
        "weightGridSha256": sha256_file(GRID_PATH),
        "configSha256": sha256_file(CONFIG_PATH),
        "seedSha256": sha256_file(SEED_PATH),
        "contendersFile": contender_file.name,
        "contendersFileSha256": sha256_file(contender_file),
        "bootstrapIterations": iterations,
        "bootstrapSeedHex": seed_hex,
        "sharedBenchmarkInputs": shared_inputs,
        "dimensions": dimensions,
        "contenders": [
            {
                "id": e["id"],
                "available": b["available"],
                "runId": b.get("runId"),
                "scorePath": b.get("scorePath"),
                "scoreSha256": b.get("scoreSha256"),
                "inputResultSchema": b.get("inputResultSchema"),
                "headlineComplete": b.get("headlineComplete"),
                "withheldReasons": b["withheldReasons"],
            }
            for e, b in zip(entries, loaded)
        ],
        "excluded": excluded,
        "rankings": rankings,
        "rankingStability": {
            "leaders": leaders,
            "distinctLeaders": leader_set,
            "leaderStableAcrossGrid": len(leader_set) == 1,
            "distinctOrderings": len(set(orderings.values())),
            "orderingStableAcrossGrid": len(set(orderings.values())) == 1,
            "note": (
                "A leader that changes across the frozen grid is weight-dependent ordering, "
                "not a winner. A stable leader still needs a paired interval excluding zero."
            ),
        },
        "pairedPair": f"{a}__vs__{b}",
        "pairedByVector": paired_by_vector,
        "productVsEqualWeights": {
            "productLeader": product_rows[0]["contender"],
            "equalWeightLeader": equal_rows[0]["contender"],
            "rankingFlipsUnderEqualWeights": product_rows[0]["contender"]
            != equal_rows[0]["contender"],
            "productPairedConclusion": product_conclusion,
            "equalWeightPairedConclusion": equal_conclusion,
            "note": (
                "A flip in paired conclusion between product and equal weights is the "
                "weight-sensitive trade-off this issue asks to surface, not a defect to average away."
            ),
        },
        "leaveOneDimensionDriver": driver,
        "claimRules": [
            "Only the frozen grid in kaggle-weight-sensitivity-grid.json is evaluated.",
            "No weight vector is added, dropped, or reweighted after seeing results.",
            "Any interval containing zero stays inconclusive; it is not a forced winner.",
            "A ranking flip across the grid is reported as weight-dependent ordering.",
            "The paired dimension bootstrap is a coarse sensitivity diagnostic; per-item "
            "paired inference remains compare-english-core-models.mjs on aligned items.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #56 weight-sensitivity analysis")
    parser.add_argument("--contenders", required=True, help="frozen contender-set JSON")
    parser.add_argument("--iterations", type=int, default=0, help="bootstrap iterations (>=1000)")
    args = parser.parse_args(argv)
    report = build_report(Path(args.contenders), args.iterations)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
