#!/usr/bin/env python3
"""Resumable all-strength sweep against Pari's resident native MLX worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HELPER = Path(__file__).with_name("native_batch_server.py")
PROTECTED_HELPER = Path(__file__).with_name("native_protected_spans.mjs")
CORPUS_DEFAULT = Path(__file__).with_name("corpus.brutal.v2.json")
OUT_DEFAULT = Path(__file__).with_name("results") / "native-brutal-v2"
REGIME_STRENGTHS = [0, 25, 50, 69, 75, 82, 100]
SLIDER_REGIME_MAP = [
    {"from": 0, "to": 24, "representative": 0, "regime": "light"},
    {"from": 25, "to": 49, "representative": 25, "regime": "balanced"},
    {"from": 50, "to": 68, "representative": 50, "regime": "strong-wording"},
    {"from": 69, "to": 74, "representative": 69, "regime": "strong-structure"},
    {"from": 75, "to": 81, "representative": 75, "regime": "deep-wording"},
    {"from": 82, "to": 100, "representative": 82, "regime": "deep-structure"},
]
MODEL_DEFAULT = (
    Path.home()
    / "Library/Application Support/Open Local Phraser/Models/native-models/Qwen/Qwen3-4B-MLX-4bit"
)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_repo_path(path: Path) -> str:
    """Return a repo-relative path, or only the basename for external files."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def portable_model_path(path: Path | None) -> str | None:
    """Keep the model directory label without recording a machine-local path."""
    return f"<local-model>/{path.name}" if path is not None else None


def parse_strengths(raw: str) -> list[int]:
    if raw.strip().lower() == "regimes":
        return REGIME_STRENGTHS.copy()
    if raw.strip().lower() == "all":
        return list(range(101))
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if match:
            start, end = map(int, match.groups())
            if start > end:
                raise ValueError("Strength ranges must be written low-to-high.")
            values.update(range(start, end + 1))
        elif part.isdigit():
            values.add(int(part))
        else:
            raise ValueError("Use integer strengths, comma-separated, or ranges such as 0-100.")
    if not values or min(values) < 0 or max(values) > 100:
        raise ValueError("Strengths must be integers from 0 through 100.")
    return sorted(values)


def prompt_regime(strength: int) -> str:
    if strength < 25:
        return "light"
    if strength < 50:
        return "balanced"
    if strength < 69:
        return "strong-wording"
    if strength < 75:
        return "strong-structure"
    if strength < 82:
        return "deep-wording"
    return "deep-structure"


def extract_app_protected_spans(cases: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    result = subprocess.run(
        ["node", str(PROTECTED_HELPER)],
        cwd=str(ROOT),
        input=json.dumps([case["input"] for case in cases], ensure_ascii=False),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not load Pari's TypeScript protected-content extractor. "
            + (result.stderr.strip() or "Run the benchmark from the app checkout with npm dependencies installed.")
        )
    extracted = json.loads(result.stdout)
    if len(extracted) != len(cases):
        raise RuntimeError("Protected-content extractor returned the wrong number of case rows.")
    return {case["id"]: spans for case, spans in zip(cases, extracted)}


def runtime_info(python: str) -> dict[str, str]:
    code = (
        "import importlib.metadata as m,json,sys; "
        "print(json.dumps({'python':sys.version.split()[0],"
        "'mlx':m.version('mlx'),'mlx_lm':m.version('mlx-lm')}))"
    )
    result = subprocess.run([python, "-c", code], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "The selected Python must have mlx and mlx-lm installed. "
            + (result.stderr.strip() or result.stdout.strip())
        )
    return json.loads(result.stdout)


def hard_gate_issues(output: str, worker_ok: bool, protected_spans: list[dict[str, str]]) -> list[str]:
    issues: list[str] = []
    if not worker_ok:
        issues.append("worker-error")
    if not output.strip():
        issues.append("empty-output")
        return issues
    distinct = list(dict.fromkeys(span["text"] for span in protected_spans))
    for value in distinct:
        matching = [span for span in protected_spans if span["text"] == value]
        expected = len(matching)
        actual = output.count(value)
        case_normalized_negation = all(span["kind"] == "negation" for span in matching)
        if actual < expected and not (
            case_normalized_negation
            and len(re.findall(re.escape(value), output, flags=re.IGNORECASE)) >= expected
        ):
            issues.append("missing-protected-span:" + value)
    return issues


def word_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+(?:[-'][a-z]+)*", text.casefold())


def lexical_change_rate(original: str, output: str) -> float:
    source = Counter(word_tokens(original))
    generated = Counter(word_tokens(output))
    shared = sum(min(count, generated[token]) for token, count in source.items())
    return round(1 - shared / max(1, sum(source.values())), 4)


def mean(values: list[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def median(values: list[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def summarize(rows: list[dict[str, Any]], requested_rows: int) -> dict[str, Any]:
    by_strength: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_strength[int(row["strength"])].append(row)
        by_case[row["caseId"]].append(row)

    per_strength = []
    for strength in sorted(by_strength):
        current = by_strength[strength]
        per_strength.append(
            {
                "strength": strength,
                "promptRegime": prompt_regime(strength),
                "rows": len(current),
                "changed": sum(row["output"] != row["input"] for row in current),
                "changedRate": mean([float(row["output"] != row["input"]) for row in current]),
                "meanLexicalChangeRate": mean([row["lexicalChangeRate"] for row in current]),
                "hardGatePass": sum(row["hardGatePass"] for row in current),
                "hardGatePassRate": mean([float(row["hardGatePass"]) for row in current]),
                "medianDurationMs": median([row["durationMs"] for row in current]),
            }
        )

    adjacent: list[float] = []
    same_regime: list[float] = []
    for case_rows in by_case.values():
        lookup = {int(row["strength"]): row for row in case_rows}
        selected_strengths = sorted(lookup)
        for left, right in zip(selected_strengths, selected_strengths[1:]):
            left_row, right_row = lookup[left], lookup[right]
            adjacent.append(float(left_row["output"] != right_row["output"]))
            if left_row["promptRegime"] == right_row["promptRegime"]:
                same_regime.append(float(left_row["output"] == right_row["output"]))

    distinct_per_case = [
        len({row["output"] for row in case_rows if row["output"]})
        for case_rows in by_case.values()
    ]
    return {
        "requestedRows": requested_rows,
        "completedRows": len(rows),
        "remainingRows": max(0, requested_rows - len(rows)),
        "allStrengthsComplete": len(rows) == requested_rows,
        "changed": sum(row["output"] != row["input"] for row in rows),
        "changedRate": mean([float(row["output"] != row["input"]) for row in rows]),
        "meanLexicalChangeRate": mean([row["lexicalChangeRate"] for row in rows]),
        "hardGatePass": sum(row["hardGatePass"] for row in rows),
        "hardGatePassRate": mean([float(row["hardGatePass"]) for row in rows]),
        "anchorOrWorkerFailures": sum(not row["hardGatePass"] for row in rows),
        "meanDurationMs": mean([row["durationMs"] for row in rows]),
        "medianDurationMs": median([row["durationMs"] for row in rows]),
        "adjacentStrengthOutputChangeRate": mean(adjacent),
        "samePromptRegimeExactRepeatRate": mean(same_regime),
        "meanDistinctOutputsPerCaseAcrossRequestedStrengths": mean(distinct_per_case),
        "sliderRegimeMap": SLIDER_REGIME_MAP,
        "perStrength": per_strength,
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    "The checkpoint has a malformed JSONL row at line "
                    + str(line_number)
                    + "; it was left untouched. Choose a new --out-dir to continue safely."
                ) from error
    return rows


def git_snapshot() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    status = git("status", "--short")
    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "dirtyStatusEntries": len(status.splitlines()) if status else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("PARI_NATIVE_MODEL_PATH", str(MODEL_DEFAULT)))
    parser.add_argument("--python", default=os.environ.get("PARI_BENCH_PYTHON", sys.executable))
    parser.add_argument("--draft-model")
    parser.add_argument("--num-draft-tokens", type=int, default=3)
    parser.add_argument("--corpus", default=str(CORPUS_DEFAULT))
    parser.add_argument(
        "--strengths",
        default="regimes",
        help="Default 'regimes' covers each distinct slider configuration plus 100; use 0-100 for every integer.",
    )
    parser.add_argument("--ids", help="Optional comma-separated case IDs.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--out-dir", default=str(OUT_DEFAULT))
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument("--temperature", type=float, help="Omit to use Pari's production strength-based temperature.")
    parser.add_argument("--seed", type=int, default=260922)
    args = parser.parse_args()

    corpus_path = Path(args.corpus).expanduser().resolve()
    model_path = Path(args.model).expanduser().resolve()
    draft_path = Path(args.draft_model).expanduser().resolve() if args.draft_model else None
    out_dir = Path(args.out_dir).expanduser().resolve()
    if not corpus_path.is_file():
        raise SystemExit("Corpus does not exist: " + str(corpus_path))
    if not model_path.is_dir():
        raise SystemExit("Model directory does not exist: " + str(model_path))
    if draft_path is not None and not draft_path.is_dir():
        raise SystemExit("Draft model directory does not exist: " + str(draft_path))
    if not 1 <= args.num_draft_tokens <= 10:
        raise SystemExit("--num-draft-tokens must be between 1 and 10.")
    if not 1 <= args.candidates <= 4:
        raise SystemExit("--candidates must be between 1 and 4.")

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
    strengths = parse_strengths(args.strengths)
    protected_by_case = extract_app_protected_spans(cases)
    runtime = runtime_info(args.python)

    config = {
        "benchmark": "pari-native-strength-sweep-brutal-v2",
        "corpusPath": portable_repo_path(corpus_path),
        "corpusSha256": sha256_file(corpus_path),
        "caseIds": [case["id"] for case in cases],
        "strengths": strengths,
        "modelPath": portable_model_path(model_path),
        "draftModelPath": portable_model_path(draft_path),
        "numDraftTokens": args.num_draft_tokens if draft_path else None,
        "maxTokens": args.max_tokens,
        "candidates": args.candidates,
        "temperatureOverride": args.temperature,
        "baseSeed": args.seed,
        "generationPath": "native-runtime/paraphrase_worker.py via resident mlx-lm worker",
        "runtime": runtime,
        "nativeWorkerSha256": sha256_file(ROOT / "native-runtime" / "paraphrase_worker.py"),
        "nativeServerSha256": sha256_file(HELPER),
        "protectedExtractorSha256": sha256_file(ROOT / "src" / "lib" / "safety" / "protectedContent.ts"),
        "protectedHelperSha256": sha256_file(PROTECTED_HELPER),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw.jsonl"
    run_path = out_dir / "run.json"
    summary_path = out_dir / "summary.json"
    if run_path.exists():
        previous = json.loads(run_path.read_text(encoding="utf-8"))
        if previous.get("config") != config:
            raise SystemExit("This output directory belongs to a different benchmark configuration; use a new --out-dir.")
    else:
        if raw_path.exists() or summary_path.exists():
            raise SystemExit("Output files exist without run.json; choose a new --out-dir to preserve them.")
        run_path.write_text(
            json.dumps(
                {
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "git": git_snapshot(),
                    "pythonExecutable": Path(args.python).name,
                    "runtime": runtime,
                    "config": config,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    rows = read_rows(raw_path)
    requested_keys = {(case["id"], strength) for case in cases for strength in strengths}
    completed = {(row["caseId"], int(row["strength"])) for row in rows}
    unexpected = completed - requested_keys
    if unexpected:
        raise SystemExit("Checkpoint contains rows outside this configuration; use a new --out-dir.")
    todo = [(case, strength) for case in cases for strength in strengths if (case["id"], strength) not in completed]
    total = len(requested_keys)
    print(
        "[native-brutal-v2] cases="
        + str(len(cases))
        + " strengths="
        + str(len(strengths))
        + " requested="
        + str(total)
        + " complete="
        + str(len(completed))
        + " model="
        + str(model_path),
        flush=True,
    )
    if draft_path:
        print(
            "[native-brutal-v2] draft="
            + str(draft_path)
            + " num_draft_tokens="
            + str(args.num_draft_tokens),
            flush=True,
        )

    command = [args.python, str(HELPER), "--model", str(model_path)]
    if draft_path:
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
            raise RuntimeError(
                "The native worker exited before readiness. Ensure this Python has mlx and mlx-lm installed."
            )
        ready = json.loads(line)
        if ready.get("ready") is not True:
            raise RuntimeError("The native worker did not send its ready handshake.")
        print("[native-brutal-v2] native worker ready: " + str(ready.get("model")), flush=True)

        with raw_path.open("a", encoding="utf-8") as checkpoint:
            for index, (case, strength) in enumerate(todo, start=1):
                seed_digest = hashlib.sha256(
                    (str(args.seed) + ":" + case["id"]).encode("utf-8")
                ).digest()
                seed = int.from_bytes(seed_digest[:4], byteorder="big") & 0x7FFFFFFF
                protected_spans = protected_by_case[case["id"]]
                payload: dict[str, Any] = {
                    "originalText": case["input"],
                    "protectedSpans": [span["text"] for span in protected_spans],
                    "mode": "personal",
                    "strength": strength,
                    "maxTokens": args.max_tokens,
                    "candidates": args.candidates,
                    "numDraftTokens": args.num_draft_tokens,
                }
                if args.temperature is not None:
                    payload["temperature"] = args.temperature
                request_id = "case-" + str(index) + "-" + case["id"] + "-" + str(strength)
                process.stdin.write(
                    json.dumps({"id": request_id, "seed": seed, "payload": payload}, ensure_ascii=False) + "\n"
                )
                process.stdin.flush()
                response_line = process.stdout.readline()
                if not response_line:
                    raise RuntimeError("Native worker exited while generating " + request_id)
                message = json.loads(response_line)
                if message.get("id") != request_id:
                    raise RuntimeError("Native worker response ID mismatch for " + request_id)
                response = message.get("response") or {}
                output = str(response.get("text") or "").strip()
                issues = hard_gate_issues(output, bool(response.get("ok")), protected_spans)
                row = {
                    "caseId": case["id"],
                    "category": case.get("category"),
                    "input": case["input"],
                    "mustPreserve": case.get("mustPreserve", []),
                    "doNotInfer": case.get("doNotInfer", []),
                    "editIntent": case.get("editIntent", ""),
                    "protectedSpans": protected_spans,
                    "strength": strength,
                    "promptRegime": prompt_regime(strength),
                    "modelPath": portable_model_path(model_path),
                    "draftModelPath": portable_model_path(draft_path),
                    "numDraftTokens": args.num_draft_tokens if draft_path else None,
                    "seed": seed,
                    "temperature": response.get("temperature"),
                    "durationMs": int(response.get("duration_ms") or 0),
                    "output": output,
                    "workerOk": bool(response.get("ok")),
                    "workerError": response.get("error"),
                    "hardGateIssues": issues,
                    "hardGatePass": not issues,
                    "lexicalChangeRate": lexical_change_rate(case["input"], output),
                }
                checkpoint.write(json.dumps(row, ensure_ascii=False) + "\n")
                checkpoint.flush()
                rows.append(row)
                if index % 10 == 0 or index == len(todo) or issues:
                    elapsed = time.perf_counter() - started
                    rate = index / max(elapsed, 0.001)
                    remaining_seconds = (len(todo) - index) / max(rate, 0.001)
                    print(
                        "[native-brutal-v2] "
                        + str(len(completed) + index)
                        + "/"
                        + str(total)
                        + " generated; last="
                        + case["id"]
                        + "@"
                        + str(strength)
                        + " "
                        + str(row["durationMs"])
                        + "ms"
                        + (" gate=FAIL " + ",".join(issues) if issues else "")
                        + "; ETA "
                        + str(round(remaining_seconds / 60, 1))
                        + " min",
                        flush=True,
                    )
                if process.poll() is not None:
                    raise RuntimeError("Native worker exited unexpectedly.")
    except KeyboardInterrupt:
        print("\nInterrupted safely; completed rows are checkpointed in " + str(raw_path), file=sys.stderr)
    finally:
        if process.poll() is None:
            try:
                assert process.stdin is not None
                process.stdin.close()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        summary = summarize(rows, total)
        summary["updatedAt"] = datetime.now(timezone.utc).isoformat()
        summary["outputDirectory"] = str(out_dir)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(
            "[native-brutal-v2] checkpoint "
            + str(summary["completedRows"])
            + "/"
            + str(total)
            + "; summary="
            + str(summary_path),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
