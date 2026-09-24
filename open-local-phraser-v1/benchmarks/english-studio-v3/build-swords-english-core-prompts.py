"""Build Pari English Core prompts from an official SWORDS JSON/JSON.GZ file.

This script does not vendor or modify SWORDS data. Download an official SWORDS
benchmark file from https://github.com/p-lambda/swords and pass its path here.

Usage:
    python build-swords-english-core-prompts.py swords-v1.1_test.json.gz swords-prompts.jsonl \
      --swords-revision OFFICIAL_REPO_COMMIT

The output contains model-visible prompts only. Official SWORDS evaluation remains
authoritative and should be run with the SWORDS repository evaluator. For
promotion-quality evidence, pin the official repository/evaluator revision to a
full immutable Git commit SHA and use an official `swords-*.json(.gz)` dataset
filename so the evaluator dataset ID can be cross-checked later.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

UNPINNED = "unrecorded_not_pinned"
GIT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
OFFICIAL_DATASET_ID_RE = re.compile(r"^swords-v[0-9]+(?:\.[0-9]+)*(?:_[A-Za-z0-9-]+)+$")


def read_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset_id_from_filename(path: Path) -> str | None:
    name = path.name
    if name.endswith(".json.gz"):
        candidate = name[:-8]
    elif name.endswith(".json"):
        candidate = name[:-5]
    else:
        return None
    return candidate if OFFICIAL_DATASET_ID_RE.fullmatch(candidate) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("swords_json")
    ap.add_argument("out_jsonl")
    ap.add_argument("--count", type=int, default=40, help="Maximum ranked substitutes requested per target")
    ap.add_argument("--swords-revision", default=None, help="Full 40-hex commit SHA of the official p-lambda/swords checkout used for source/evaluation provenance")
    args = ap.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    source = Path(args.swords_json).resolve()
    if not source.is_file():
        raise SystemExit(f"Missing SWORDS source file: {source}")
    data = read_json(source)
    contexts = data.get("contexts", {})
    targets = data.get("targets", {})
    if not contexts or not targets:
        raise SystemExit("Input does not look like an official SWORDS-format benchmark JSON")

    tasks = []
    for target_id, target in targets.items():
        context_id = target["context_id"]
        if context_id not in contexts:
            raise SystemExit(f"Target {target_id} references missing context {context_id}")
        context = contexts[context_id]["context"]
        target_text = target["target"]
        offset = target.get("offset")
        pos = target.get("pos")
        pos_line = f"\nPart of speech: {pos}" if pos else ""
        prompt = (
            f"Context: {context}\n"
            f"Target text: {target_text}\n"
            f"Target character offset: {offset}{pos_line}\n"
            f"Give up to {args.count} ranked substitutes for the target text that could replace it in this exact context while preserving its intended meaning and grammatical fit. "
            "Do not rewrite the surrounding context. Output only the substitutes, one per line, best first."
        )
        tasks.append({
            "id": target_id,
            "dimension": "lexical_context",
            "source": "SWORDS",
            "task": "lexical_substitution_generation",
            "generative": True,
            "prompt": prompt,
            "metadata": {
                "contextId": context_id,
                "target": target_text,
                "offset": offset,
                "pos": pos,
            },
        })

    ids = [row["id"] for row in tasks]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate SWORDS target IDs encountered")

    out = Path(args.out_jsonl).resolve()
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n")
    source_hash = sha256(source)
    prompt_hash = sha256(out)
    revision = args.swords_revision or UNPINNED
    immutable_revision = bool(GIT_COMMIT_RE.fullmatch(revision))
    dataset_id = dataset_id_from_filename(source)
    promotion_ready = immutable_revision and dataset_id is not None

    manifest = out.with_suffix(out.suffix + ".manifest.json")
    manifest.write_text(json.dumps({
        "version": 4,
        "sourceFile": str(source),
        "sourceSha256": source_hash,
        "officialDatasetId": dataset_id,
        "sourceFilenameMatchesOfficialDatasetIdPattern": dataset_id is not None,
        "promptFile": str(out),
        "promptFileSha256": prompt_hash,
        "targets": len(tasks),
        "requestedCandidates": args.count,
        "officialRepository": "https://github.com/p-lambda/swords",
        "officialRepositoryRevision": revision,
        "officialRepositoryRevisionIsFullCommit": immutable_revision,
        "officialEvaluator": "Use the SWORDS repository evaluator at the recorded immutable revision; Pari does not redefine official SWORDS metrics.",
        "researchReference": "https://aclanthology.org/2021.naacl-main.345/",
        "promotionReadySourceProvenance": promotion_ready,
        "notes": [
            "sourceSha256 pins the exact benchmark JSON/JSON.GZ bytes used to construct prompts.",
            "officialDatasetId is derived only from an official-looking swords-*.json(.gz) filename and is later cross-checked against the pinned SWORDS checkout before evaluation.",
            "promptFileSha256 pins the exact model-visible prompt JSONL.",
            "Promotion-quality evidence requires the official evaluator checkout's full 40-hex commit SHA rather than a mutable branch/tag label.",
            "The official evaluator revision is separate provenance from the benchmark-file hash and must be pinned for promotion-quality comparisons."
        ]
    }, indent=2) + "\n")
    print(json.dumps({
        "targets": len(tasks),
        "out": str(out),
        "sourceSha256": source_hash,
        "officialDatasetId": dataset_id,
        "promptFileSha256": prompt_hash,
        "manifest": str(manifest),
        "officialRepositoryRevision": revision,
        "officialRepositoryRevisionIsFullCommit": immutable_revision,
        "promotionReadySourceProvenance": promotion_ready,
    }, indent=2))


if __name__ == "__main__":
    main()
