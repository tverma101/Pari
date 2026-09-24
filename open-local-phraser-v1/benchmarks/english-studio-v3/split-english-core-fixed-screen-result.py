#!/usr/bin/env python3
"""Split one fixed-screen model run back into the original scoring lanes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def output_hash(outputs: list[dict]) -> str:
    canonical = json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256_bytes(canonical)


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
    ap.add_argument("result", type=Path)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()

    run = json.loads(args.result.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("cases") != 1943 or run.get("taskCount") != 1943:
        raise SystemExit("Parent run and manifest must both describe the complete 1,943-case screen")
    if run.get("taskFileSha256") != manifest.get("taskFileSha256"):
        raise SystemExit("Parent result hash does not match the fixed-screen manifest")
    outputs = run.get("outputs")
    if not isinstance(outputs, list):
        raise SystemExit("Parent result outputs must be an array")
    output_map = {row.get("id"): row for row in outputs if isinstance(row, dict)}
    if len(output_map) != len(outputs):
        raise SystemExit("Parent result contains malformed or duplicate output IDs")
    expected_all = {task_id for lane in manifest.get("lanes", []) for task_id in lane.get("taskIds", [])}
    if set(output_map) != expected_all:
        raise SystemExit(f"Parent result coverage mismatch: missing={len(expected_all - set(output_map))} extra={len(set(output_map) - expected_all)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str((run.get("model") or {}).get("name", "model"))).strip("-") or "model"
    completed = []
    for lane in manifest["lanes"]:
        lane_ids = lane["taskIds"]
        lane_path = args.manifest.parent / lane["sourceFile"]
        lane_bytes = lane_path.read_bytes()
        if sha256_bytes(lane_bytes) != lane["taskFileSha256"]:
            raise SystemExit(f"Source lane changed since assembly: {lane_path}")
        lane_outputs = [output_map[task_id] for task_id in lane_ids]
        split = copy.deepcopy(run)
        split["taskFile"] = str(lane_path.resolve())
        split["taskFileSha256"] = lane["taskFileSha256"]
        split["taskCount"] = len(lane_ids)
        split["outputs"] = lane_outputs
        split.setdefault("reproducibility", {})["rawOutputSha256"] = output_hash(lane_outputs)
        split["reproducibility"].setdefault("notes", []).append(
            f"Lane outputs split from complete fixed-screen parent {args.result.name}; lane task bytes/hash remain unchanged."
        )
        out_path = args.output_dir / f"{safe_name}.{lane['lane']}.json"
        atomic_write(out_path, (json.dumps(split, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        completed.append({"lane": lane["lane"], "path": str(out_path.resolve()), "cases": len(lane_ids), "rawOutputSha256": split["reproducibility"]["rawOutputSha256"]})
    print(json.dumps({"parentResultSha256": sha256_bytes(args.result.read_bytes()), "lanes": completed}, indent=2))


if __name__ == "__main__":
    main()
