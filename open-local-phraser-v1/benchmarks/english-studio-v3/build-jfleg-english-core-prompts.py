"""Build English Core prompts from an official JFLEG `.src` file.

Download JFLEG from https://github.com/keisks/jfleg and pass `dev/dev.src` or
`test/test.src`. Benchmark data is not vendored into Pari.

Usage:
    python build-jfleg-english-core-prompts.py /path/to/jfleg/dev/dev.src jfleg-dev-prompts.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_file")
    ap.add_argument("out_jsonl")
    args = ap.parse_args()

    source = Path(args.source_file).resolve()
    lines = source.read_text().splitlines()
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

    out = Path(args.out_jsonl)
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n")
    out.with_suffix(out.suffix + ".manifest.json").write_text(json.dumps({
        "version": 1,
        "sourceFile": str(source),
        "sourceSha256": sha256(source),
        "cases": len(tasks),
        "officialRepository": "https://github.com/keisks/jfleg",
        "officialMetric": "GLEU using the repository eval/gleu.py script with all four references",
        "researchReference": "https://aclanthology.org/E17-2037/",
        "protocolNote": "Pari only adapts model I/O; official JFLEG references and GLEU remain authoritative."
    }, indent=2) + "\n")
    print(json.dumps({"cases": len(tasks), "out": str(out)}, indent=2))


if __name__ == "__main__":
    main()
