#!/usr/bin/env python3
"""Build model-visible Word Studio slider tasks and a separate private review key.

The hand-authored synthetic seed may be versioned separately as an explicitly
unvalidated product test. Keep the generated review key, tasks, and model
outputs in the private Kaggle notebook/workspace; do not attach them to a public
Kaggle model or dataset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STRENGTHS = (15, 40, 60, 90)
STRENGTH_GUIDANCE = {
    15: "Keep the original wording and shape when they already work; make only small useful changes.",
    40: "Make a noticeable but moderate rewrite; change some wording while keeping the original shape mostly intact.",
    60: "Make a confident rewrite; vary wording and recast syntax when that improves clarity, without changing the meaning or voice.",
    90: "Make a bold rewrite with substantially different wording or structure, but do not intensify claims, change the author's voice, or alter facts.",
}
PROMPT_CONTRACT = {
    "version": 1,
    "candidateCount": 10,
    "strengths": list(STRENGTHS),
    "strengthGuidance": STRENGTH_GUIDANCE,
    "invariants": [
        "Keep every fact, actor, relation, quantity, date, name, filename, quote, negation, modality, and certainty level intact.",
        "Do not invent evidence, causes, outcomes, or claims.",
        "Preserve the author's register and intensity unless the user explicitly asks to change them.",
        "Each alternative should be grammatical, natural, and genuinely useful; avoid thesaurus inflation and duplicates.",
    ],
    "productChoice": "The slider controls how much wording/structure may change, not how strong the author's opinion becomes.",
    "evidenceLabel": "Pari product-engineering prompt contract; not a literature-derived scale or human-validated gold.",
}


def sha256(data: bytes) -> str:
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


def build_prompt(input_text: str, strength: int, selected: str | None) -> str:
    guidance = STRENGTH_GUIDANCE[strength]
    invariants = "\n".join(f"- {item}" for item in PROMPT_CONTRACT["invariants"])
    if selected:
        task = (
            "Suggest replacements for only the selected text. Return replacement phrases only; "
            "do not rewrite the surrounding sentence. Use the surrounding sentence as context.\n"
            f"Full context: {input_text}\nSelected text: {selected}"
        )
    else:
        task = f"Rewrite this complete paragraph as alternative paragraphs:\n{input_text}"
    return (
        "You are Pari Word Studio, an English rewriting assistant.\n"
        f"Strength slider: {strength}/100. {guidance}\n\n"
        f"{task}\n\n"
        "Return exactly 10 distinct alternatives as a JSON object with one key, "
        '"options", whose value is an array of 10 strings. Return JSON only.\n'
        "Rules:\n" + invariants
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic-seed", required=True, type=Path)
    ap.add_argument("--interactive-seed", type=Path, default=HERE / "interactive.seed.json")
    ap.add_argument("--output", type=Path, default=HERE / "word-studio-strength.jsonl")
    ap.add_argument("--manifest", type=Path, default=HERE / "word-studio-strength.manifest.json")
    ap.add_argument("--private-review-key", type=Path, default=None)
    args = ap.parse_args()

    synthetic_path = args.synthetic_seed.resolve()
    interactive_path = args.interactive_seed.resolve()
    if not synthetic_path.is_file() or not interactive_path.is_file():
        raise SystemExit("Both the private synthetic seed and the tracked interactive seed are required")
    synthetic_bytes = synthetic_path.read_bytes()
    interactive_bytes = interactive_path.read_bytes()
    synthetic = json.loads(synthetic_bytes)
    interactive = json.loads(interactive_bytes)
    synthetic_rows = synthetic.get("cases", [])
    interactive_rows = interactive.get("cases", [])
    if synthetic.get("status") != "synthetic_hand_authored_unvalidated":
        raise SystemExit("Synthetic seed must retain its unvalidated evidence label")
    if not synthetic_rows:
        raise SystemExit("Synthetic seed has no cases")

    tasks: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(case_id: str, kind: str, text: str, strength: int, selected: str | None, expectations: list[str], source: str) -> None:
        task_id = f"ws-{source}-{case_id}-s{strength}"
        if task_id in seen:
            raise SystemExit(f"Duplicate generated task id: {task_id}")
        seen.add(task_id)
        tasks.append({
            "id": task_id,
            "dimension": "word_studio_strength_response",
            "suite": "word_studio_v1_strength_private",
            "source": source,
            "sourceId": case_id,
            "task": kind,
            "strength": strength,
            "requestedCount": 10,
            "sourceText": text,
            "selectedText": selected,
            "generative": True,
            "maxNewTokens": 1200,
            "prompt": build_prompt(text, strength, selected),
        })
        review.append({
            "id": task_id,
            "sourceId": case_id,
            "strength": strength,
            "source": source,
            "expectations": expectations,
            "reviewStatus": "synthetic_author_expectations_not_independently_validated",
        })

    selected_categories = {"register_preserve", "vocabulary_ceiling"}
    selected_rows = [row for row in interactive_rows if row.get("category") in selected_categories]
    if not selected_rows:
        raise SystemExit("Interactive seed contains no slider-relevant register/vocabulary cases")
    for row in selected_rows:
        for strength in STRENGTHS:
            add(
                row["id"],
                "selected_span_alternatives",
                row["input"],
                strength,
                row.get("selection"),
                row.get("requirements", []),
                "interactive_v2",
            )

    for row in synthetic_rows:
        for strength in STRENGTHS:
            add(
                row["id"],
                "paragraph_rewrite",
                row["input"],
                strength,
                None,
                row.get("expectations", []),
                "synthetic_private",
            )

    task_bytes = ("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n").encode("utf-8")
    prompt_hash = sha256(json.dumps(PROMPT_CONTRACT, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    manifest = {
        "version": 2,
        "suite": "word_studio_v1_strength_private",
        "cases": len(tasks),
        "uniqueSources": len({row["sourceId"] for row in tasks}),
        "strengths": list(STRENGTHS),
        "tasks": str(args.output.resolve()),
        "taskFileSha256": sha256(task_bytes),
        "promptContractSha256": prompt_hash,
        "syntheticSeedSha256": sha256(synthetic_bytes),
        "interactiveSeedSha256": sha256(interactive_bytes),
        "evidenceStatus": "synthetic_hand_authored_unvalidated; internal_interactive_seed; not published gold",
        "strengthInterpretation": PROMPT_CONTRACT["productChoice"],
        "humanReview": "Use the separate private review key. No LLM judge is run; counts and latency are not quality scores.",
        "diagnosticMetadata": "sourceText/selectedText are non-gold fields already present in the prompt; they enable unchanged-copy diagnostics without opening the private review key.",
        "privacy": "Keep tasks, private review key, outputs, and this manifest in a private Kaggle notebook/workspace.",
    }
    review_path = args.private_review_key or args.output.with_name("word-studio-strength.private-review.json")
    atomic_write(args.output, task_bytes)
    atomic_write(args.manifest, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    atomic_write(review_path, (json.dumps({"version": 1, "items": review}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"cases": len(tasks), "uniqueSources": manifest["uniqueSources"], "strengths": list(STRENGTHS), "taskFileSha256": manifest["taskFileSha256"], "promptContractSha256": prompt_hash, "reviewKey": str(review_path.resolve())}, indent=2))


if __name__ == "__main__":
    main()
