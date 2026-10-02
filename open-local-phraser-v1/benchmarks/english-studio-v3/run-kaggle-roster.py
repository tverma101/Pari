#!/usr/bin/env python3
"""Run the frozen Kaggle candidate roster without agent decision-making.

Normal decode is always evaluated first. A candidate that fails a stage keeps its
artifacts and is skipped for later quality stages; the next roster candidate is
then attempted. The status matrix is regenerated after every stage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
DISPATCH = HERE / "run-kaggle-candidate.py"
MATRIX = HERE / "build-kaggle-candidate-matrix.py"

PHASE_STAGES = {
    "smoke": ("smoke",),
    "english": ("smoke", "full"),
    "product": ("smoke", "full", "transform", "word-studio"),
    "all": ("smoke", "full", "transform", "word-studio"),
}


def run(cmd: list[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    print("+", " ".join(cmd), flush=True)
    started = time.time()
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.time() - started
    log.write_text(proc.stdout, encoding="utf-8", errors="replace")
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    print(f"command rc={proc.returncode} elapsed={elapsed:.1f}s log={log}", flush=True)
    return proc.returncode


def rebuild_matrix(results_dir: Path) -> None:
    subprocess.run(
        [sys.executable, str(MATRIX), "--results-dir", str(results_dir)],
        check=False,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--phase", choices=sorted(PHASE_STAGES), default="all")
    ap.add_argument("--candidate", action="append", default=[], help="optional exact candidate id; repeat to choose a subset")
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--probe-mtp-smoke", action="store_true", help="after ordinary smoke success, probe only roster-declared MTP methods")
    args = ap.parse_args()

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    available = [row["id"] for row in roster["candidates"]]
    selected = args.candidate or available
    unknown = [x for x in selected if x not in available]
    if unknown:
        raise SystemExit(f"unknown candidates: {unknown}; allowed={available}")

    args.results_dir.mkdir(parents=True, exist_ok=True)
    orchestration = {
        "version": 1,
        "benchmarkRevision": args.benchmark_revision,
        "phase": args.phase,
        "selectedCandidates": selected,
        "stages": list(PHASE_STAGES[args.phase]),
        "candidates": [],
    }
    orchestration_path = args.results_dir / "roster-orchestration.json"

    by_id = {row["id"]: row for row in roster["candidates"]}
    for candidate_id in selected:
        candidate = by_id[candidate_id]
        record = {"candidate": candidate_id, "stages": [], "mtpSmoke": []}
        orchestration["candidates"].append(record)
        orchestration_path.write_text(json.dumps(orchestration, indent=2) + "\n", encoding="utf-8")

        ordinary_smoke_passed = False
        candidate_blocked = False
        for stage in PHASE_STAGES[args.phase]:
            if candidate_blocked:
                record["stages"].append({"stage": stage, "status": "skipped_due_to_prior_failure"})
                continue
            log = args.results_dir / "orchestration-logs" / f"{candidate_id}-{stage}.log.txt"
            cmd = [
                sys.executable, str(DISPATCH), candidate_id,
                "--stage", stage,
                "--benchmark-revision", args.benchmark_revision,
                "--results-dir", str(args.results_dir),
            ]
            rc = run(cmd, log)
            record["stages"].append({"stage": stage, "returnCode": rc, "log": str(log)})
            rebuild_matrix(args.results_dir)
            orchestration_path.write_text(json.dumps(orchestration, indent=2) + "\n", encoding="utf-8")
            if stage == "smoke" and rc == 0:
                ordinary_smoke_passed = True
            if rc != 0:
                candidate_blocked = True

        if args.probe_mtp_smoke and ordinary_smoke_passed and candidate.get("runtime") == "vllm":
            for method in candidate.get("mtpMethodsToProbe") or []:
                log = args.results_dir / "orchestration-logs" / f"{candidate_id}-smoke-{method}.log.txt"
                cmd = [
                    sys.executable, str(DISPATCH), candidate_id,
                    "--stage", "smoke", "--decode", method,
                    "--speculative-tokens", "1",
                    "--benchmark-revision", args.benchmark_revision,
                    "--results-dir", str(args.results_dir),
                ]
                rc = run(cmd, log)
                record["mtpSmoke"].append({"method": method, "returnCode": rc, "log": str(log)})
                rebuild_matrix(args.results_dir)
                orchestration_path.write_text(json.dumps(orchestration, indent=2) + "\n", encoding="utf-8")

    rebuild_matrix(args.results_dir)
    orchestration["complete"] = True
    orchestration_path.write_text(json.dumps(orchestration, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "orchestration_complete", "artifact": str(orchestration_path)}, indent=2))


if __name__ == "__main__":
    main()
