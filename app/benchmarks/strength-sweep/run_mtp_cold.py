#!/usr/bin/env python3
"""Fresh-process Qwen3.5 target-only vs MTP latency pilot.

Unlike run_mtp_native.py, each scored request starts a new worker and includes
Python startup plus target/drafter model loading in the wall-clock measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import run_mtp_native as paired
import run_native as common


ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).with_name("mtp_batch_server.py")
CORPUS_DEFAULT = Path(__file__).with_name("corpus.brutal.v2.json")
OUT_DEFAULT = Path(__file__).with_name("results") / "qwen35-mtp-cold-pilot"


def median(values: list[float]) -> float:
    return round(statistics.median(values), 2) if values else 0.0


def summarize(rows: list[dict[str, Any]], requested_rows: int) -> dict[str, Any]:
    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        pairs[(str(row["caseId"]), int(row["strength"]))][str(row["mode"])] = row
    matched = [
        pair for pair in pairs.values()
        if pair.get("target-only") is not None and pair.get("mtp") is not None
    ]
    speedups = [
        float(pair["target-only"]["workerWallMs"]) / max(float(pair["mtp"]["workerWallMs"]), 1.0)
        for pair in matched
    ]
    return {
        "requestedRows": requested_rows,
        "completedRows": len(rows),
        "remainingRows": max(0, requested_rows - len(rows)),
        "allRowsComplete": len(rows) == requested_rows,
        "matchedPairs": len(matched),
        "mtpFasterPairs": sum(value > 1.0 for value in speedups),
        "mtpFasterRate": round(sum(value > 1.0 for value in speedups) / len(speedups), 4) if speedups else 0.0,
        "medianSpeedup": median(speedups),
        "medianWorkerWallMsTargetOnly": median(
            [float(pair["target-only"]["workerWallMs"]) for pair in matched]
        ),
        "medianWorkerWallMsMtp": median(
            [float(pair["mtp"]["workerWallMs"]) for pair in matched]
        ),
        "medianReadyWaitMsTargetOnly": median(
            [float(pair["target-only"]["readyWaitMs"]) for pair in matched]
        ),
        "medianReadyWaitMsMtp": median(
            [float(pair["mtp"]["readyWaitMs"]) for pair in matched]
        ),
        "byteIdenticalOutputs": sum(
            pair["target-only"]["output"] == pair["mtp"]["output"] for pair in matched
        ),
        "note": "Fresh subprocess per request; workerWallMs includes interpreter start, model load, prompt construction, and generation. It excludes app/UI work outside the worker.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--draft-model", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--corpus", default=str(CORPUS_DEFAULT))
    parser.add_argument("--ids", default="voice-01,fragment-01,long-01")
    parser.add_argument("--strengths", default="50,82")
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--seed", type=int, default=260922)
    parser.add_argument("--out-dir", default=str(OUT_DEFAULT))
    args = parser.parse_args()

    model_path = Path(args.model).expanduser().resolve()
    draft_path = Path(args.draft_model).expanduser().resolve()
    corpus_path = Path(args.corpus).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    if not model_path.is_dir() or not draft_path.is_dir() or not corpus_path.is_file():
        raise SystemExit("The local target, MTP drafter, and corpus must exist.")

    corpus_data = json.loads(corpus_path.read_text(encoding="utf-8"))
    wanted_ids = {value.strip() for value in args.ids.split(",") if value.strip()}
    cases = [case for case in corpus_data.get("cases", []) if case.get("id") in wanted_ids]
    missing = wanted_ids - {case.get("id") for case in cases}
    if missing:
        raise SystemExit("Unknown benchmark case IDs: " + ", ".join(sorted(missing)))
    strengths = common.parse_strengths(args.strengths)
    if not cases or not strengths:
        raise SystemExit("Select at least one case and strength.")
    protected_by_case = common.extract_app_protected_spans(cases)

    config = {
        "benchmark": "pari-qwen35-mtp-cold-start-pilot",
        "corpusSha256": common.sha256_file(corpus_path),
        "caseIds": [case["id"] for case in cases],
        "strengths": strengths,
        "modes": ["target-only", "mtp"],
        "targetModelPath": str(model_path),
        "draftModelPath": str(draft_path),
        "targetRevision": paired.TARGET_REVISION_DEFAULT,
        "draftRevision": paired.DRAFT_REVISION_DEFAULT,
        "maxTokens": args.max_tokens,
        "seed": args.seed,
        "python": args.python,
        "workerSha256": common.sha256_file(ROOT / "native-runtime" / "paraphrase_worker.py"),
        "serverSha256": common.sha256_file(SERVER),
        "runnerSha256": common.sha256_file(Path(__file__).resolve()),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw.jsonl"
    run_path = out_dir / "run.json"
    summary_path = out_dir / "summary.json"
    if run_path.exists():
        previous = json.loads(run_path.read_text(encoding="utf-8"))
        if previous.get("config") != config:
            raise SystemExit("This output directory belongs to another configuration; choose a new --out-dir.")
    else:
        if raw_path.exists() or summary_path.exists():
            raise SystemExit("Output files exist without run.json; choose a new --out-dir.")
        run_path.write_text(
            json.dumps(
                {
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "git": common.git_snapshot(),
                    "config": config,
                    "runtime": paired.runtime_info(args.python),
                    "hardware": paired.hardware_info(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    rows = common.read_rows(raw_path)
    requested_keys = {
        (case["id"], strength, mode)
        for case in cases
        for strength in strengths
        for mode in ("target-only", "mtp")
    }
    completed = {
        (str(row["caseId"]), int(row["strength"]), str(row["mode"]))
        for row in rows
    }
    if completed - requested_keys:
        raise SystemExit("Checkpoint contains rows outside this configuration; choose a new output directory.")
    total = len(requested_keys)
    print(
        f"[qwen35-mtp-cold] cases={len(cases)} strengths={len(strengths)} "
        f"requested={total} complete={len(completed)}",
        flush=True,
    )

    with raw_path.open("a", encoding="utf-8") as checkpoint:
        for case in cases:
            for strength in strengths:
                seed_digest = hashlib.sha256(
                    f"{args.seed}:{case['id']}:0".encode("utf-8")
                ).digest()
                seed = int.from_bytes(seed_digest[:4], "big") & 0x7FFFFFFF
                protected_spans = protected_by_case[case["id"]]
                payload = {
                    "originalText": case["input"],
                    "protectedSpans": [span["text"] for span in protected_spans],
                    "mode": "personal",
                    "strength": strength,
                    "maxTokens": args.max_tokens,
                    "useMtp": False,
                }
                order = paired.mode_order(args.seed, case["id"], strength, 0, ["target-only", "mtp"])
                for mode in order:
                    key = (case["id"], strength, mode)
                    if key in completed:
                        continue
                    use_mtp = mode == "mtp"
                    payload["useMtp"] = use_mtp
                    command = [args.python, str(SERVER), "--model", str(model_path)]
                    if use_mtp:
                        command.extend(["--draft-model", str(draft_path)])
                    started = time.perf_counter()
                    process = subprocess.Popen(
                        command,
                        cwd=str(ROOT),
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        bufsize=1,
                    )
                    try:
                        assert process.stdout is not None and process.stdin is not None
                        ready_line = process.stdout.readline()
                        ready_wait_ms = round((time.perf_counter() - started) * 1000)
                        if not ready_line:
                            raise RuntimeError(f"Worker exited before readiness for {case['id']}@{strength}/{mode}.")
                        ready = json.loads(ready_line)
                        if ready.get("ready") is not True or (use_mtp and ready.get("draftKind") != "mtp"):
                            raise RuntimeError("Worker readiness handshake did not confirm the requested runtime.")
                        request_id = f"cold-{case['id']}-{strength}-{mode}"
                        process.stdin.write(
                            json.dumps(
                                {"id": request_id, "seed": seed, "payload": payload},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        process.stdin.flush()
                        response_line = process.stdout.readline()
                        if not response_line:
                            raise RuntimeError(f"Worker exited during generation for {request_id}.")
                        message = json.loads(response_line)
                        if message.get("id") != request_id:
                            raise RuntimeError(f"Worker response ID mismatch for {request_id}.")
                        response = message.get("response") or {}
                        worker_wall_ms = round((time.perf_counter() - started) * 1000)
                    finally:
                        if process.stdin is not None:
                            process.stdin.close()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                            process.wait(timeout=5)

                    output = str(response.get("text") or "").strip()
                    issues = common.hard_gate_issues(
                        output, bool(response.get("ok")), protected_spans
                    )
                    row = {
                        "caseId": case["id"],
                        "category": case.get("category"),
                        "input": case["input"],
                        "strength": strength,
                        "promptRegime": common.prompt_regime(strength),
                        "mode": mode,
                        "seed": seed,
                        "readyWaitMs": ready_wait_ms,
                        "workerWallMs": worker_wall_ms,
                        "inferenceMs": int(response.get("inference_ms") or 0),
                        "generationTokens": response.get("generation_tokens"),
                        "generationTokensPerSecond": response.get("generation_tokens_per_second"),
                        "output": output,
                        "workerOk": bool(response.get("ok")),
                        "hardGateIssues": issues,
                        "hardGatePass": not issues,
                        "lexicalChangeRate": common.lexical_change_rate(case["input"], output),
                    }
                    checkpoint.write(json.dumps(row, ensure_ascii=False) + "\n")
                    checkpoint.flush()
                    rows.append(row)
                    completed.add(key)
                    print(
                        f"[qwen35-mtp-cold] {len(completed)}/{total} {case['id']}@{strength}/{mode} "
                        f"ready={ready_wait_ms}ms wall={worker_wall_ms}ms",
                        flush=True,
                    )

    summary = summarize(rows, total)
    summary["updatedAt"] = datetime.now(timezone.utc).isoformat()
    summary["outputDirectory"] = str(out_dir)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[qwen35-mtp-cold] summary={summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
