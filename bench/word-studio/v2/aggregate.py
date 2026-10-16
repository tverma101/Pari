#!/usr/bin/env python3
"""Verify blind scores against the raw outputs, un-blind and aggregate (#87).

    cd bench/word-studio
    python3 -m v2.aggregate --judging v2/judging/<run-id>

Every score row must cite a task id, an output ref and the raw output's
sha256 that match the sealed key, and the raw file is re-hashed now. The code
checks are recomputed from the raw output, so a row cannot label an option
that failed them or skip one that passed. Any mismatch stops the aggregation
and nothing is written. Metrics are defined in ``v2/RUBRIC.md``.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WORD_STUDIO = HERE.parent
if str(WORD_STUDIO) not in sys.path:
    sys.path.insert(0, str(WORD_STUDIO))

from v2 import blind, build_tasks, hard_checks  # noqa: E402

TOP = 3


class VerificationError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"{len(problems)} problem(s): " + "; ".join(problems[:10]))
        self.problems = problems


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else blind.REPO_ROOT / candidate


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 1)


def latency(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "median_ms": percentile(values, 0.5), "p90_ms": percentile(values, 0.9)}


def verify(judging: Path, scores_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Return (index, key, verified rows) or raise VerificationError."""
    problems: list[str] = []
    index = json.loads((judging / "packets" / "index.json").read_text(encoding="utf-8"))
    key_path = judging / "sealed" / "key.json"
    if blind.sha256_file(key_path) != index["key_sha256"]:
        raise VerificationError(["sealed/key.json does not match the sha256 recorded in packets/index.json"])
    key = json.loads(key_path.read_text(encoding="utf-8"))
    rows = read_jsonl(scores_path)
    if not rows or not rows[0].get("header"):
        raise VerificationError(["scores file must start with a header line"])
    header, rows = rows[0], rows[1:]
    if not header.get("judge") or not header.get("session"):
        problems.append("header must name the judge and the session")
    if header.get("blind") is not True:
        problems.append("header must state blind: true")
    for field in ("rubric_sha256", "key_sha256"):
        if header.get(field) != index[field]:
            problems.append(f"header {field} does not match packets/index.json")
    tasks = {t["id"]: t for t in build_tasks.load_tasks(key["task_set"])}
    expected = {(t, label) for t, labels in key["tasks"].items() for label in labels}
    seen: Counter = Counter((r.get("task_id"), r.get("label")) for r in rows)
    for pair, count in seen.items():
        if pair not in expected:
            problems.append(f"{pair}: not in the key")
        elif count > 1:
            problems.append(f"{pair}: scored {count} times")
    for pair in sorted(expected - set(seen)):
        problems.append(f"{pair}: not scored")
    verified = []
    for row in rows:
        pair = (row.get("task_id"), row.get("label"))
        if pair not in expected or seen[pair] > 1:
            continue
        task_id, label = pair
        sealed = key["tasks"][task_id][label]
        where = f"{task_id} {label}"
        if row.get("output_ref") != sealed["output_ref"]:
            problems.append(f"{where}: output_ref does not match the key")
        if row.get("output_sha256") != sealed["output_sha256"]:
            problems.append(f"{where}: output_sha256 does not match the key")
        raw_path = resolve(sealed["raw_output"])
        if not raw_path.exists():
            problems.append(f"{where}: raw output {sealed['raw_output']} is missing")
            continue
        if blind.sha256_file(raw_path) != sealed["output_sha256"]:
            problems.append(f"{where}: raw output {sealed['raw_output']} changed after packets were built")
            continue
        output = json.loads(raw_path.read_text(encoding="utf-8"))
        checked = hard_checks.check(tasks[task_id], output)
        judged = {str(o["index"] + 1) for o in checked["options"] if o["judge"]}
        relevance = row.get("relevance") or {}
        if set(relevance) != judged:
            extra, missing = sorted(set(relevance) - judged), sorted(judged - set(relevance))
            problems.append(f"{where}: relevance keys wrong (labels code-failed or absent options {extra}, "
                            f"misses judged options {missing})")
        if any(v not in (0, 1, 2) for v in relevance.values()):
            problems.append(f"{where}: relevance labels must be 0, 1 or 2")
        if 0 in relevance.values() and not str(row.get("note") or "").strip():
            problems.append(f"{where}: a 0 label needs a note")
        criteria = row.get("criteria")
        if judged:
            if not isinstance(criteria, dict) or set(criteria) != set(blind.CRITERIA) or any(
                    not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5 for v in criteria.values()):
                problems.append(f"{where}: criteria must give {', '.join(blind.CRITERIA)} each as 1-5")
        elif criteria is not None:
            problems.append(f"{where}: criteria must be null when no option was judged")
        verified.append({"row": row, "sealed": sealed, "checked": checked, "output": output,
                         "kind": tasks[task_id]["kind"]})
    if problems:
        raise VerificationError(problems)
    return index, key, verified


def candidate_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = len(items)
    top = [0, 0, 0]  # at bar in top 1, at bar in top 3, strong in top 3
    usable = strong = slots = 0
    formats: Counter = Counter()
    fails: Counter = Counter()
    warns: Counter = Counter()
    truncated = 0
    criteria: dict[str, list[int]] = defaultdict(list)
    first_text, first_option, third_option, total = [], [], [], []
    by_kind: dict[str, dict[str, Any]] = defaultdict(lambda: {"tasks": 0, "top3_at_bar": 0, "usable": 0})
    citations = []
    for item in items:
        checked, row, output = item["checked"], item["row"], item["output"]
        relevance = {int(k): v for k, v in (row["relevance"] or {}).items()}
        requested = checked["requested"]
        labels = [relevance.get(i, 0) for i in range(1, requested + 1)]
        top3 = labels[:TOP]
        top[0] += labels[0] >= 1
        top[1] += sum(v >= 1 for v in top3)
        top[2] += sum(v == 2 for v in top3)
        usable += sum(v >= 1 for v in labels)
        strong += sum(v == 2 for v in labels)
        slots += requested
        kind = by_kind[item["kind"]]
        kind["tasks"] += 1
        kind["top3_at_bar"] += sum(v >= 1 for v in top3)
        kind["usable"] += sum(v >= 1 for v in labels)
        formats[checked["format"]] += 1
        truncated += checked["truncated"]
        for option in checked["options"]:
            if "beyond_requested" not in option["fail"]:
                fails.update(option["fail"])
                warns.update(option["warn"])
        for name, value in (row["criteria"] or {}).items():
            criteria[name].append(value)
        timing = output.get("timing") or {}
        if output.get("status") == "ok":
            if timing.get("first_text_ms") is not None:
                first_text.append(timing["first_text_ms"])
            option_ms = timing.get("option_ms") or []
            if option_ms:
                first_option.append(option_ms[0])
            if len(option_ms) >= TOP:
                third_option.append(option_ms[TOP - 1])
            total.append(timing["total_ms"])
        citations.append({"task_id": row["task_id"], "output_ref": row["output_ref"],
                          "raw_output": item["sealed"]["raw_output"], "sha256": item["sealed"]["output_sha256"]})
    return {
        "tasks": tasks,
        "top3_at_bar": round(top[1] / (TOP * tasks), 4),
        "top1_at_bar": round(top[0] / tasks, 4),
        "top3_strong": round(top[2] / (TOP * tasks), 4),
        "usable_per_task": round(usable / tasks, 2),
        "strong_share": round(strong / slots, 4),
        "criteria_means": {name: round(statistics.mean(v), 2) for name, v in sorted(criteria.items())},
        "criteria_rows": len(criteria.get("fit", [])),
        "by_kind": {k: {"tasks": v["tasks"], "top3_at_bar": round(v["top3_at_bar"] / (TOP * v["tasks"]), 4),
                        "usable_per_task": round(v["usable"] / v["tasks"], 2)} for k, v in sorted(by_kind.items())},
        "formats": dict(sorted(formats.items())),
        "token_limit_hits": truncated,
        "fail_flags": dict(sorted(fails.items())),
        "warn_flags": dict(sorted(warns.items())),
        "latency_t4": {"first_text": latency(first_text), "first_option": latency(first_option),
                       "third_option": latency(third_option), "whole_output": latency(total)},
        "citations": citations,
    }


def aggregate(judging: Path, scores_path: Path) -> dict[str, Any]:
    index, key, verified = verify(judging, scores_path)
    header = read_jsonl(scores_path)[0]
    per_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in verified:
        per_candidate[item["sealed"]["candidate_id"]].append(item)
    candidates = {}
    for cid, items in sorted(per_candidate.items()):
        meta = key["candidates"][cid]
        if blind.sha256_file(resolve(meta["run_json"])) != meta["run_sha256"]:
            raise VerificationError([f"{meta['run_json']} changed after packets were built"])
        run = json.loads(resolve(meta["run_json"]).read_text(encoding="utf-8"))
        metrics = candidate_metrics(items)
        metrics["run"] = {"status": run["status"], "complete_set": run.get("complete_set"),
                          "run_json": meta["run_json"], "run_sha256": meta["run_sha256"],
                          "model_id": run["candidate"].get("model_id"), "revision": run["candidate"].get("revision"),
                          "load_seconds": (run.get("load") or {}).get("load_seconds"),
                          "peak_memory": run.get("peak_memory")}
        candidates[cid] = metrics
    ranking = sorted(candidates, key=lambda c: (-candidates[c]["top3_at_bar"], -candidates[c]["usable_per_task"], c))
    return {
        "benchmark": "word-studio-v2",
        "run_id": index["run_id"],
        "task_set": index["task_set"],
        "tasks_judged": len(index["tasks"]),
        "judge": {k: header.get(k) for k in ("judge", "session", "blind")},
        "sources": {
            "run_dir": key["run_dir"],
            "packets_index_sha256": blind.sha256_file(judging / "packets" / "index.json"),
            "key_sha256": index["key_sha256"],
            "scores_sha256": blind.sha256_file(scores_path),
            "rubric_sha256_at_judging": index["rubric_sha256"],
            "rubric_unchanged_since": blind.sha256_file(blind.RUBRIC) == index["rubric_sha256"],
            "checks_version": index["checks_version"],
        },
        "ranking": ranking,
        "ranking_rule": "top3_at_bar, then usable_per_task (v2/RUBRIC.md)",
        "candidates": candidates,
        "not_judged": key["not_judged"],
        "aggregated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [f"# Word Studio v2 results: {result['run_id']}", "",
             f"Set `{result['task_set']}`, {result['tasks_judged']} tasks judged blind by "
             f"{result['judge']['judge']} (session `{result['judge']['session']}`). "
             f"Ranked by {result['ranking_rule']}. Latency is Kaggle T4, Transformers fp16, not the Mac.", "",
             "| Candidate | Top-3 at bar | Top-1 at bar | Top-3 strong | Usable / task | Strict JSON | "
             "First option p50 | Third option p50 | Complete set |",
             "|---|---|---|---|---|---|---|---|---|"]
    for cid in result["ranking"]:
        m = result["candidates"][cid]
        lat = m["latency_t4"]
        ms = lambda v: "—" if v is None else f"{v / 1000:.1f} s"  # noqa: E731
        lines.append(f"| {cid} | {m['top3_at_bar']:.1%} | {m['top1_at_bar']:.1%} | {m['top3_strong']:.1%} | "
                     f"{m['usable_per_task']} | {m['formats'].get('strict', 0)}/{m['tasks']} | "
                     f"{ms(lat['first_option']['median_ms'])} | {ms(lat['third_option']['median_ms'])} | "
                     f"{'yes' if m['run']['complete_set'] else 'no'} |")
    if result["not_judged"]:
        lines += ["", "Not judged (run failed):", ""]
        for entry in result["not_judged"]:
            message = ((entry.get("error") or {}).get("message") or "").splitlines()[0][:160] if entry.get(
                "error") else ""
            lines.append(f"- {entry['candidate_id']}: {entry['status']} at {entry.get('stage')}: {message}")
    lines += ["", "Every number above traces to `results.json`, which lists each task id, output ref, raw output "
              "path and sha256 it came from.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--judging", type=Path, required=True, help="v2/judging/<run-id>")
    parser.add_argument("--scores", type=Path, help="default: <judging>/scores.jsonl")
    parser.add_argument("--out", type=Path, help="default: v2/results/<run-id>")
    args = parser.parse_args(argv)
    judging = args.judging.resolve()
    scores = (args.scores or judging / "scores.jsonl").resolve()
    out = (args.out or HERE / "results" / judging.name).resolve()
    if (out / "results.json").exists():
        raise SystemExit(f"{out} already has results; never overwrite evidence")
    try:
        result = aggregate(judging, scores)
    except VerificationError as exc:
        print("verification failed; nothing written:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "results.md").write_text(markdown(result), encoding="utf-8")
    print(markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
