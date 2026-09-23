"""Build full-distribution prompted public classification tasks for English Core.

This lane is separate from:
- the balanced public-fast screen; and
- benchmark-native likelihood/generation protocols such as BLiMP/SWORDS/JFLEG.

It preserves the locally scoreable validation distribution for WiC, CoLA and
PAWS-Wiki so classification metrics are not distorted by Pari's fast-screen
balancing.

For promotion-quality reproducibility, pass immutable dataset revisions (commit
SHAs) using the --*-revision flags. Omitted revisions are explicitly marked as
mutable defaults in the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import datasets
from datasets import load_dataset

HERE = Path(__file__).resolve().parent
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def permute_choices(task_id: str, choices: list[str], correct_index: int) -> tuple[list[str], str, list[int]]:
    order = list(range(len(choices)))
    for i in range(len(order) - 1, 0, -1):
        digest = hashlib.sha256(f"{task_id}:option:{i}".encode()).digest()
        j = int.from_bytes(digest[:4], "big") % (i + 1)
        order[i], order[j] = order[j], order[i]
    shuffled = [choices[i] for i in order]
    return shuffled, LETTERS[order.index(correct_index)], order


def choice_prompt(prefix: str, choices: list[str]) -> str:
    rendered = "\n".join(f"{LETTERS[i]}. {choice}" for i, choice in enumerate(choices))
    return f"{prefix}\n{rendered}\nAnswer only with the letter."


def revision_record(value: str | None) -> str:
    return value if value else "mutable_default_not_pinned"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super-glue-revision", default=None)
    ap.add_argument("--glue-revision", default=None)
    ap.add_argument("--paws-revision", default=None)
    args = ap.parse_args()

    tasks: list[dict] = []
    answers: dict[str, dict] = {}
    counts = Counter()
    label_counts: dict[str, Counter] = {}
    fingerprints: dict[str, str | None] = {}

    def add(
        task_id: str,
        source: str,
        dimension: str,
        prefix: str,
        choices: list[str],
        choice_labels: list[int],
        correct_index: int,
        gold_label: int,
        phenomenon: str,
    ) -> None:
        if len(choices) != len(choice_labels):
            raise ValueError(f"{task_id}: choices and choice_labels length mismatch")
        shuffled, letter, order = permute_choices(task_id, choices, correct_index)
        label_by_letter = {
            LETTERS[new_index]: int(choice_labels[original_index])
            for new_index, original_index in enumerate(order)
        }
        tasks.append(
            {
                "id": task_id,
                "source": source,
                "dimension": dimension,
                "phenomenon": phenomenon,
                "prompt": choice_prompt(prefix, shuffled),
                "generative": False,
            }
        )
        answers[task_id] = {
            "letter": letter,
            "goldLabel": int(gold_label),
            "labelByLetter": label_by_letter,
        }
        counts[source] += 1
        label_counts.setdefault(source, Counter())[int(gold_label)] += 1

    BINARY_CHOICE_LABELS = [1, 0]

    wic_ds = load_dataset("aps/super_glue", "wic", split="validation", revision=args.super_glue_revision)
    fingerprints["WiC"] = getattr(wic_ds, "_fingerprint", None)
    for i, row in enumerate(wic_ds):
        label = int(row["label"])
        task_id = f"full-wic-{i:05d}"
        add(
            task_id,
            "WiC",
            "lexical_context",
            (
                f"Target word: {row['word']}\n"
                f"Sentence 1: {row['sentence1']}\n"
                f"Sentence 2: {row['sentence2']}\n"
                "Does the target have the same meaning in both sentences?"
            ),
            ["same", "different"],
            BINARY_CHOICE_LABELS,
            0 if label == 1 else 1,
            label,
            "word_sense_discrimination",
        )

    cola_ds = load_dataset("nyu-mll/glue", "cola", split="validation", revision=args.glue_revision)
    fingerprints["CoLA"] = getattr(cola_ds, "_fingerprint", None)
    for i, row in enumerate(cola_ds):
        label = int(row["label"])
        task_id = f"full-cola-{i:05d}"
        add(
            task_id,
            "CoLA",
            "grammar_syntax",
            f"Sentence: {row['sentence']}\nIs this sentence acceptable in standard written English?",
            ["acceptable", "unacceptable"],
            BINARY_CHOICE_LABELS,
            0 if label == 1 else 1,
            label,
            "acceptability",
        )

    paws_ds = load_dataset("paws", "labeled_final", split="validation", revision=args.paws_revision)
    fingerprints["PAWS"] = getattr(paws_ds, "_fingerprint", None)
    for i, row in enumerate(paws_ds):
        label = int(row["label"])
        task_id = f"full-paws-{i:05d}"
        add(
            task_id,
            "PAWS",
            "paraphrase_semantics",
            (
                f"Sentence 1: {row['sentence1']}\n"
                f"Sentence 2: {row['sentence2']}\n"
                "Do these sentences preserve the same meaning?"
            ),
            ["same", "different"],
            BINARY_CHOICE_LABELS,
            0 if label == 1 else 1,
            label,
            "high_overlap_paraphrase",
        )

    (HERE / "english-core-public-full-classification.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n"
    )
    (HERE / "english-core-public-full-classification.answers.json").write_text(
        json.dumps({"version": 3, "answers": answers}, indent=2) + "\n"
    )
    (HERE / "english-core-public-full-classification.manifest.json").write_text(
        json.dumps(
            {
                "version": 3,
                "purpose": "full-distribution prompted classification lane; distinct from balanced fast screen and benchmark-native protocols",
                "cases": len(tasks),
                "countsBySource": dict(counts),
                "labelCountsBySource": {k: dict(v) for k, v in label_counts.items()},
                "datasetsLibraryVersion": datasets.__version__,
                "resolvedDatasetFingerprints": fingerprints,
                "revisionPolicy": "promotion runs should provide immutable dataset revisions; omitted revisions are explicitly marked mutable",
                "optionOrder": "deterministic SHA-256 permutation per item; answer file preserves displayed-letter-to-class mapping",
                "distributionPolicy": "no Pari label balancing or subsampling; preserve each locally scoreable validation distribution",
                "adaptation": "zero-shot prompted classification; not identical to supervised benchmark-native model adaptation",
                "sources": {
                    "WiC": {"dataset": "aps/super_glue", "config": "wic", "split": "validation", "headlineMetric": "accuracy", "requestedRevision": revision_record(args.super_glue_revision)},
                    "CoLA": {"dataset": "nyu-mll/glue", "config": "cola", "split": "validation", "headlineMetric": "Matthews correlation coefficient", "requestedRevision": revision_record(args.glue_revision)},
                    "PAWS": {"dataset": "paws", "config": "labeled_final", "split": "validation", "headlineMetric": "accuracy", "requestedRevision": revision_record(args.paws_revision)},
                },
                "researchReferences": {
                    "WiC": "https://aclanthology.org/N19-1128/",
                    "CoLA": "https://aclanthology.org/Q19-1040/",
                    "PAWS": "https://aclanthology.org/N19-1131/",
                },
            },
            indent=2,
        ) + "\n"
    )

    print(json.dumps({"cases": len(tasks), "countsBySource": dict(counts), "datasetsVersion": datasets.__version__}, indent=2))


if __name__ == "__main__":
    main()
