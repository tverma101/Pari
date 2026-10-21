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
import hashlib
import json
import math
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

from v2 import blind, build_tasks, hard_checks, run_candidate  # noqa: E402

TOP = 3
# Two-sided 95% Student t quantiles. Between rows the lower df is used, which
# widens the interval slightly rather than narrowing it.
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
       9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042,
       40: 2.021, 60: 2.000, 120: 1.980}
SUPPORTED_JUDGE_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}
T3_GPT_MODEL = "gpt-6.1-sol"
SUBAGENT_PREFIX = "claude-subagent:"
SUBAGENT_PROVIDER = "claude-code-subagent"


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


def verify(judging: Path, scores_path: Path) -> tuple[
        dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], Path]:
    """Return frozen index, key, verified rows, judge receipt and receipt path."""
    problems: list[str] = []
    index_path = judging / "packets" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
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
    header_effort = header.get("effort_level")
    if not isinstance(header_effort, str) or header_effort not in SUPPORTED_JUDGE_EFFORT_LEVELS:
        problems.append("header must record a fixed supported judge effort level")
    if header.get("blind") is not True:
        problems.append("header must state blind: true")
    for field in ("rubric_sha256", "key_sha256"):
        if header.get(field) != index[field]:
            problems.append(f"header {field} does not match packets/index.json")
    if header.get("packets_index_sha256") != blind.sha256_file(index_path):
        problems.append("packets/index.json changed after the score template was created")
    judge = header.get("judge")
    if isinstance(judge, str) and judge.startswith("claude:"):
        receipt_path = judging / "claude-session-receipt.json"
        receipt_kind = "claude"
    elif isinstance(judge, str) and judge.startswith(SUBAGENT_PREFIX):
        receipt_path = judging / "judge-session-receipt.json"
        receipt_kind = "claude_subagent"
    elif judge == T3_GPT_MODEL:
        receipt_path = judging / "judge-session-receipt.json"
        receipt_kind = "t3"
    else:
        receipt_path = judging / "judge-session-receipt.json"
        receipt_kind = "unsupported"
        problems.append(f"unsupported judge identity: {judge!r}")
    receipt: dict[str, Any] = {}
    try:
        loaded_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if isinstance(loaded_receipt, dict):
            receipt = loaded_receipt
        else:
            problems.append("judge session receipt must be a JSON object")
    except (OSError, json.JSONDecodeError):
        problems.append("judge session receipt is missing or invalid")
    model = receipt.get("model")
    if (not isinstance(model, str) or not model
            or (receipt_kind == "claude" and judge != "claude:" + model)
            or (receipt_kind == "claude_subagent" and judge != SUBAGENT_PREFIX + model)
            or (receipt_kind == "t3" and model != judge)):
        problems.append("judge session receipt model does not match the score header")
    if receipt_kind == "claude_subagent":
        if receipt.get("provider") != SUBAGENT_PROVIDER or header.get("provider") != SUBAGENT_PROVIDER:
            problems.append("subagent judge provider does not match the score header")
        if not isinstance(receipt.get("model_verified"), bool):
            problems.append("subagent judge receipt must say whether the model was verified")
        answers = receipt.get("answers_sha256")
        if not isinstance(answers, dict) or set(answers) != set(index.get("tasks", [])):
            problems.append("subagent judge receipt must hash one saved answer per judged task")
        else:
            for task_id, digest in sorted(answers.items()):
                path = judging / "subagent-answers" / f"{task_id}.json"
                if not path.is_file() or blind.sha256_file(path) != digest:
                    problems.append(f"subagent answer for {task_id} is missing or changed")
    effort_level = receipt.get("effort_level")
    if not isinstance(effort_level, str) or effort_level not in SUPPORTED_JUDGE_EFFORT_LEVELS:
        problems.append("judge session receipt must record a fixed supported effort level")
    if header.get("effort_level") not in (None, effort_level):
        problems.append("score header effort level does not match the judge session receipt")
    if receipt_kind == "t3":
        if receipt.get("schema_version") != 1:
            problems.append("T3 judge receipt schema version must be 1")
        if receipt.get("provider") != "t3-code" or header.get("provider") != receipt.get("provider"):
            problems.append("T3 judge provider does not match the score header")
        if effort_level != "high":
            problems.append("GPT 6.1 Sol score receipt must record high effort")
        if receipt.get("service_tier") != "standard" or header.get("service_tier") != "standard":
            problems.append("GPT 6.1 Sol score receipt must record standard service tier")
        for field in ("provider_instance_id", "delegated_task_id", "child_run_id"):
            value = receipt.get(field)
            if not isinstance(value, str) or not value:
                problems.append(f"T3 judge receipt must record {field}")
            if header.get(field) != value:
                problems.append(f"T3 judge receipt {field} does not match the score header")
        input_hash = receipt.get("input_sha256")
        try:
            valid_input_hash = isinstance(input_hash, str) and len(input_hash) == 64 and int(input_hash, 16) >= 0
        except ValueError:
            valid_input_hash = False
        if not valid_input_hash:
            problems.append("T3 judge receipt must bind the original response SHA-256")
    sessions = receipt.get("sessions")
    if (not isinstance(sessions, dict) or set(sessions) != set(index.get("tasks", []))
            or any(not isinstance(value, str) or not value for value in sessions.values())):
        problems.append("judge session receipt must contain one session ID per judged task")
    else:
        session_digest = hashlib.sha256(json.dumps(sessions, sort_keys=True).encode()).hexdigest()
        if header.get("session") != "batch:" + session_digest:
            problems.append("judge session receipt sessions do not match the score header")
        if receipt_kind == "t3" and any(value != receipt.get("child_run_id") for value in sessions.values()):
            problems.append("T3 judge session IDs must match the recorded child run")
    if receipt.get("packet_index_sha256") != blind.sha256_file(index_path):
        problems.append("judge session receipt packet index hash does not match")
    if receipt.get("scores_sha256") != blind.sha256_file(scores_path):
        problems.append("judge session receipt score hash does not match")
    if receipt_kind == "claude":
        receipt["provider"] = "claude-code"
    if blind.sha256_file(blind.RUBRIC) != index["rubric_sha256"]:
        problems.append("current RUBRIC.md changed after the judging packets were built")
    packet_hashes = index.get("packet_hashes")
    task_ids = set(index["tasks"])
    if not isinstance(packet_hashes, dict) or set(packet_hashes) != task_ids:
        problems.append("packet hash list does not match the task list in packets/index.json")
    else:
        for task_id in sorted(task_ids):
            packet_path = judging / "packets" / f"{task_id}.md"
            if not packet_path.is_file():
                problems.append(f"packet {task_id} is missing")
            elif blind.sha256_file(packet_path) != packet_hashes[task_id]:
                problems.append(f"packet {task_id} changed after packets/index.json was created")
    if index["checks_version"] != hard_checks.CHECKS_VERSION:
        problems.append(f"packets were built with {index['checks_version']}, the code checks are now "
                        f"{hard_checks.CHECKS_VERSION}")
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
        if output.get("messages_sha256") != run_candidate.messages_digest(tasks[task_id]["messages"]):
            problems.append(f"{where}: the output was generated from different messages than task {task_id} has now")
            continue
        checked = hard_checks.check(tasks[task_id], output)
        judged = {str(o["index"] + 1) for o in checked["options"] if o["judge"]}
        relevance = row.get("relevance") or {}
        if set(relevance) != judged:
            extra, missing = sorted(set(relevance) - judged), sorted(judged - set(relevance))
            problems.append(f"{where}: relevance keys wrong (labels code-failed or absent options {extra}, "
                            f"misses judged options {missing})")
        if any(not isinstance(v, int) or isinstance(v, bool) or v not in (0, 1, 2)
               for v in relevance.values()):
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
    return index, key, verified, receipt, receipt_path


def top3_share(item: dict[str, Any]) -> float:
    """One task's share of top-3 positions at the bar; its mean is ``top3_at_bar``."""
    relevance = {int(k): v for k, v in (item["row"]["relevance"] or {}).items()}
    return sum(relevance.get(i, 0) >= 1 for i in range(1, TOP + 1)) / TOP


def clustered_mean(values: dict[str, float], cluster_of: dict[str, str]) -> dict[str, Any]:
    """Mean with a cluster-robust standard error and a t-based 95% interval.

    Tasks that share a source paragraph are not independent, so the error is
    clustered by paragraph (Miller 2024, "Adding Error Bars to Evals",
    arXiv:2411.00640), with the G/(G-1) small-sample correction and G-1
    degrees of freedom because there are few paragraphs.
    """
    n = len(values)
    mean = sum(values.values()) / n
    sums: dict[str, float] = defaultdict(float)
    for task_id, value in values.items():
        sums[cluster_of[task_id]] += value - mean
    g = len(sums)
    out: dict[str, Any] = {"mean": round(mean, 4), "n": n, "clusters": g, "se": None, "ci95": None}
    if g >= 2:
        se = math.sqrt(g / (g - 1) * sum(v * v for v in sums.values())) / n
        half = T95[max(k for k in T95 if k <= g - 1)] * se
        out.update(se=round(se, 4), ci95=[round(mean - half, 4), round(mean + half, 4)])
    return out


def uncertainty(per_task: dict[str, dict[str, float]], ranking: list[str],
                cluster_of: dict[str, str]) -> dict[str, Any]:
    """Interval for each candidate's top-3 at bar, and the paired gap to the leader.

    The gap is paired by task (each task scored for both candidates), which
    removes task difficulty from the comparison. A gap whose interval spans 0
    is not separable from the leader on this task set.
    """
    result: dict[str, Any] = {
        "metric": "top3_at_bar",
        "method": "per-task mean, standard error clustered by source paragraph, t interval with "
                  "clusters-1 df (Miller 2024, arXiv:2411.00640)",
        "candidates": {cid: clustered_mean(per_task[cid], cluster_of) for cid in ranking},
        "leader": ranking[0] if ranking else None,
        "gap_to_leader": {},
    }
    for cid in ranking[1:]:
        shared = per_task[ranking[0]].keys() & per_task[cid].keys()
        gap = clustered_mean({t: per_task[ranking[0]][t] - per_task[cid][t] for t in shared}, cluster_of)
        gap["separable"] = gap["ci95"] is not None and gap["ci95"][0] > 0
        result["gap_to_leader"][cid] = gap
    return result


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


def by_candidate(verified: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Judged outputs per candidate. Anchors are re-judged old outputs, so they never count."""
    per_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in verified:
        if not item["sealed"].get("anchor"):
            per_candidate[item["sealed"]["candidate_id"]].append(item)
    return per_candidate


def candidate_result(items: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    if blind.sha256_file(resolve(meta["run_json"])) != meta["run_sha256"]:
        raise VerificationError([f"{meta['run_json']} changed after packets were built"])
    run = json.loads(resolve(meta["run_json"]).read_text(encoding="utf-8"))
    metrics = candidate_metrics(items)
    metrics["run"] = {"status": run["status"], "complete_set": run.get("complete_set"),
                      "run_json": meta["run_json"], "run_sha256": meta["run_sha256"],
                      "model_id": run["candidate"].get("model_id"), "revision": run["candidate"].get("revision"),
                      "load_seconds": (run.get("load") or {}).get("load_seconds"),
                      "peak_memory": run.get("peak_memory")}
    return metrics


def rank(candidates: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(candidates, key=lambda c: (-candidates[c]["top3_at_bar"], -candidates[c]["usable_per_task"], c))


def anchor_agreement(verified: list[dict[str, Any]]) -> dict[str, Any] | None:
    """How this judging's labels on anchors compare with their original judging.

    Low agreement means scores from the two judgings should not be pooled
    (``v2.leaderboard``) without re-judging.
    """
    anchors = [item for item in verified if item["sealed"].get("anchor")]
    if not anchors:
        return None
    originals: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    options = same_label = same_bar = 0
    shifts, citations = [], []
    for item in anchors:
        source = item["sealed"]["anchor"]
        if source["judging"] not in originals:
            judging = resolve(source["judging"])
            original_rows = verify(judging, judging / "scores.jsonl")[2]
            originals[source["judging"]] = {(i["row"]["task_id"], i["row"]["label"]): i for i in original_rows}
        original = originals[source["judging"]].get((source["task_id"], source["label"]))
        if original is None or original["sealed"]["output_sha256"] != item["sealed"]["output_sha256"]:
            raise VerificationError([f"anchor {item['row']['task_id']} {item['row']['label']} does not match "
                                     f"its original in {source['judging']}"])
        new, old = item["row"]["relevance"] or {}, original["row"]["relevance"] or {}
        for option, label in new.items():
            options += 1
            same_label += label == old.get(option)
            same_bar += (label >= 1) == ((old.get(option) or 0) >= 1)
        shifts.append(top3_share(item) - top3_share(original))
        citations.append({"task_id": item["row"]["task_id"], "label": item["row"]["label"],
                          "original": source, "sha256": item["sealed"]["output_sha256"]})
    return {
        "anchors": len(anchors),
        "options": options,
        "label_agreement": round(same_label / options, 4) if options else None,
        "bar_agreement": round(same_bar / options, 4) if options else None,
        "top3_shift_mean": round(sum(shifts) / len(shifts), 4),
        "citations": citations,
    }


def aggregate(judging: Path, scores_path: Path) -> dict[str, Any]:
    index, key, verified, receipt, receipt_path = verify(judging, scores_path)
    header = read_jsonl(scores_path)[0]
    per_candidate = by_candidate(verified)
    candidates = {cid: candidate_result(items, key["candidates"][cid]) for cid, items in sorted(per_candidate.items())}
    ranking = rank(candidates)
    all_tasks = build_tasks.load_tasks(index["task_set"])
    task_ids = [task["id"] for task in all_tasks]
    cluster_of = {task["id"]: task["paragraph_id"] for task in all_tasks}
    per_task = {cid: {item["row"]["task_id"]: top3_share(item) for item in items}
                for cid, items in per_candidate.items()}
    task_selection = index.get("task_selection", "legacy_unspecified")
    task_set_complete = index.get("task_set_complete", index["tasks"] == task_ids)
    result = {
        "benchmark": "word-studio-v2",
        "run_id": index["run_id"],
        "task_set": index["task_set"],
        "task_selection": task_selection,
        "task_set_complete": task_set_complete,
        "tasks_judged": len(index["tasks"]),
        "judge": {**{k: header.get(k) for k in ("judge", "session", "blind", "effort_level")},
                  "provider": receipt.get("provider"),
                  "model_verified": receipt.get("model_verified", receipt.get("provider") == "claude-code"),
                  "provider_instance_id": receipt.get("provider_instance_id"),
                  "delegated_task_id": receipt.get("delegated_task_id"),
                  "child_run_id": receipt.get("child_run_id")},
        "anchor_agreement": anchor_agreement(verified),
        "sources": {
            "run_dir": key["run_dir"],
            "judge_receipt_sha256": blind.sha256_file(receipt_path),
            "packets_index_sha256": blind.sha256_file(judging / "packets" / "index.json"),
            "key_sha256": index["key_sha256"],
            "scores_sha256": blind.sha256_file(scores_path),
            "rubric_sha256_at_judging": index["rubric_sha256"],
            "rubric_unchanged_since": blind.sha256_file(blind.RUBRIC) == index["rubric_sha256"],
            "checks_version": index["checks_version"],
        },
        "ranking": ranking,
        "ranking_rule": "top3_at_bar, then usable_per_task (v2/RUBRIC.md)",
        "uncertainty": uncertainty(per_task, ranking, cluster_of),
        "candidates": candidates,
        "not_judged": key["not_judged"],
        "aggregated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if receipt_path.name == "claude-session-receipt.json":
        result["sources"]["claude_receipt_sha256"] = result["sources"]["judge_receipt_sha256"]
    return result


def markdown(result: dict[str, Any]) -> str:
    lines = [f"# Word Studio v2 results: {result['run_id']}", "",
             f"Set `{result['task_set']}`, {result['tasks_judged']} tasks judged blind "
             f"({result['task_selection']}; complete task set: {str(result['task_set_complete']).lower()}) by "
             f"{result['judge']['judge']} via `{result['judge']['provider']}`"
             f"{'' if result['judge'].get('model_verified', True) else ' (model not verified per call)'} "
             f"at `{result['judge']['effort_level']}` effort "
             f"(session `{result['judge']['session']}`). "
             f"Ranked by {result['ranking_rule']}. Latency is Kaggle T4, Transformers fp16, not the Mac.", "",
             "| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Top-1 at bar | Top-3 strong | "
             "Usable / task | Strict JSON | First option p50 | Third option p50 | Complete set |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    spread = result["uncertainty"]
    pct = lambda pair: "—" if pair is None else f"{pair[0]:.1%} to {pair[1]:.1%}"  # noqa: E731
    for cid in result["ranking"]:
        m = result["candidates"][cid]
        lat = m["latency_t4"]
        ms = lambda v: "—" if v is None else f"{v / 1000:.1f} s"  # noqa: E731
        gap = spread["gap_to_leader"].get(cid)
        gap_text = "leader" if gap is None else (
            f"{gap['mean']:+.1%} ({pct(gap['ci95'])}){'' if gap['separable'] else ', not separable'}")
        lines.append(f"| {cid} | {m['top3_at_bar']:.1%} | {pct(spread['candidates'][cid]['ci95'])} | {gap_text} | "
                     f"{m['top1_at_bar']:.1%} | {m['top3_strong']:.1%} | "
                     f"{m['usable_per_task']} | {m['formats'].get('strict', 0)}/{m['tasks']} | "
                     f"{ms(lat['first_option']['median_ms'])} | {ms(lat['third_option']['median_ms'])} | "
                     f"{'yes' if m['run']['complete_set'] else 'no'} |")
    if result["not_judged"]:
        lines += ["", "Not judged (run failed):", ""]
        for entry in result["not_judged"]:
            message = ((entry.get("error") or {}).get("message") or "").splitlines()[0][:160] if entry.get(
                "error") else ""
            lines.append(f"- {entry['candidate_id']}: {entry['status']} at {entry.get('stage')}: {message}")
    anchors = result.get("anchor_agreement")
    if anchors:
        lines += ["", f"Drift anchors: {anchors['anchors']} already-judged outputs were judged again blind. "
                  f"Same label on {anchors['label_agreement']:.1%} of {anchors['options']} options, same side of "
                  f"the bar on {anchors['bar_agreement']:.1%}; top-3 at bar moved {anchors['top3_shift_mean']:+.1%} "
                  "on average."]
    lines += ["", f"Intervals: {spread['method']}. \"Not separable\" means the paired gap's interval "
              "includes 0, so this task set cannot tell that candidate from the leader."]
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
