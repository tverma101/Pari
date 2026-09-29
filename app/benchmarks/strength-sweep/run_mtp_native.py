#!/usr/bin/env python3
"""Paired Qwen3.5 target-only vs native-MTP slider benchmark."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import run_native as common


ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(__file__).with_name("mtp_batch_server.py")
WORKER = ROOT / "native-runtime" / "paraphrase_worker.py"
PROTECTED_HELPER = Path(__file__).with_name("native_protected_spans.mjs")
CORPUS_DEFAULT = Path(__file__).with_name("corpus.brutal.v2.json")
OUT_DEFAULT = Path(__file__).with_name("results") / "qwen35-4b-mtp-brutal-v2"
TARGET_REVISION_DEFAULT = "32f3e8ecf65426fc3306969496342d504bfa13f3"
DRAFT_REVISION_DEFAULT = "ab6f59bc6627196c611ab8851638651078170485"


def mean(values: list[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def median(values: list[float]) -> float:
    return round(statistics.median(values), 2) if values else 0.0


def runtime_info(python: str) -> dict[str, str]:
    code = (
        "import importlib.metadata as m,json,sys; "
        "print(json.dumps({'python':sys.version.split()[0],"
        "'mlx':m.version('mlx'),'mlx_vlm':m.version('mlx-vlm'),"
        "'transformers':m.version('transformers')}))"
    )
    result = subprocess.run([python, "-c", code], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "The selected Python must have mlx, mlx-vlm, and transformers installed. "
            + (result.stderr.strip() or result.stdout.strip())
        )
    return json.loads(result.stdout)


def hardware_info() -> dict[str, Any]:
    memory = subprocess.run(
        ["sysctl", "-n", "hw.memsize"], check=False, capture_output=True, text=True
    )
    return {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "physicalMemoryBytes": int(memory.stdout.strip()) if memory.returncode == 0 else None,
    }


def speed_summary(rows: list[dict[str, Any]], modes: list[str]) -> dict[str, Any]:
    by_pair: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_pair[(row["caseId"], int(row["strength"]), int(row["repeat"]))][row["mode"]] = row
    pairs = [
        pair
        for pair in by_pair.values()
        if pair.get("target-only") and pair.get("mtp")
        and pair["target-only"].get("inferenceMs", 0) > 0
        and pair["mtp"].get("inferenceMs", 0) > 0
    ]
    speedups = [
        float(pair["target-only"]["inferenceMs"]) / float(pair["mtp"]["inferenceMs"])
        for pair in pairs
    ]
    saved = [
        float(pair["target-only"]["inferenceMs"]) - float(pair["mtp"]["inferenceMs"])
        for pair in pairs
    ]
    per_strength = []
    for strength in sorted({int(pair["mtp"]["strength"]) for pair in pairs}):
        selected = [
            pair for pair in pairs if int(pair["mtp"]["strength"]) == strength
        ]
        ratios = [
            float(pair["target-only"]["inferenceMs"]) / float(pair["mtp"]["inferenceMs"])
            for pair in selected
        ]
        per_strength.append(
            {
                "strength": strength,
                "pairedRows": len(selected),
                "medianSpeedup": median(ratios),
                "mtpFasterRate": mean([float(value > 1.0) for value in ratios]),
            }
        )
    geometric = math.exp(mean([math.log(value) for value in speedups if value > 0])) if speedups else 0.0
    return {
        "pairedRows": len(pairs),
        "mtpFasterRows": sum(value > 1.0 for value in speedups),
        "mtpFasterRate": mean([float(value > 1.0) for value in speedups]),
        "medianSpeedup": median(speedups),
        "geometricMeanSpeedup": round(geometric, 4),
        "medianInferenceMsSaved": median(saved),
        "meanTargetOnlyInferenceMs": mean([float(pair["target-only"]["inferenceMs"]) for pair in pairs]),
        "meanMtpInferenceMs": mean([float(pair["mtp"]["inferenceMs"]) for pair in pairs]),
        "perStrength": per_strength,
        "note": "Paired same-prompt target-only/MTP timings; model load excluded, prompt tokenization and generation included.",
    }


def summarize(rows: list[dict[str, Any]], requested_rows: int, modes: list[str]) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_mode[row["mode"]].append(row)
    mode_summary: dict[str, Any] = {}
    for mode in modes:
        current = by_mode[mode]
        per_strength = []
        for strength in sorted({int(row["strength"]) for row in current}):
            selected = [row for row in current if int(row["strength"]) == strength]
            per_strength.append(
                {
                    "strength": strength,
                    "promptRegime": selected[0]["promptRegime"],
                    "rows": len(selected),
                    "changedRate": mean([float(row["output"] != row["input"]) for row in selected]),
                    "meanLexicalChangeRate": mean([float(row["lexicalChangeRate"]) for row in selected]),
                    "hardGatePassRate": mean([float(row["hardGatePass"]) for row in selected]),
                    "medianInferenceMs": median([float(row["inferenceMs"]) for row in selected]),
                    "medianGenerationTokensPerSecond": median(
                        [float(row["generationTokensPerSecond"] or 0) for row in selected]
                    ),
                }
            )
        mode_summary[mode] = {
            "rows": len(current),
            "changedRate": mean([float(row["output"] != row["input"]) for row in current]),
            "meanLexicalChangeRate": mean([float(row["lexicalChangeRate"]) for row in current]),
            "hardGatePass": sum(bool(row["hardGatePass"]) for row in current),
            "hardGatePassRate": mean([float(row["hardGatePass"]) for row in current]),
            "meanInferenceMs": mean([float(row["inferenceMs"]) for row in current]),
            "medianInferenceMs": median([float(row["inferenceMs"]) for row in current]),
            "meanDurationMs": mean([float(row["durationMs"]) for row in current]),
            "medianGenerationTokensPerSecond": median(
                [float(row["generationTokensPerSecond"] or 0) for row in current]
            ),
            "perStrength": per_strength,
        }
    return {
        "requestedRows": requested_rows,
        "completedRows": len(rows),
        "remainingRows": max(0, requested_rows - len(rows)),
        "allStrengthsComplete": len(rows) == requested_rows,
        "modeSummary": mode_summary,
        "pairedSpeedComparison": speed_summary(rows, modes),
        "sliderRegimeMap": common.SLIDER_REGIME_MAP,
    }


def mode_order(seed: int, case_id: str, strength: int, repeat: int, modes: list[str]) -> list[str]:
    digest = hashlib.sha256(
        f"{seed}:{case_id}:{strength}:{repeat}".encode("utf-8")
    ).digest()
    return modes.copy() if digest[0] & 1 else list(reversed(modes))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Local Qwen3.5-4B target checkpoint.")
    parser.add_argument("--draft-model", help="Local matching Qwen3.5 MTP drafter.")
    parser.add_argument("--python", default=sys.executable, help="Python with mlx-vlm installed.")
    parser.add_argument("--target-revision", default=TARGET_REVISION_DEFAULT)
    parser.add_argument("--draft-revision", default=DRAFT_REVISION_DEFAULT)
    parser.add_argument("--corpus", default=str(CORPUS_DEFAULT))
    parser.add_argument("--strengths", default="regimes")
    parser.add_argument("--modes", default="target-only,mtp")
    parser.add_argument("--ids", help="Optional comma-separated case IDs.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=1, help="Unscored JIT warmups per mode.")
    parser.add_argument("--out-dir", default=str(OUT_DEFAULT))
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--seed", type=int, default=260922)
    args = parser.parse_args()

    corpus_path = Path(args.corpus).expanduser().resolve()
    model_path = Path(args.model).expanduser().resolve()
    draft_path = Path(args.draft_model).expanduser().resolve() if args.draft_model else None
    out_dir = Path(args.out_dir).expanduser().resolve()
    modes = [value.strip() for value in args.modes.split(",") if value.strip()]
    if len(set(modes)) != len(modes) or not modes or set(modes) - {"target-only", "mtp"}:
        raise SystemExit("--modes must be target-only, mtp, or both once each.")
    if "mtp" in modes and draft_path is None:
        raise SystemExit("--draft-model is required when --modes includes mtp.")
    if not corpus_path.is_file() or not model_path.is_dir():
        raise SystemExit("The corpus and local target model must exist.")
    if draft_path is not None and not draft_path.is_dir():
        raise SystemExit("The local MTP draft model directory does not exist.")
    if args.repeats < 1 or args.warmups < 0:
        raise SystemExit("--repeats must be positive and --warmups cannot be negative.")

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    cases = corpus.get("cases", [])
    if args.ids:
        wanted = {value.strip() for value in args.ids.split(",") if value.strip()}
        cases = [case for case in cases if case.get("id") in wanted]
        missing = wanted - {case.get("id") for case in cases}
        if missing:
            raise SystemExit("Unknown case IDs: " + ", ".join(sorted(missing)))
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be positive.")
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("No benchmark cases were selected.")
    strengths = common.parse_strengths(args.strengths)
    protected_by_case = common.extract_app_protected_spans(cases)
    runtime = runtime_info(args.python)

    config = {
        "benchmark": "pari-qwen35-native-mtp-slider-brutal-v2",
        "corpusPath": str(corpus_path),
        "corpusSha256": common.sha256_file(corpus_path),
        "caseIds": [case["id"] for case in cases],
        "strengths": strengths,
        "repeats": args.repeats,
        "modes": modes,
        "targetModelPath": str(model_path),
        "targetRevision": args.target_revision,
        "draftModelPath": str(draft_path) if draft_path else None,
        "draftRevision": args.draft_revision if draft_path else None,
        "draftKind": "mtp" if draft_path else None,
        "maxTokens": args.max_tokens,
        "baseSeed": args.seed,
        "warmupsPerMode": args.warmups,
        "generationPath": "Pari build_instruction/postprocess via MLX-VLM stream_generate",
        "runtime": runtime,
        "hardware": hardware_info(),
        "workerSha256": common.sha256_file(WORKER),
        "serverSha256": common.sha256_file(SERVER),
        "protectedExtractorSha256": common.sha256_file(ROOT / "src" / "lib" / "safety" / "protectedContent.ts"),
        "protectedHelperSha256": common.sha256_file(PROTECTED_HELPER),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw.jsonl"
    run_path = out_dir / "run.json"
    summary_path = out_dir / "summary.json"
    if run_path.exists():
        previous = json.loads(run_path.read_text(encoding="utf-8"))
        if previous.get("config") != config:
            raise SystemExit("This output directory belongs to a different configuration; choose a new --out-dir.")
    else:
        if raw_path.exists() or summary_path.exists():
            raise SystemExit("Output files exist without run.json; choose a new --out-dir to preserve them.")
        run_path.write_text(
            json.dumps(
                {
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "git": common.git_snapshot(),
                    "pythonExecutable": args.python,
                    "runtime": runtime,
                    "config": config,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    rows = common.read_rows(raw_path)
    requested_keys = {
        (case["id"], strength, repeat, mode)
        for case in cases
        for strength in strengths
        for repeat in range(args.repeats)
        for mode in modes
    }
    completed = {
        (row["caseId"], int(row["strength"]), int(row["repeat"]), row["mode"])
        for row in rows
    }
    if completed - requested_keys:
        raise SystemExit("Checkpoint contains rows outside this configuration; use a new --out-dir.")
    todo = [
        (case, strength, repeat)
        for case in cases
        for strength in strengths
        for repeat in range(args.repeats)
        if any((case["id"], strength, repeat, mode) not in completed for mode in modes)
    ]
    total = len(requested_keys)
    print(
        f"[qwen35-mtp] cases={len(cases)} strengths={len(strengths)} repeats={args.repeats} "
        f"modes={','.join(modes)} requested={total} complete={len(completed)} model={model_path}",
        flush=True,
    )
    command = [args.python, str(SERVER), "--model", str(model_path)]
    if draft_path is not None:
        command.extend(["--draft-model", str(draft_path)])
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    started = time.perf_counter()
    try:
        assert process.stdout is not None and process.stdin is not None
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("MLX-VLM exited before model readiness.")
        ready = json.loads(line)
        if ready.get("ready") is not True:
            raise RuntimeError("MLX-VLM did not send its ready handshake.")
        if "mtp" in modes and ready.get("draftKind") != "mtp":
            raise RuntimeError("MLX-VLM did not resolve the requested MTP drafter.")
        print(
            "[qwen35-mtp] worker ready model="
            + str(ready.get("model"))
            + " draft="
            + str(ready.get("draftModel"))
            + " kind="
            + str(ready.get("draftKind")),
            flush=True,
        )

        def request(mode: str, case: dict[str, Any], strength: int, repeat: int, warmup: bool = False):
            seed_digest = hashlib.sha256(
                f"{args.seed}:{case['id']}:{repeat}".encode("utf-8")
            ).digest()
            seed = int.from_bytes(seed_digest[:4], "big") & 0x7FFFFFFF
            protected_spans = protected_by_case[case["id"]]
            payload = {
                "originalText": case["input"],
                "protectedSpans": [span["text"] for span in protected_spans],
                "mode": "personal",
                "strength": strength,
                "maxTokens": args.max_tokens,
                "useMtp": mode == "mtp",
            }
            request_id = f"{'warmup' if warmup else 'case'}-{case['id']}-{strength}-{repeat}-{mode}"
            process.stdin.write(
                json.dumps({"id": request_id, "seed": seed, "payload": payload}, ensure_ascii=False) + "\n"
            )
            process.stdin.flush()
            response_line = process.stdout.readline()
            if not response_line:
                raise RuntimeError("MLX-VLM exited while generating " + request_id)
            message = json.loads(response_line)
            if message.get("id") != request_id:
                raise RuntimeError("MLX-VLM response ID mismatch for " + request_id)
            return message.get("response") or {}, protected_spans, seed

        warmup_case = cases[0]
        warmup_order = modes if args.seed & 1 else list(reversed(modes))
        for repeat in range(args.warmups):
            for mode in warmup_order:
                result, _, _ = request(mode, warmup_case, 82, repeat, warmup=True)
                if not result.get("ok"):
                    raise RuntimeError("Unscored " + mode + " warmup failed: " + str(result.get("error")))
        if args.warmups:
            print(f"[qwen35-mtp] completed {args.warmups} unscored warmup(s) per mode", flush=True)

        with raw_path.open("a", encoding="utf-8") as checkpoint:
            completed_now = 0
            for case, strength, repeat in todo:
                for mode in mode_order(args.seed, case["id"], strength, repeat, modes):
                    key = (case["id"], strength, repeat, mode)
                    if key in completed:
                        continue
                    response, protected_spans, seed = request(mode, case, strength, repeat)
                    output = str(response.get("text") or "").strip()
                    issues = common.hard_gate_issues(output, bool(response.get("ok")), protected_spans)
                    row = {
                        "caseId": case["id"],
                        "category": case.get("category"),
                        "input": case["input"],
                        "mustPreserve": case.get("mustPreserve", []),
                        "doNotInfer": case.get("doNotInfer", []),
                        "editIntent": case.get("editIntent", ""),
                        "protectedSpans": protected_spans,
                        "strength": strength,
                        "promptRegime": common.prompt_regime(strength),
                        "repeat": repeat,
                        "mode": mode,
                        "modelPath": str(model_path),
                        "draftModelPath": str(draft_path) if mode == "mtp" else None,
                        "draftKind": ready.get("draftKind") if mode == "mtp" else None,
                        "seed": seed,
                        "temperature": response.get("temperature"),
                        "topP": response.get("top_p"),
                        "durationMs": int(response.get("duration_ms") or 0),
                        "inferenceMs": int(response.get("inference_ms") or 0),
                        "promptTokens": response.get("prompt_tokens"),
                        "generationTokens": response.get("generation_tokens"),
                        "promptTokensPerSecond": response.get("prompt_tokens_per_second"),
                        "generationTokensPerSecond": response.get("generation_tokens_per_second"),
                        "finishReason": response.get("finish_reason"),
                        "peakMemoryGb": response.get("peak_memory_gb"),
                        "mtpAcceptance": response.get("mtp_acceptance"),
                        "output": output,
                        "workerOk": bool(response.get("ok")),
                        "workerError": response.get("error"),
                        "hardGateIssues": issues,
                        "hardGatePass": not issues,
                        "lexicalChangeRate": common.lexical_change_rate(case["input"], output),
                    }
                    checkpoint.write(json.dumps(row, ensure_ascii=False) + "\n")
                    checkpoint.flush()
                    rows.append(row)
                    completed.add(key)
                    completed_now += 1
                    if completed_now % 10 == 0 or completed_now == len(todo) * len(modes) or issues:
                        elapsed = time.perf_counter() - started
                        rate = completed_now / max(elapsed, 0.001)
                        remaining = (total - len(completed)) / max(rate, 0.001)
                        print(
                            f"[qwen35-mtp] {len(completed)}/{total}; last={case['id']}@{strength}/{mode} "
                            f"{row['inferenceMs']}ms"
                            + (" gate=FAIL " + ",".join(issues) if issues else "")
                            + f"; ETA {remaining / 60:.1f} min",
                            flush=True,
                        )
                    if process.poll() is not None:
                        raise RuntimeError("MLX-VLM worker exited unexpectedly.")
    except KeyboardInterrupt:
        print("\nInterrupted safely; completed rows remain in " + str(raw_path), file=sys.stderr)
    finally:
        if process.poll() is None:
            try:
                assert process.stdin is not None
                process.stdin.close()
                process.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        summary = summarize(rows, total, modes)
        summary["updatedAt"] = datetime.now(timezone.utc).isoformat()
        summary["outputDirectory"] = str(out_dir)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(
            f"[qwen35-mtp] checkpoint {summary['completedRows']}/{total}; summary={summary_path}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
