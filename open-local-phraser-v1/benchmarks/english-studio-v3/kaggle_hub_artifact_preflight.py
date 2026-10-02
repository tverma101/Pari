#!/usr/bin/env python3
"""Inspect a pinned Hugging Face artifact before spending Kaggle disk/network.

This is a runtime feasibility check only. It does not download model weights,
score English, or mutate the candidate configuration.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("/kaggle/working")
MIN_EXTRA_HEADROOM_BYTES = 4 * 1024**3
HEADROOM_FACTOR = 1.25


def _size_of(sibling: Any) -> int | None:
    size = getattr(sibling, "size", None)
    if isinstance(size, int) and size >= 0:
        return size
    lfs = getattr(sibling, "lfs", None)
    if isinstance(lfs, dict):
        value = lfs.get("size")
        return int(value) if isinstance(value, int) else None
    value = getattr(lfs, "size", None) if lfs is not None else None
    return int(value) if isinstance(value, int) else None


def inspect_hub_artifact(
    repo: str,
    revision: str,
    *,
    filename: str | None = None,
    disk_root: Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        return {
            "status": "dependency_failure",
            "failureCategory": "runtime_import_failure",
            "error": f"huggingface_hub import failed: {type(exc).__name__}: {exc}",
        }

    try:
        info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    except Exception as exc:
        return {
            "status": "metadata_failure",
            "failureCategory": "model_download_failure",
            "repo": repo,
            "requestedRevision": revision,
            "error": f"Hub metadata failed: {type(exc).__name__}: {exc}",
        }

    if info.sha != revision:
        return {
            "status": "revision_mismatch",
            "failureCategory": "artifact_hash_mismatch",
            "repo": repo,
            "requestedRevision": revision,
            "resolvedRevision": info.sha,
        }

    rows: list[dict[str, Any]] = []
    unknown_size: list[str] = []
    selected_bytes = 0
    selected_files = 0
    found_named_file = filename is None
    for sibling in info.siblings or []:
        path = str(getattr(sibling, "rfilename", ""))
        size = _size_of(sibling)
        selected = filename is None or path == filename
        if filename is not None and path == filename:
            found_named_file = True
        if selected:
            selected_files += 1
            if size is None:
                unknown_size.append(path)
            else:
                selected_bytes += size
        rows.append({"path": path, "sizeBytes": size, "selected": selected})

    if not found_named_file:
        return {
            "status": "file_missing",
            "failureCategory": "model_download_failure",
            "repo": repo,
            "revision": revision,
            "filename": filename,
        }

    root = disk_root if disk_root.exists() else Path.cwd()
    disk = shutil.disk_usage(root)
    required_with_headroom = max(
        selected_bytes + MIN_EXTRA_HEADROOM_BYTES,
        math.ceil(selected_bytes * HEADROOM_FACTOR),
    )
    enough_disk = not unknown_size and disk.free >= required_with_headroom
    if unknown_size:
        status = "size_unknown"
        category = "artifact_size_unknown"
    elif not enough_disk:
        status = "insufficient_disk"
        category = "disk_space_failure"
    else:
        status = "qualified"
        category = None

    return {
        "schemaVersion": 1,
        "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "failureCategory": category,
        "repo": repo,
        "revision": revision,
        "filename": filename,
        "selectedFileCount": selected_files,
        "selectedBytes": selected_bytes,
        "unknownSizeFiles": unknown_size,
        "diskRoot": str(root),
        "diskFreeBytes": disk.free,
        "diskTotalBytes": disk.total,
        "requiredWithHeadroomBytes": required_with_headroom,
        "headroomFactor": HEADROOM_FACTOR,
        "minimumExtraHeadroomBytes": MIN_EXTRA_HEADROOM_BYTES,
        "enoughDisk": enough_disk,
        "files": rows,
        "interpretation": [
            "For a single-file GGUF candidate, selectedBytes is the exact pinned file size from Hub metadata when available.",
            "For a Transformers/vLLM repository, the conservative estimate includes all repository files so the benchmark fails early rather than filling Kaggle disk.",
            "A different checkpoint/quantization is a distinct candidate and is never selected automatically to reduce disk use.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("revision")
    ap.add_argument("--file", default=None)
    ap.add_argument("--disk-root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    result = inspect_hub_artifact(
        args.repo,
        args.revision,
        filename=args.file,
        disk_root=args.disk_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "selectedBytes": result.get("selectedBytes"),
        "diskFreeBytes": result.get("diskFreeBytes"),
        "requiredWithHeadroomBytes": result.get("requiredWithHeadroomBytes"),
        "output": str(args.output),
    }, indent=2))
    if result.get("status") != "qualified":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
