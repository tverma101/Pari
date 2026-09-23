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

# Fixed screening budget. Full benchmark evaluation remains separate.
BLIMP_PER_CONFIG = 10   # 67 configs -> 670 pairs
WIC_COUNT = 300
COLA_COUNT = 300
PAWS_COUNT = 300


def stable_take(rows: list[dict], count: int, salt: str) -> list[dict]:
    def key(row: dict) -> str:
        raw = json.dumps(row, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(f"{salt}:{raw}".encode()).hexdigest()

    return sorted(rows, key=key)[: min(count, len(rows))]


def choice_prompt(prefix: str, choices: list[str]) -> str:
    opts = "\n".join(f"{LETTERS[i]}. {choice}" for i, choice in enumerate(choices))
    return f"{prefix}\n{opts}\nAnswer only with the letter."


tasks: list[dict] = []
answers: dict[str, str] = {}
counts: dict[str, int] = {}


def add(task_id: str, dimension: str, source: str, prompt: str, answer_letter: str, phenomenon: str | None = None) -> None:
    tasks.append({
        "id": task_id,
        "dimension": dimension,
        "source": source,
        "phenomenon": phenomenon,
        "prompt": prompt,
        "generative": False,
    })
    answers[task_id] = answer_letter
    counts[source] = counts.get(source, 0) + 1


# BLiMP: sentence_good / sentence_bad are already minimal pairs. Alternate option
# order deterministically so a model cannot exploit an A-is-always-good pattern.
blimp_configs = get_dataset_config_names("nyu-mll/blimp")
for config in sorted(blimp_configs):
    rows = list(load_dataset("nyu-mll/blimp", config, split="train"))
    for i, row in enumerate(stable_take(rows, BLIMP_PER_CONFIG, f"blimp:{config}")):
        good = row["sentence_good"]
        bad = row["sentence_bad"]
        flip = int(hashlib.sha256(f"{config}:{i}".encode()).hexdigest(), 16) % 2 == 1
        choices = [bad, good] if flip else [good, bad]
        answer = "B" if flip else "A"
        add(
            f"pub-blimp-{config}-{i:03d}",
            "grammar_syntax",
            "BLiMP",
            choice_prompt("Which sentence is more acceptable in standard English?", choices),
            answer,
            row.get("linguistics_term") or row.get("field") or config,
        )


# WiC: label 1=True means same word sense; label 0=False means different.
wic_rows = list(load_dataset("aps/super_glue", "wic", split="validation"))
for i, row in enumerate(stable_take(wic_rows, WIC_COUNT, "wic:validation")):
    prompt = choice_prompt(
        f"Target word: {row['word']}\nSentence 1: {row['sentence1']}\nSentence 2: {row['sentence2']}\nDoes the target have the same meaning in both sentences?",
        ["same", "different"],
    )
    add(
        f"pub-wic-{i:04d}",
        "lexical_context",
        "WiC",
        prompt,
        "A" if int(row["label"]) == 1 else "B",
        "word_sense_discrimination",
    )


# CoLA: use validation because public test labels are not the appropriate local
# gold source. This is individual acceptability classification rather than a pair.
cola_rows = list(load_dataset("nyu-mll/glue", "cola", split="validation"))
for i, row in enumerate(stable_take(cola_rows, COLA_COUNT, "cola:validation")):
    prompt = choice_prompt(
        f"Sentence: {row['sentence']}\nIs this sentence acceptable in standard written English?",
        ["acceptable", "unacceptable"],
    )
    add(
        f"pub-cola-{i:04d}",
        "grammar_syntax",
        "CoLA",
        prompt,
        "A" if int(row["label"]) == 1 else "B",
        "acceptability",
    )


# PAWS-Wiki labeled final: label 1=paraphrase/same meaning, 0=not paraphrase.
paws_rows = list(load_dataset("paws", "labeled_final", split="validation"))
for i, row in enumerate(stable_take(paws_rows, PAWS_COUNT, "paws:labeled_final:validation")):
    prompt = choice_prompt(
        f"Sentence 1: {row['sentence1']}\nSentence 2: {row['sentence2']}\nDo these sentences preserve the same meaning?",
        ["same", "different"],
    )
    add(
        f"pub-paws-{i:04d}",
        "paraphrase_semantics",
        "PAWS",
        prompt,
        "A" if int(row["label"]) == 1 else "B",
        "high_overlap_paraphrase",
    )


(HERE / "english-core-public-fast.jsonl").write_text(
    "\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n"
)
(HERE / "english-core-public-fast.answers.json").write_text(
    json.dumps({"version": 1, "answers": answers}, indent=2) + "\n"
)
(HERE / "english-core-public-fast.manifest.json").write_text(
    json.dumps(
        {
            "version": 1,
            "purpose": "deterministic public-anchor screening set; not a substitute for official full benchmark evaluation",
            "cases": len(tasks),
            "countsBySource": counts,
            "sourcePolicy": "evaluation only; never use these rows for model training or prompt optimization",
            "sources": {
                "BLiMP": {"dataset": "nyu-mll/blimp", "split": "train-by-dataset-convention", "perConfig": BLIMP_PER_CONFIG},
                "WiC": {"dataset": "aps/super_glue", "config": "wic", "split": "validation", "count": WIC_COUNT},
                "CoLA": {"dataset": "nyu-mll/glue", "config": "cola", "split": "validation", "count": COLA_COUNT},
                "PAWS": {"dataset": "paws", "config": "labeled_final", "split": "validation", "count": PAWS_COUNT},
            },
        },
        indent=2,
    ) + "\n"
)

print(json.dumps({"cases": len(tasks), "countsBySource": counts}, indent=2))
