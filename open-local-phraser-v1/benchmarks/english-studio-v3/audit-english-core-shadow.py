"""Audit English Core shadow-set structure without using a model judge.

This is a *diagnostic*, not a quality metric. It flags structural risks for human
review: duplicate/near-duplicate wording, answer imbalance, repeated phenomena,
missing fields, and tiny phenomenon cells. It never auto-deletes an item or
claims semantic equivalence from token overlap.

Usage:
    python audit-english-core-shadow.py [english-core-shadow.seed.json]
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT = HERE / "english-core-shadow.seed.json"

STOP = {
    "a", "an", "the", "to", "of", "and", "or", "is", "are", "was", "were",
    "be", "been", "being", "in", "on", "at", "for", "with", "that", "this",
}


def normalize_tokens(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9']+", text.lower())
        if token not in STOP
    ]


def item_text(row: dict) -> str:
    fields = [
        "sentence", "sentenceA", "sentenceB", "source", "candidate", "text",
        "selection", "target"
    ]
    chunks: list[str] = []
    for field in fields:
        value = row.get(field)
        if isinstance(value, str):
            chunks.append(value)
    for field in ("choices", "sentences"):
        value = row.get(field)
        if isinstance(value, list):
            for x in value:
                if isinstance(x, str):
                    chunks.append(x)
                elif isinstance(x, list):
                    chunks.append(" ".join(map(str, x)))
    return " ".join(chunks)


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def normalized_answer(row: dict) -> str:
    answer = row.get("answer")
    if isinstance(answer, list):
        return json.dumps(answer, separators=(",", ":"))
    return str(answer)


def entropy(counts: Counter) -> float | None:
    n = sum(counts.values())
    if n <= 0 or len(counts) <= 1:
        return 0.0 if n else None
    h = 0.0
    for c in counts.values():
        p = c / n
        h -= p * math.log2(p)
    max_h = math.log2(len(counts))
    return h / max_h if max_h else 0.0


def main() -> None:
    path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT
    data = json.loads(path.read_text())
    rows = data.get("cases", [])
    if not rows:
        raise SystemExit("No cases found")

    ids = [row.get("id") for row in rows]
    duplicate_ids = sorted([k for k, v in Counter(ids).items() if v > 1])

    required_missing = []
    for row in rows:
        for field in ("id", "dimension", "task"):
            if not row.get(field):
                required_missing.append({"id": row.get("id"), "field": field})
        if row.get("dimension") != "generative_expression" and "answer" not in row:
            required_missing.append({"id": row.get("id"), "field": "answer"})

    by_dimension = defaultdict(list)
    by_phenomenon = Counter()
    answer_balance = defaultdict(Counter)
    task_counts = Counter()
    for row in rows:
        dim = row["dimension"]
        by_dimension[dim].append(row)
        by_phenomenon[f"{dim}::{row.get('phenomenon', 'unspecified')}"] += 1
        task_counts[f"{dim}::{row['task']}"] += 1
        if "answer" in row:
            answer_balance[f"{dim}::{row['task']}"][normalized_answer(row)] += 1

    # Lexical overlap is only a review flag. High overlap can be intentional in
    # minimal-pair benchmarks, so do not auto-fail or automatically remove items.
    overlap_flags = []
    for dim, dim_rows in by_dimension.items():
        for a, b in combinations(dim_rows, 2):
            ta = normalize_tokens(item_text(a))
            tb = normalize_tokens(item_text(b))
            score = jaccard(ta, tb)
            if score >= 0.72:
                overlap_flags.append({
                    "dimension": dim,
                    "idA": a["id"],
                    "idB": b["id"],
                    "tokenJaccard": round(score, 4),
                    "reviewOnly": True,
                })

    small_cells = [
        {"cell": key, "cases": count}
        for key, count in sorted(by_phenomenon.items())
        if count < 2
    ]

    balance_report = {}
    for key, counts in sorted(answer_balance.items()):
        n = sum(counts.values())
        majority = max(counts.values()) / n if n else None
        balance_report[key] = {
            "cases": n,
            "counts": dict(counts),
            "majorityShare": round(majority, 4) if majority is not None else None,
            "normalizedEntropy": round(entropy(counts), 4) if entropy(counts) is not None else None,
            "warning": bool(n >= 4 and majority is not None and majority > 0.75),
        }

    report = {
        "version": 1,
        "source": str(path),
        "validationStatus": data.get("validationStatus"),
        "cases": len(rows),
        "duplicateIds": duplicate_ids,
        "requiredFieldProblems": required_missing,
        "countsByDimension": {k: len(v) for k, v in sorted(by_dimension.items())},
        "countsByDimensionTask": dict(sorted(task_counts.items())),
        "countsByDimensionPhenomenon": dict(sorted(by_phenomenon.items())),
        "answerBalance": balance_report,
        "smallPhenomenonCells": small_cells,
        "highLexicalOverlapFlags": sorted(overlap_flags, key=lambda x: -x["tokenJaccard"]),
        "interpretation": [
            "This audit checks benchmark structure; it does not validate the linguistic gold labels.",
            "High lexical overlap is a human-review flag, not an error: minimal pairs and matched lexical-sense cases can intentionally overlap.",
            "Answer imbalance can create shortcut risk in a fixed forced-choice corpus even when model-visible option order is randomized.",
            "Phenomenon cells with one item are descriptive probes, not stable estimates of phenomenon-level competence.",
            "Independent annotation/adjudication remains required before the shadow set is treated as externally validated evidence."
        ],
        "researchGrounding": [
            "Benchmark Transparency (NAACL 2024): data distribution can materially affect model comparisons.",
            "When Benchmarks are Targets (ACL 2024): seemingly small benchmark-design choices can change rankings.",
            "Evidence-Centered Benchmark Design (ACL 2024): benchmark evidence should be explicitly linked to intended constructs and validity assumptions."
        ]
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
