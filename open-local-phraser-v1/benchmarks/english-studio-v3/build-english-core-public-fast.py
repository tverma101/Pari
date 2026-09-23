"""Build a deterministic public-anchor screening set for Pari English Core.

This does NOT replace official full benchmark evaluation. It creates a manageable,
reproducible screening set from public evaluation/benchmark splits so candidate
LLMs can be compared before expensive full-suite runs.

Requires:
    pip install datasets

For promotion-quality reproducibility, pass immutable dataset revisions (commit
SHAs) with the --*-revision flags. Omitting them is allowed for exploration but
is recorded as a mutable-default source in the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import datasets
from datasets import get_dataset_config_names, load_dataset

HERE = Path(__file__).resolve().parent
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

BLIMP_PER_CONFIG = 10
WIC_COUNT = 300
COLA_COUNT = 300
PAWS_COUNT = 300


def stable_key(row: dict, salt: str) -> str:
    raw = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{salt}:{raw}".encode()).hexdigest()


def stable_take(rows: list[dict], count: int, salt: str) -> list[dict]:
    return sorted(rows, key=lambda row: stable_key(row, salt))[: min(count, len(rows))]


def stable_take_binary_balanced(rows: list[dict], count: int, salt: str) -> list[dict]:
    groups = {0: [], 1: []}
    for row in rows:
        label = int(row["label"])
        if label in groups:
            groups[label].append(row)
    half0 = count // 2
    half1 = count - half0
    picked = stable_take(groups[0], half0, f"{salt}:label0") + stable_take(groups[1], half1, f"{salt}:label1")
    if len(picked) < count:
        used = {stable_key(row, "identity") for row in picked}
        remainder = [row for row in rows if stable_key(row, "identity") not in used]
        picked += stable_take(remainder, count - len(picked), f"{salt}:remainder")
    return sorted(picked, key=lambda row: stable_key(row, f"{salt}:final"))


def permute_choices(task_id: str, choices: list[str], correct_index: int) -> tuple[list[str], str]:
    order = list(range(len(choices)))
    for i in range(len(order) - 1, 0, -1):
        digest = hashlib.sha256(f"{task_id}:option:{i}".encode()).digest()
        value = int.from_bytes(digest[:4], "big")
        j = value % (i + 1)
        order[i], order[j] = order[j], order[i]
    shuffled = [choices[i] for i in order]
    new_index = order.index(correct_index)
    return shuffled, LETTERS[new_index]


def choice_prompt(prefix: str, choices: list[str]) -> str:
    opts = "\n".join(f"{LETTERS[i]}. {choice}" for i, choice in enumerate(choices))
    return f"{prefix}\n{opts}\nAnswer only with the letter."


def revision_record(value: str | None) -> str:
    return value if value else "mutable_default_not_pinned"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blimp-revision", default=None)
    ap.add_argument("--super-glue-revision", default=None)
    ap.add_argument("--glue-revision", default=None)
    ap.add_argument("--paws-revision", default=None)
    args = ap.parse_args()

    tasks: list[dict] = []
    answers: dict[str, str] = {}
    counts: dict[str, int] = {}
    fingerprints: dict[str, object] = {}

    def add(task_id: str, dimension: str, source: str, prefix: str, choices: list[str], correct_index: int, phenomenon: str | None = None) -> None:
        shuffled, answer_letter = permute_choices(task_id, choices, correct_index)
        tasks.append({
            "id": task_id,
            "dimension": dimension,
            "source": source,
            "phenomenon": phenomenon,
            "prompt": choice_prompt(prefix, shuffled),
            "generative": False,
        })
        answers[task_id] = answer_letter
        counts[source] = counts.get(source, 0) + 1

    blimp_configs = get_dataset_config_names("nyu-mll/blimp", revision=args.blimp_revision)
    blimp_fingerprints = {}
    for config in sorted(blimp_configs):
        ds = load_dataset("nyu-mll/blimp", config, split="train", revision=args.blimp_revision)
        blimp_fingerprints[config] = getattr(ds, "_fingerprint", None)
        rows = list(ds)
        for i, row in enumerate(stable_take(rows, BLIMP_PER_CONFIG, f"blimp:{config}")):
            task_id = f"pub-blimp-{config}-{i:03d}"
            add(
                task_id,
                "grammar_syntax",
                "BLiMP",
                "Which sentence is more acceptable in standard English?",
                [row["sentence_good"], row["sentence_bad"]],
                0,
                row.get("linguistics_term") or row.get("field") or config,
            )
    fingerprints["BLiMP"] = blimp_fingerprints

    wic_ds = load_dataset("aps/super_glue", "wic", split="validation", revision=args.super_glue_revision)
    fingerprints["WiC"] = getattr(wic_ds, "_fingerprint", None)
    wic_rows = list(wic_ds)
    for i, row in enumerate(stable_take_binary_balanced(wic_rows, WIC_COUNT, "wic:validation")):
        task_id = f"pub-wic-{i:04d}"
        add(
            task_id,
            "lexical_context",
            "WiC",
            f"Target word: {row['word']}\nSentence 1: {row['sentence1']}\nSentence 2: {row['sentence2']}\nDoes the target have the same meaning in both sentences?",
            ["same", "different"],
            0 if int(row["label"]) == 1 else 1,
            "word_sense_discrimination",
        )

    cola_ds = load_dataset("nyu-mll/glue", "cola", split="validation", revision=args.glue_revision)
    fingerprints["CoLA"] = getattr(cola_ds, "_fingerprint", None)
    cola_rows = list(cola_ds)
    for i, row in enumerate(stable_take_binary_balanced(cola_rows, COLA_COUNT, "cola:validation")):
        task_id = f"pub-cola-{i:04d}"
        add(
            task_id,
            "grammar_syntax",
            "CoLA",
            f"Sentence: {row['sentence']}\nIs this sentence acceptable in standard written English?",
            ["acceptable", "unacceptable"],
            0 if int(row["label"]) == 1 else 1,
            "acceptability",
        )

    paws_ds = load_dataset("paws", "labeled_final", split="validation", revision=args.paws_revision)
    fingerprints["PAWS"] = getattr(paws_ds, "_fingerprint", None)
    paws_rows = list(paws_ds)
    for i, row in enumerate(stable_take_binary_balanced(paws_rows, PAWS_COUNT, "paws:labeled_final:validation")):
        task_id = f"pub-paws-{i:04d}"
        add(
            task_id,
            "paraphrase_semantics",
            "PAWS",
            f"Sentence 1: {row['sentence1']}\nSentence 2: {row['sentence2']}\nDo these sentences preserve the same meaning?",
            ["same", "different"],
            0 if int(row["label"]) == 1 else 1,
            "high_overlap_paraphrase",
        )

    (HERE / "english-core-public-fast.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n"
    )
    (HERE / "english-core-public-fast.answers.json").write_text(
        json.dumps({"version": 3, "answers": answers}, indent=2) + "\n"
    )
    (HERE / "english-core-public-fast.manifest.json").write_text(
        json.dumps(
            {
                "version": 3,
                "purpose": "deterministic public-anchor screening set; not a substitute for official full benchmark evaluation",
                "cases": len(tasks),
                "countsBySource": counts,
                "datasetsLibraryVersion": datasets.__version__,
                "resolvedDatasetFingerprints": fingerprints,
                "sourcePolicy": "evaluation only; never use these rows for model training or prompt optimization",
                "revisionPolicy": "promotion runs should provide immutable dataset commit revisions; omitted revisions are explicitly marked mutable",
                "screeningDesign": {
                    "optionOrder": "deterministic SHA-256 permutation for every forced-choice item",
                    "binarySources": "WiC, CoLA, and PAWS are approximately label-balanced in this fast screen",
                    "budgets": "engineering choices for cheap screening, not literature-derived construct weights",
                },
                "sources": {
                    "BLiMP": {"dataset": "nyu-mll/blimp", "split": "train-by-dataset-convention", "perConfig": BLIMP_PER_CONFIG, "requestedRevision": revision_record(args.blimp_revision)},
                    "WiC": {"dataset": "aps/super_glue", "config": "wic", "split": "validation", "count": WIC_COUNT, "balanced": True, "requestedRevision": revision_record(args.super_glue_revision)},
                    "CoLA": {"dataset": "nyu-mll/glue", "config": "cola", "split": "validation", "count": COLA_COUNT, "balanced": True, "requestedRevision": revision_record(args.glue_revision)},
                    "PAWS": {"dataset": "paws", "config": "labeled_final", "split": "validation", "count": PAWS_COUNT, "balanced": True, "requestedRevision": revision_record(args.paws_revision)},
                },
            },
            indent=2,
        ) + "\n"
    )

    print(json.dumps({"cases": len(tasks), "countsBySource": counts, "datasetsVersion": datasets.__version__}, indent=2))


if __name__ == "__main__":
    main()
