"""Build English Core prompts from an official JFLEG `.src` file.

Download JFLEG from https://github.com/keisks/jfleg and pass `dev/dev.src` or
`test/test.src`. Benchmark data is not vendored into Pari.

Exploration:
    python build-jfleg-english-core-prompts.py /path/to/jfleg/dev/dev.src jfleg-dev-prompts.jsonl

Promotion-quality provenance should also pin the official repository revision and
all four reference files used by JFLEG's official GLEU evaluator:
    python build-jfleg-english-core-prompts.py /path/to/jfleg/dev/dev.src jfleg-dev-prompts.jsonl \
      --jfleg-revision OFFICIAL_REPO_COMMIT \
      --reference /path/to/jfleg/dev/dev.ref0 \
      --reference /path/to/jfleg/dev/dev.ref1 \
      --reference /path/to/jfleg/dev/dev.ref2 \
      --reference /path/to/jfleg/dev/dev.ref3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

UNPINNED = "unrecorded_not_pinned"
GIT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_file")
    ap.add_argument("out_jsonl")
    ap.add_argument("--jfleg-revision", default=None, help="Full 40-hex commit SHA of the official keisks/jfleg checkout for promotion-quality provenance")
    ap.add_argument("--reference", action="append", default=[], help="Reference file used by official GLEU; pass all four for promotion-quality provenance")
    args = ap.parse_args()

    source = Path(args.source_file).resolve()
    if not source.is_file():
        raise SystemExit(f"Missing JFLEG source file: {source}")
    refs = [Path(value).resolve() for value in args.reference]
    for ref in refs:
        if not ref.is_file():
            raise SystemExit(f"Missing JFLEG reference file: {ref}")
    if len(refs) != len(set(refs)):
        raise SystemExit("JFLEG reference arguments must be distinct files")

    lines = source.read_text().splitlines()
    if not lines:
        raise SystemExit("JFLEG source file contains no lines")

    reference_records = []
    reference_hashes: set[str] = set()
    for ref in refs:
        ref_lines = ref.read_text().splitlines()
        if len(ref_lines) != len(lines):
            raise SystemExit(f"Reference line count mismatch: {ref} has {len(ref_lines)} lines; source has {len(lines)}")
        ref_hash = sha256(ref)
        if ref_hash in reference_hashes:
            raise SystemExit(f"JFLEG references must not be byte-identical duplicates: {ref}")
        reference_hashes.add(ref_hash)
        reference_records.append({
            "path": str(ref),
            "sha256": ref_hash,
            "lines": len(ref_lines),
        })

    tasks = []
    for i, text in enumerate(lines):
        prompt = (
            "Improve the sentence so it is grammatical and fluent natural English. "
            "Preserve its intended meaning and information. Make only changes that improve correctness or fluency. "
            "Output only the revised sentence.\n"
            f"Sentence: {text}"
        )
        tasks.append({
            "id": f"jfleg-{i:04d}",
            "dimension": "fluency_register",
            "source": "JFLEG",
            "task": "fluency_correction",
            "generative": True,
            "prompt": prompt,
            "metadata": {"line": i},
        })

    out = Path(args.out_jsonl).resolve()
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n")
    revision = args.jfleg_revision or UNPINNED
    immutable_revision = bool(GIT_COMMIT_RE.fullmatch(revision))
    promotion_ready = immutable_revision and len(reference_records) == 4

    manifest = out.with_suffix(out.suffix + ".manifest.json")
    manifest.write_text(json.dumps({
        "version": 3,
        "sourceFile": str(source),
        "sourceSha256": sha256(source),
        "sourceLines": len(lines),
        "promptFile": str(out),
        "promptFileSha256": sha256(out),
        "cases": len(tasks),
        "references": reference_records,
        "officialRepository": "https://github.com/keisks/jfleg",
        "officialRepositoryRevision": revision,
        "officialRepositoryRevisionIsFullCommit": immutable_revision,
        "officialMetric": "GLEU using the repository eval/gleu.py script with the four pinned references",
        "researchReference": "https://aclanthology.org/E17-2037/",
        "promotionReadySourceProvenance": promotion_ready,
        "protocolNote": "Pari only adapts model I/O; official JFLEG references and GLEU remain authoritative.",
        "notes": [
            "For promotion-quality evidence, pin exactly the four distinct references used in the official GLEU command and the official repository's full 40-hex commit SHA.",
            "Reference line counts are checked against the source and duplicate reference paths/bytes are rejected to prevent split/file mismatches.",
            "The prompt-file hash cross-links this source/reference bundle to the exact model-visible task file."
        ]
    }, indent=2) + "\n")
    print(json.dumps({
        "cases": len(tasks),
        "out": str(out),
        "manifest": str(manifest),
        "sourceSha256": sha256(source),
        "promptFileSha256": sha256(out),
        "referenceFiles": len(reference_records),
        "officialRepositoryRevision": revision,
        "officialRepositoryRevisionIsFullCommit": immutable_revision,
        "promotionReadySourceProvenance": promotion_ready,
    }, indent=2))


if __name__ == "__main__":
    main()
