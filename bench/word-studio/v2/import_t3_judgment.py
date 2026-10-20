#!/usr/bin/env python3
"""Import a completed T3 GPT 6.1 Sol blind batch into the frozen score template.

This importer only reads the packet index, anonymized score template, rubric
hash and judge response. It never opens the sealed key or candidate runs.
Unblinding and raw-output verification remain the job of ``v2.aggregate``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

MODEL = "gpt-6.1-sol"
PROVIDER = "t3-code"
EFFORT_LEVEL = "high"
SERVICE_TIER = "standard"
CRITERIA = ("fit", "meaning", "register", "variety", "usefulness")
RUBRIC = Path(__file__).with_name("RUBRIC.md")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(answer: Any, templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate exact task/label coverage and combine scores with frozen citations."""
    if not isinstance(answer, dict) or set(answer) != {"scores"}:
        raise ValueError("response must contain only a scores array")
    scores = answer["scores"]
    if not isinstance(scores, list) or len(scores) != len(templates):
        raise ValueError("response has missing or extra blind outputs")

    expected = {(row["task_id"], row["label"]) for row in templates}
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    required_fields = {"task_id", "label", "criteria", "relevance", "note"}
    for item in scores:
        if (not isinstance(item, dict) or set(item) != required_fields
                or not isinstance(item.get("task_id"), str)
                or not isinstance(item.get("label"), str)):
            raise ValueError("each score must contain only task_id, label, criteria, relevance and note")
        pair = (item["task_id"], item["label"])
        if pair in keyed:
            raise ValueError("duplicate task and label")
        keyed[pair] = item
    if set(keyed) != expected:
        raise ValueError("response task and label set does not match the frozen template")

    result = []
    for row in templates:
        item = keyed[(row["task_id"], row["label"])]
        relevance, criteria, note = item["relevance"], item["criteria"], item["note"]
        if not isinstance(relevance, dict) or set(relevance) != set(row["relevance"]):
            raise ValueError("incorrect relevance indices")
        if any(type(value) is not int or value not in (0, 1, 2) for value in relevance.values()):
            raise ValueError("relevance must be integer 0, 1 or 2")
        if relevance:
            if (not isinstance(criteria, dict) or set(criteria) != set(CRITERIA)
                    or any(type(value) is not int or not 1 <= value <= 5
                           for value in criteria.values())):
                raise ValueError("criteria must score all five rubric categories from 1 to 5")
        elif criteria is not None:
            raise ValueError("criteria must be null when no option was judged")
        if not isinstance(note, str) or (0 in relevance.values() and not note.strip()):
            raise ValueError("a relevance zero needs an explanatory note")
        result.append(dict(row, criteria=criteria, relevance=relevance, note=note))
    return result


def run(
    judging: Path,
    response_path: Path,
    *,
    provider_instance_id: str,
    delegated_task_id: str,
    child_run_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    judging, response_path = Path(judging), Path(response_path)
    index_path = judging / "packets" / "index.json"
    template_path = judging / "scores.template.jsonl"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    template = load_jsonl(template_path)
    if not template or template[0].get("header") is not True:
        raise ValueError("frozen score template has no header")
    header = template[0]
    if (sha(index_path) != header.get("packets_index_sha256")
            or sha(RUBRIC) != index.get("rubric_sha256")
            or index.get("rubric_sha256") != header.get("rubric_sha256")
            or index.get("key_sha256") != header.get("key_sha256")):
        raise ValueError("frozen rubric/index/key commitment mismatch")

    task_ids = index.get("tasks")
    packet_hashes = index.get("packet_hashes")
    if (not isinstance(task_ids, list) or len(task_ids) != len(set(task_ids))
            or not isinstance(packet_hashes, dict) or set(packet_hashes) != set(task_ids)):
        raise ValueError("packet index task and packet hash sets are invalid")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in template[1:]:
        if row.get("task_id") not in task_ids:
            raise ValueError("score template contains a task absent from packet index")
        groups[row["task_id"]].append(row)
    if (set(groups) != set(task_ids)
            or any(len(groups[task_id]) != index.get("outputs_per_task") for task_id in task_ids)):
        raise ValueError("frozen score template is incomplete")
    for task_id in task_ids:
        if not isinstance(task_id, str) or "/" in task_id or "\\" in task_id or ".." in task_id:
            raise ValueError("unsafe task ID in packet index")
        packet_path = judging / "packets" / (task_id + ".md")
        if not packet_path.is_file() or sha(packet_path) != packet_hashes[task_id]:
            raise ValueError("packet changed or missing: " + task_id)

    for name, value in (("provider instance ID", provider_instance_id),
                        ("delegated task ID", delegated_task_id), ("child run ID", child_run_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("missing " + name)
    response_bytes = response_path.read_bytes()
    response = json.loads(response_bytes)
    scored_rows = validate(response, template[1:])

    output = judging / "scores.jsonl"
    receipt_path = judging / "judge-session-receipt.json"
    if output.exists() or receipt_path.exists():
        raise FileExistsError("refusing to overwrite existing judged evidence")
    sessions = {task_id: child_run_id for task_id in task_ids}
    session_digest = hashlib.sha256(json.dumps(sessions, sort_keys=True).encode("utf-8")).hexdigest()
    result_header = dict(header, judge=MODEL, provider=PROVIDER,
                         provider_instance_id=provider_instance_id,
                         delegated_task_id=delegated_task_id, child_run_id=child_run_id,
                         session="batch:" + session_digest, effort_level=EFFORT_LEVEL,
                         service_tier=SERVICE_TIER)
    rows = [result_header, *scored_rows]
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    receipt = {
        "schema_version": 1,
        "provider": PROVIDER,
        "provider_instance_id": provider_instance_id,
        "model": MODEL,
        "effort_level": EFFORT_LEVEL,
        "service_tier": SERVICE_TIER,
        "delegated_task_id": delegated_task_id,
        "child_run_id": child_run_id,
        "sessions": sessions,
        "input_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "packet_index_sha256": sha(index_path),
        "scores_sha256": hashlib.sha256(payload).hexdigest(),
    }
    if dry_run:
        return {"tasks": len(task_ids), "blind_outputs": len(scored_rows), "wrote_scores": False}

    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix=".t3-judge-import-", dir=judging) as temp_dir:
        temp = Path(temp_dir)
        scores_temp = temp / "scores.jsonl"
        receipt_temp = temp / "judge-session-receipt.json"
        scores_temp.write_bytes(payload)
        receipt_temp.write_bytes(receipt_bytes)
        os.replace(scores_temp, output)
        os.replace(receipt_temp, receipt_path)
    return {"tasks": len(task_ids), "blind_outputs": len(scored_rows), "wrote_scores": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judging", required=True, type=Path)
    parser.add_argument("--response", required=True, type=Path,
                        help="JSON response returned by the completed GPT 6.1 Sol task")
    parser.add_argument("--provider-instance-id", required=True)
    parser.add_argument("--delegated-task-id", required=True)
    parser.add_argument("--child-run-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.judging, args.response,
                     provider_instance_id=args.provider_instance_id,
                     delegated_task_id=args.delegated_task_id,
                     child_run_id=args.child_run_id,
                     dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, FileNotFoundError, FileExistsError, json.JSONDecodeError) as error:
        parser.exit(2, f"Fail closed; no fallback scores were written: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
