#!/usr/bin/env python3
"""Assemble the frozen 1,943-case model-visible English Core screen.

This concatenates already-built lane task files without changing their prompts,
order, labels, or benchmark weighting. Gold files are never opened or copied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANES = (
    ("shadow", "english-core-shadow.jsonl", 68, "author_labeled_unvalidated"),
    ("public_fast", "english-core-public-fast.jsonl", 1570, "public_prompted_fast"),
    ("semanticqa_lcc", "semanticqa-lcc-english-core.jsonl", 305, "public_prompted_native_protocol"),
)
GOLD_KEYS = {"answer", "answers", "label", "gold", "correct", "correct_answer", "expected"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=HERE / "english-core-fixed-screen.jsonl")
    ap.add_argument("--manifest", type=Path, default=HERE / "english-core-fixed-screen.manifest.json")
    args = ap.parse_args()

    task_lines: list[str] = []
    seen: set[str] = set()
    lane_records = []
    for lane, filename, expected_count, evidence_status in LANES:
        source_path = HERE / filename
        if not source_path.is_file():
            raise SystemExit(f"Missing {source_path}; build each lane with its documented pinned source first")
        source_bytes = source_path.read_bytes()
        lines = [line for line in source_bytes.decode("utf-8").splitlines() if line.strip()]
        if len(lines) != expected_count:
            raise SystemExit(f"{lane}: expected {expected_count} cases, got {len(lines)}")
        lane_ids = []
        for line_number, line in enumerate(lines, 1):
            row = json.loads(line)
            if not isinstance(row, dict) or not row.get("id") or not isinstance(row.get("prompt"), str):
                raise SystemExit(f"{lane}:{line_number}: task needs a non-empty id and prompt")
            leaked = sorted(GOLD_KEYS.intersection(row))
            if leaked:
                raise SystemExit(f"{lane}:{line_number}: gold-bearing task fields are forbidden: {leaked}")
            task_id = row["id"]
            if task_id in seen:
                raise SystemExit(f"Duplicate task ID across lanes: {task_id}")
            seen.add(task_id)
            lane_ids.append(task_id)
            task_lines.append(line)
        lane_records.append({
            "lane": lane,
            "sourceFile": filename,
            "taskFileSha256": sha256_bytes(source_bytes),
            "cases": len(lines),
            "evidenceStatus": evidence_status,
            "taskIds": lane_ids,
        })

    combined = ("\n".join(task_lines) + "\n").encode("utf-8")
    if len(seen) != 1943:
        raise SystemExit(f"Frozen fixed screen must contain exactly 1,943 unique cases; got {len(seen)}")
    atomic_write(args.output, combined)
    manifest = {
        "version": 1,
        "screen": "english_studio_v3_fixed_1943",
        "cases": len(seen),
        "taskFile": str(args.output.resolve()),
        "taskFileSha256": sha256_bytes(combined),
        "sourcePolicy": "evaluation only; never train on these rows or tune prompts/weights after seeing results",
        "assemblyPolicy": "lane JSONL rows concatenated byte-for-byte after newline parsing; no prompt, option, or weighting changes",
        "modelVisibleOnly": True,
        "goldPolicy": "answer keys remain in lane-specific files and are never read or included by this builder",
        "lanes": lane_records,
    }
    atomic_write(args.manifest, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"cases": len(seen), "taskFileSha256": manifest["taskFileSha256"], "lanes": {r["lane"]: r["cases"] for r in lane_records}}, indent=2))


if __name__ == "__main__":
    main()
