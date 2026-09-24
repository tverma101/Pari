"""Score Pari model outputs on SemanticQA LCC 8-category zero-shot tasks.

The scorer keeps SemanticQA's established classification metrics (accuracy and
macro/micro/weighted F1), adds valid-output coverage, and binds the result to the
exact task/answer/manifest bytes used for the run. It does not merge this score
into the Pari shadow composite automatically; public anchors remain separately
reported evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

LABELS = ("Magn", "AntiMagn", "Ver", "AntiVer", "Bon", "AntiBon", "Son", "Oper1")
LABEL_SET = set(LABELS)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_prediction(text: str) -> str | None:
    """Conservatively recover exactly one SemanticQA LCC label from output."""
    raw = str(text or "").strip()
    if not raw:
        return None
    for label in LABELS:
        if raw == label or raw.lower() == label.lower():
            return label
    found = []
    for label in LABELS:
        pattern = rf"(?<![A-Za-z]){re.escape(label)}(?![A-Za-z])"
        if re.search(pattern, raw, flags=re.IGNORECASE):
            found.append(label)
    unique = list(dict.fromkeys(found))
    return unique[0] if len(unique) == 1 else None


def f1_for_label(golds: list[str], preds: list[str | None], label: str) -> tuple[float, int, int, int]:
    tp = sum(g == label and p == label for g, p in zip(golds, preds))
    fp = sum(g != label and p == label for g, p in zip(golds, preds))
    fn = sum(g == label and p != label for g, p in zip(golds, preds))
    denom = 2 * tp + fp + fn
    return ((2 * tp / denom) if denom else 0.0), tp, fp, fn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", type=Path, help="run-english-core-mlx.py result JSON")
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    result = load_json(args.result)
    answers_obj = load_json(args.answers)
    manifest = load_json(args.manifest)
    task_bytes = args.tasks.read_bytes()
    answer_bytes = args.answers.read_bytes()
    manifest_bytes = args.manifest.read_bytes()
    tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]

    task_ids = [row.get("id") for row in tasks]
    if any(not x for x in task_ids) or len(task_ids) != len(set(task_ids)):
        raise SystemExit("Task file contains missing or duplicate IDs")
    if result.get("taskFileSha256") != sha256_bytes(task_bytes):
        raise SystemExit("Model result taskFileSha256 does not match the exact SemanticQA LCC task file")
    if result.get("taskCount") != len(tasks):
        raise SystemExit("Model result taskCount does not match SemanticQA LCC task count")
    if manifest.get("taskFileSha256") != sha256_bytes(task_bytes):
        raise SystemExit("SemanticQA LCC manifest/task hash mismatch")
    if manifest.get("answerFileSha256") != sha256_bytes(answer_bytes):
        raise SystemExit("SemanticQA LCC manifest/answer hash mismatch")

    answer_rows = answers_obj.get("answers") or []
    answer_map = {row.get("id"): row.get("label") for row in answer_rows}
    if len(answer_map) != len(answer_rows):
        raise SystemExit("Answer file contains duplicate IDs")
    if set(answer_map) != set(task_ids):
        raise SystemExit("Task and answer ID sets differ")
    if set(answer_map.values()) - LABEL_SET:
        raise SystemExit("Answer file contains an unknown SemanticQA LCC label")

    outputs = result.get("outputs") or []
    output_ids = [row.get("id") for row in outputs if isinstance(row, dict)]
    if len(output_ids) != len(outputs) or any(not x for x in output_ids):
        raise SystemExit("Model result contains malformed output rows")
    if len(output_ids) != len(set(output_ids)):
        raise SystemExit("Model result contains duplicate output IDs")
    extra = set(output_ids) - set(task_ids)
    missing = set(task_ids) - set(output_ids)
    if extra:
        raise SystemExit(f"Model result contains {len(extra)} foreign SemanticQA LCC IDs")
    if missing:
        raise SystemExit(f"Model result is missing {len(missing)} SemanticQA LCC outputs")

    output_map = {row["id"]: row for row in outputs}
    golds: list[str] = []
    preds: list[str | None] = []
    detail = []
    for task_id in task_ids:
        gold = answer_map[task_id]
        raw = output_map[task_id].get("output", "")
        pred = parse_prediction(raw)
        golds.append(gold)
        preds.append(pred)
        detail.append({"id": task_id, "gold": gold, "prediction": pred, "validOutput": pred is not None, "correct": pred == gold})

    valid = sum(p is not None for p in preds)
    correct = sum(p == g for p, g in zip(preds, golds))
    accuracy = correct / len(golds)

    per_label = {}
    f1s = []
    supports = Counter(golds)
    total_tp = total_fp = total_fn = 0
    for label in LABELS:
        f1, tp, fp, fn = f1_for_label(golds, preds, label)
        f1s.append(f1)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        per_label[label] = {"support": supports[label], "f1": round(f1, 6), "tp": tp, "fp": fp, "fn": fn}

    macro_f1 = sum(f1s) / len(f1s)
    weighted_f1 = sum(per_label[l]["f1"] * supports[l] for l in LABELS) / len(golds)
    micro_denom = 2 * total_tp + total_fp + total_fn
    micro_f1 = (2 * total_tp / micro_denom) if micro_denom else 0.0

    report = {
        "version": 1,
        "benchmark": "SemanticQA LCC 8-category zero-shot",
        "model": result.get("model"),
        "cases": len(golds),
        "validOutputs": valid,
        "validOutputCoverage": round(valid / len(golds), 6),
        "correct": correct,
        "accuracy": round(accuracy, 6),
        "macroF1": round(macro_f1, 6),
        "microF1": round(micro_f1, 6),
        "weightedF1": round(weighted_f1, 6),
        "perLabel": per_label,
        "provenance": {
            "resultSha256": sha256_file(args.result),
            "taskSha256": sha256_bytes(task_bytes),
            "answerSha256": sha256_bytes(answer_bytes),
            "manifestSha256": sha256_bytes(manifest_bytes),
            "semanticqaSourceCommit": manifest.get("sourceCommit"),
            "datasetMember": (manifest.get("assets") or {}).get("datasetMember"),
            "prompt": (manifest.get("assets") or {}).get("prompt"),
            "taxonomy": (manifest.get("assets") or {}).get("taxonomy"),
        },
        "detail": detail,
        "interpretation": [
            "Accuracy/F1 follow SemanticQA's LCC classification construct; invalid or malformed outputs count as incorrect and are additionally exposed through validOutputCoverage.",
            "This is modern prompted LLM evidence for collocation-semantic categorization. Do not relabel it as the EACL 2021 supervised/native score.",
            "Report this public anchor separately from Pari shadow collocation cases and from product-weighted English Core composites.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cases", "validOutputCoverage", "accuracy", "macroF1", "microF1", "weightedF1")}, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
