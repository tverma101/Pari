#!/usr/bin/env python3
"""Build an explicit runtime/product status matrix from Kaggle result summaries.

This tool never ranks models. It prevents silent omission by requiring every
roster candidate and every required stage to appear as completed, failed, or
not-run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
REQUIRED_STAGES = ("smoke", "full", "word-studio", "transform")


def load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def summary_path(results: Path, candidate: dict[str, Any], stage: str, decode: str = "normal") -> Path:
    if candidate.get("runtime") == "vllm":
        return results / candidate["id"] / stage / decode / "summary.json"
    return results / candidate["id"] / stage / "summary.json"


def state_for(path: Path) -> dict[str, Any]:
    data = load(path)
    if data is None:
        return {"status": "not_run", "summary": str(path)}
    return {
        "status": data.get("status", "unknown"),
        "summary": str(path),
        "result": data.get("result"),
        "stableBatchSize": data.get("stableBatchSize"),
        "terminalFailureCategories": data.get("terminalFailureCategories", []),
        "protocolDiagnostics": data.get("protocolDiagnostics"),
    }


def disposition(row: dict[str, Any]) -> str:
    states = [row[stage]["status"] for stage in REQUIRED_STAGES]
    if any(status == "runtime_unqualified" for status in states):
        return "runtime_unqualified"
    if all(status == "completed" for status in states):
        return "fully_measured_pending_quality_comparison"
    if any(status in {"benchmark_tool_failure", "benchmark_validation_failure"} for status in states):
        return "benchmark_blocked"
    return "pending_measurement"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--json", type=Path, default=Path("/kaggle/working/results/candidate-matrix.json"))
    ap.add_argument("--markdown", type=Path, default=Path("/kaggle/working/results/candidate-matrix.md"))
    args = ap.parse_args()

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    rows = []
    for candidate in roster["candidates"]:
        row: dict[str, Any] = {
            "candidate": candidate["id"],
            "runtime": candidate.get("runtime"),
            "repo": candidate.get("repo"),
            "revision": candidate.get("revision"),
            "quantization": candidate.get("quantization"),
        }
        for stage in REQUIRED_STAGES:
            row[stage] = state_for(summary_path(args.results_dir, candidate, stage))
        mtp = {}
        for method in candidate.get("mtpMethodsToProbe") or []:
            mtp[method] = {
                "smoke": state_for(summary_path(args.results_dir, candidate, "smoke", method)),
                "full": state_for(summary_path(args.results_dir, candidate, "full", method)),
                "wordStudio": state_for(summary_path(args.results_dir, candidate, "word-studio", method)),
                "transform": state_for(summary_path(args.results_dir, candidate, "transform", method)),
            }
        row["speculative"] = mtp
        row["disposition"] = disposition(row)
        rows.append(row)

    report = {
        "version": 1,
        "resultsDir": str(args.results_dir),
        "requiredStages": list(REQUIRED_STAGES),
        "rows": rows,
        "counts": {
            status: sum(1 for row in rows if row["disposition"] == status)
            for status in sorted({row["disposition"] for row in rows})
        },
        "interpretation": [
            "This is a completeness/runtime matrix, not a quality ranking.",
            "not_run remains visible so missing candidates cannot disappear from the final report.",
            "runtime_unqualified is not an English score of zero.",
        ],
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    headers = ["candidate", "runtime", "smoke", "full", "word-studio", "transform", "spec/MTP", "disposition"]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        spec = ", ".join(f"{k}:{v['smoke']['status']}" for k, v in row["speculative"].items()) or "n/a"
        lines.append("| " + " | ".join([
            row["candidate"], row["runtime"], row["smoke"]["status"], row["full"]["status"],
            row["word-studio"]["status"], row["transform"]["status"], spec, row["disposition"],
        ]) + " |")
    args.markdown.write_text("# Kaggle candidate status matrix\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(args.json), "markdown": str(args.markdown), "counts": report["counts"]}, indent=2))


if __name__ == "__main__":
    main()
