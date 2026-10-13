#!/usr/bin/env python3
"""Build a 100-task cross-granularity Word Studio product suite.

The suite is derived only from the tracked hand-authored interactive seed. It is
an internal product benchmark, not published human-validated gold. Expectations
stay in a separate review key and are never shown to the model.
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

OPERATIONS: dict[str, list[dict[str, Any]]] = {
    "word_to_phrase": [
        {"id": "phrase", "instruction": "Replace the selected word with a natural phrase of 2 to 6 words."},
        {"id": "flex", "instruction": "Replace the selected word with any natural context-valid alternative; one word or a short phrase is allowed."},
    ],
    "phrase_to_word": [
        {"id": "word", "instruction": "Compress the selected phrase to one natural word when possible."},
        {"id": "micro", "instruction": "Compress the selected phrase to 1 to 3 natural words."},
    ],
    "phrase_to_phrase": [
        {"id": "phrase", "instruction": "Replace the selected phrase with a materially different natural phrase."},
        {"id": "shorter", "instruction": "Replace the selected phrase with a shorter natural phrase without changing its role in the sentence."},
    ],
    "clause_rewrite": [
        {"id": "clause", "instruction": "Rewrite only the selected clause with different wording or syntax while preserving its logical relation."},
        {"id": "reorder", "instruction": "Rewrite only the selected clause and prefer a structurally different ordering when natural."},
    ],
    "sentence_rewrite": [
        {"id": "sentence", "instruction": "Rewrite the selected complete sentence with materially different structure while preserving all propositions."},
        {"id": "gist3", "instruction": "Compress the selected sentence to a 1 to 3 word gist label. Preserve the central idea only; detail loss is intentional and must not be scored as ordinary paraphrase loss.", "semanticMode": "intentional_compression"},
    ],
    "split_join": [
        {"id": "structure", "instruction": "Transform the selected text by splitting or joining sentences in the direction that improves natural flow while preserving all claims and event order."},
        {"id": "compact", "instruction": "Make the selected text structurally more compact while preserving all claims, negation, and event order."},
    ],
    "register_preserve": [
        {"id": "same-register", "instruction": "Replace only the selected text with natural alternatives that preserve the same conversational register and intensity."},
    ],
    "vocabulary_ceiling": [
        {"id": "simple", "instruction": "Replace only the selected text using ordinary common English; do not make the vocabulary more sophisticated."},
    ],
    "collocation": [
        {"id": "collocation", "instruction": "Replace only the selected text with natural English collocations that fit the complete sentence."},
    ],
    "protected_context": [
        {"id": "protected", "instruction": "Replace only the selected text. All names, numbers, dates, filenames, quotes, and other protected context outside the selection must remain conceptually untouched."},
    ],
    "expansion_compression": [
        {"id": "shorter", "instruction": "Replace only the selected text with a shorter natural equivalent."},
        {"id": "longer", "instruction": "Replace only the selected text with a longer natural equivalent. Do not invent facts or causes while expanding."},
    ],
}

INVARIANTS = [
    "Use the full sentence as context but output replacements for the selected text only, unless the task explicitly selects a complete sentence or multi-sentence span.",
    "Preserve actor roles, polarity, negation, modality, quantities, chronology, comparison direction, and causal/conditional/concessive relations unless the operation explicitly says intentional compression.",
    "Do not invent evidence, reasons, facts, causes, outcomes, names, dates, or stronger claims.",
    "Keep ordinary natural English. Do not reward academic or thesaurus-heavy wording for its own sake.",
    "Return genuinely different alternatives rather than cosmetic variants or duplicates.",
]


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


def build_prompt(row: dict[str, Any], op: dict[str, Any]) -> str:
    rules = "\n".join(f"- {x}" for x in INVARIANTS)
    semantic_note = ""
    if op.get("semanticMode") == "intentional_compression":
        semantic_note = (
            "\nThis is intentional semantic compression, not full paraphrase equivalence. "
            "Keep the central gist without inventing a new claim."
        )
    return (
        "You are Pari Word Studio. Perform exactly the requested text transformation.\n\n"
        f"Full context: {row['input']}\n"
        f"Selected text: {row['selection']}\n"
        f"Operation: {op['instruction']}{semantic_note}\n\n"
        "Return exactly 10 distinct alternatives as JSON only: "
        '{"options":["...","..."]}.\n'
        "Rules:\n" + rules
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=Path, default=HERE / "interactive.seed.json")
    ap.add_argument("--output", type=Path, default=HERE / "word-studio-transform.jsonl")
    ap.add_argument("--manifest", type=Path, default=HERE / "word-studio-transform.manifest.json")
    ap.add_argument("--private-review-key", type=Path, default=None)
    args = ap.parse_args()

    seed_bytes = args.seed.read_bytes()
    seed = json.loads(seed_bytes)
    cases = seed.get("cases", [])
    tasks: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in cases:
        category = row.get("category")
        operations = OPERATIONS.get(category)
        if not operations:
            raise SystemExit(f"no transform mapping for category {category!r} ({row.get('id')})")
        for op in operations:
            task_id = f"wst-{row['id']}-{op['id']}"
            if task_id in seen:
                raise SystemExit(f"duplicate task id {task_id}")
            seen.add(task_id)
            tasks.append({
                "id": task_id,
                "suite": "word_studio_transform_v1",
                "dimension": "cross_granularity_transformation",
                "sourceId": row["id"],
                "sourceCategory": category,
                "operation": op["id"],
                "semanticMode": op.get("semanticMode", "preserve_full_selected_meaning"),
                "requestedCount": 10,
                "sourceText": row["input"],
                "selectedText": row["selection"],
                "generative": True,
                "maxNewTokens": 900,
                "prompt": build_prompt(row, op),
            })
            review.append({
                "id": task_id,
                "sourceId": row["id"],
                "sourceCategory": category,
                "operation": op["id"],
                "input": row["input"],
                "selection": row["selection"],
                "requirements": row.get("requirements", []),
                "semanticMode": op.get("semanticMode", "preserve_full_selected_meaning"),
                "reviewStatus": "author_expectations_not_independently_validated",
            })

    if len(tasks) != 100:
        raise SystemExit(f"expected exactly 100 transform tasks from interactive seed, got {len(tasks)}")

    task_bytes = ("\n".join(json.dumps(x, ensure_ascii=False) for x in tasks) + "\n").encode("utf-8")
    manifest = {
        "version": 2,
        "suite": "word_studio_transform_v1",
        "cases": len(tasks),
        "uniqueSources": len(cases),
        "taskFileSha256": sha256(task_bytes),
        "interactiveSeedSha256": sha256(seed_bytes),
        "operationCounts": {
            category: sum(1 for task in tasks if task["sourceCategory"] == category)
            for category in sorted(OPERATIONS)
        },
        "evidenceStatus": "hand_authored_product_acceptance_seed; author expectations; not published human-validated gold",
        "scoringSeparation": "intentional_compression tasks must not use full-paraphrase semantic-equivalence thresholds",
        "diagnosticMetadata": "sourceText/selectedText are non-gold fields already present in prompts and enable unchanged-copy diagnostics without private expectations.",
        "privacy": "Keep model outputs and private review key in the private Kaggle workspace.",
    }
    review_path = args.private_review_key or args.output.with_name("word-studio-transform.private-review.json")
    atomic_write(args.output, task_bytes)
    atomic_write(args.manifest, (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    atomic_write(review_path, (json.dumps({"version": 1, "items": review}, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(json.dumps({"cases": len(tasks), "taskFileSha256": manifest["taskFileSha256"], "reviewKey": str(review_path.resolve())}, indent=2))


if __name__ == "__main__":
    main()
