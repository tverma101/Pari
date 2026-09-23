"""Build a deterministic public-anchor screening set for Pari English Core.

This does NOT replace official full benchmark evaluation. It creates a manageable,
reproducible screening set from public evaluation/benchmark splits so candidate
LLMs can be compared before expensive full-suite runs.

Requires:
    pip install datasets

Sources:
- nyu-mll/blimp: 67 benchmark configs, train-only by dataset convention
- aps/super_glue, config wic: validation split
- nyu-mll/glue, config cola: validation split
- paws, config labeled_final: validation split

Outputs (not intended to be committed after every rebuild):
- english-core-public-fast.jsonl          prompts only
- english-core-public-fast.answers.json   gold answer key
- english-core-public-fast.manifest.json  provenance/counts
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from datasets import get_dataset_config_names, load_dataset

HERE = Path(__file__).resolve().parent
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Fixed screening budget. These are engineering budgets, not research-derived
# importance weights. Official full benchmark evaluation remains separate.
BLIMP_PER_CONFIG = 10   # 67 configs -> 670 pairs
WIC_COUNT = 300
COLA_COUNT = 300
PAWS_COUNT = 300


def stable_key(row: dict, salt: str) -> str:
    raw = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{salt}:{raw}".encode()).hexdigest()


def stable_take(rows: list[dict], count: int, salt: str) -> list[dict]:
    return sorted(rows, key=lambda row: stable_key(row, salt))[: min(count, len(rows))]


def stable_take_binary_balanced(rows: list[dict], count: int, salt: str) -> list[dict]:
    """Take an approximately 50/50 label sample for screening accuracy.

    The official benchmark distribution is preserved only in full-suite reporting;
    this fast screen is balanced so a model cannot benefit from a source's majority
    class. If one class is too small, fill the remainder deterministically.
    """
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


tasks: list[dict] = []
answers: dict[str, str] = {}
counts: dict[str, int] = {}


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


# BLiMP: sentence_good / sentence_bad are already minimal pairs. Every item is
# option-permuted so A/B position carries no stable grammaticality signal.
blimp_configs = get_dataset_config_names("nyu-mll/blimp")
for config in sorted(blimp_configs):
    rows = list(load_dataset("nyu-mll/blimp", config, split="train"))
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


# WiC: label 1=True means same word sense; label 0=False means different.
wic_rows = list(load_dataset("aps/super_glue", "wic", split="validation"))
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


# CoLA: validation has public labels and is suitable for a local screen. The fast
# sample is balanced by acceptability label; official/full reporting should use
# the benchmark's standard protocol rather than this screening distribution.
cola_rows = list(load_dataset("nyu-mll/glue", "cola", split="validation"))
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


# PAWS-Wiki labeled-final: label 1=paraphrase/same meaning, 0=not paraphrase.
paws_rows = list(load_dataset("paws", "labeled_final", split="validation"))
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
    json.dumps({"version": 2, "answers": answers}, indent=2) + "\n"
)
(HERE / "english-core-public-fast.manifest.json").write_text(
    json.dumps(
        {
            "version": 2,
            "purpose": "deterministic public-anchor screening set; not a substitute for official full benchmark evaluation",
            "cases": len(tasks),
            "countsBySource": counts,
            "sourcePolicy": "evaluation only; never use these rows for model training or prompt optimization",
            "screeningDesign": {
                "optionOrder": "deterministic SHA-256 permutation for every forced-choice item",
                "binarySources": "WiC, CoLA, and PAWS are approximately label-balanced in this fast screen",
                "budgets": "engineering choices for cheap screening, not literature-derived construct weights"
            },
            "sources": {
                "BLiMP": {"dataset": "nyu-mll/blimp", "split": "train-by-dataset-convention", "perConfig": BLIMP_PER_CONFIG},
                "WiC": {"dataset": "aps/super_glue", "config": "wic", "split": "validation", "count": WIC_COUNT, "balanced": True},
                "CoLA": {"dataset": "nyu-mll/glue", "config": "cola", "split": "validation", "count": COLA_COUNT, "balanced": True},
                "PAWS": {"dataset": "paws", "config": "labeled_final", "split": "validation", "count": PAWS_COUNT, "balanced": True},
            },
        },
        indent=2,
    ) + "\n"
)

print(json.dumps({"cases": len(tasks), "countsBySource": counts}, indent=2))
