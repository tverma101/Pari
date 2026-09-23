"""Convert an English Core JFLEG run to the hypothesis file expected by JFLEG.

Usage:
    python convert-jfleg-english-core-output.py jfleg-dev-prompts.jsonl model-result.json hypothesis.txt

Then, from an official JFLEG checkout:
    python ./eval/gleu.py -r ./dev/dev.ref[0-3] -s ./dev/dev.src --hyp /path/to/hypothesis.txt

The official script reports the benchmark GLEU result and uncertainty; Pari does
not replace it with a custom fluency metric.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def normalize_one_line(text: str) -> str:
    # JFLEG expects one hypothesis per source line. Preserve sentence content while
    # collapsing model formatting/newlines that are not part of the benchmark I/O.
    return " ".join(str(text or "").strip().split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_jsonl")
    ap.add_argument("model_result")
    ap.add_argument("out_hypothesis")
    args = ap.parse_args()

    tasks = [json.loads(line) for line in Path(args.prompt_jsonl).read_text().splitlines() if line.strip()]
    run = json.loads(Path(args.model_result).read_text())
    outputs = {row["id"]: row.get("output", "") for row in run.get("outputs", [])}

    hypotheses = []
    missing = []
    empty = []
    for task in tasks:
        task_id = task["id"]
        if task_id not in outputs:
            missing.append(task_id)
            hypotheses.append("")
            continue
        text = normalize_one_line(outputs[task_id])
        if not text:
            empty.append(task_id)
        hypotheses.append(text)

    Path(args.out_hypothesis).write_text("\n".join(hypotheses) + "\n")
    print(json.dumps({
        "cases": len(tasks),
        "hypotheses": len(hypotheses),
        "missingOutputs": len(missing),
        "emptyOutputs": len(empty),
        "out": args.out_hypothesis,
        "nextStep": "Run the official JFLEG eval/gleu.py with all four references."
    }, indent=2))


if __name__ == "__main__":
    main()
