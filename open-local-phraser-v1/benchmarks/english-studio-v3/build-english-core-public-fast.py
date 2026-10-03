"""Build a deterministic public-anchor screening set for Pari English Core.

This does NOT replace official full benchmark evaluation. It creates a manageable,
reproducible screening set from public evaluation/benchmark splits so candidate
LLMs can be compared before expensive full-suite runs.

Requires:
    pip install datasets huggingface_hub

Revision policy:
- `datasets.load_dataset(..., revision=...)` accepts branches, tags, or commits.
- To avoid a moving-ref race, this builder resolves each requested revision to the
  Hub repository's immutable commit SHA first, then loads the dataset using that
  resolved SHA.
- The manifest records both the originally requested revision and the resolved
  commit SHA, plus Datasets fingerprints and library versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import datasets
import huggingface_hub
from datasets import get_dataset_config_names, load_dataset
from english_core_public_sources import (
    PUBLIC_SOURCE_IDENTITIES,
    resolve_source_commit,
)
from huggingface_hub import HfApi

HERE = Path(__file__).resolve().parent
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

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


def resolve_dataset_revision(api: HfApi, repo_id: str, requested: str | None) -> dict[str, str]:
    """Delegate to the shared #67 resolver so both public lanes cannot drift.

    The canonical repo ID, config, and split live in
    `english_core_public_sources.PUBLIC_SOURCE_IDENTITIES`. One-shot resolution
    and full-SHA validation are the same code path the full-distribution
    finalist builder uses, so the two lanes cannot diverge semantically.
    """
    identity = next(
        (entry for entry in PUBLIC_SOURCE_IDENTITIES.values() if entry.repo_id == repo_id),
        None,
    )
    if identity is None:
        raise RuntimeError(f"{repo_id!r} is not a canonical Pari public source identity")
    record = resolve_source_commit(api, identity, requested)
    return {"requestedRevision": record["requestedRevision"], "resolvedRevision": record["resolvedRevision"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blimp-revision", default=None, help="Hub branch/tag/commit to resolve; default main")
    ap.add_argument("--super-glue-revision", default=None, help="Hub branch/tag/commit to resolve; default main")
    ap.add_argument("--glue-revision", default=None, help="Hub branch/tag/commit to resolve; default main")
    ap.add_argument("--paws-revision", default=None, help="Hub branch/tag/commit to resolve; default main")
    args = ap.parse_args()

    api = HfApi()
    source_revisions = {
        # Issue #67: the canonical repo IDs come from the shared source-identity
        # table, so this screen and the full-distribution finalist lane cannot
        # silently name different repositories for the same source.
        name: resolve_dataset_revision(api, identity.repo_id, getattr(args, flag))
        for name, identity, flag in (
            ("BLiMP", PUBLIC_SOURCE_IDENTITIES["BLiMP"], "blimp_revision"),
            ("WiC", PUBLIC_SOURCE_IDENTITIES["WiC"], "super_glue_revision"),
            ("CoLA", PUBLIC_SOURCE_IDENTITIES["CoLA"], "glue_revision"),
            ("PAWS", PUBLIC_SOURCE_IDENTITIES["PAWS"], "paws_revision"),
        )
    }

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
            # Model-visible frozen choice set, derived from the same structured
            # choice array that renders the prompt's "A. .." lines. It never
            # comes from gold and never from prompt prose.
            "allowedChoices": list(LETTERS[: len(shuffled)]),
            "answerProtocol": "letter",
        })
        answers[task_id] = answer_letter
        counts[source] = counts.get(source, 0) + 1

    blimp_revision = source_revisions["BLiMP"]["resolvedRevision"]
    blimp_configs = get_dataset_config_names("nyu-mll/blimp", revision=blimp_revision)
    blimp_fingerprints = {}
    for config in sorted(blimp_configs):
        ds = load_dataset(
            PUBLIC_SOURCE_IDENTITIES["BLiMP"].repo_id, config, split="train", revision=blimp_revision
        )
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

    wic_ds = load_dataset(
        PUBLIC_SOURCE_IDENTITIES["WiC"].repo_id,
        PUBLIC_SOURCE_IDENTITIES["WiC"].config,
        split=PUBLIC_SOURCE_IDENTITIES["WiC"].split,
        revision=source_revisions["WiC"]["resolvedRevision"],
    )
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

    cola_ds = load_dataset(
        PUBLIC_SOURCE_IDENTITIES["CoLA"].repo_id,
        PUBLIC_SOURCE_IDENTITIES["CoLA"].config,
        split=PUBLIC_SOURCE_IDENTITIES["CoLA"].split,
        revision=source_revisions["CoLA"]["resolvedRevision"],
    )
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

    paws_ds = load_dataset(
        PUBLIC_SOURCE_IDENTITIES["PAWS"].repo_id,
        PUBLIC_SOURCE_IDENTITIES["PAWS"].config,
        split=PUBLIC_SOURCE_IDENTITIES["PAWS"].split,
        revision=source_revisions["PAWS"]["resolvedRevision"],
    )
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

    task_path = HERE / "english-core-public-fast.jsonl"
    answer_path = HERE / "english-core-public-fast.answers.json"
    manifest_path = HERE / "english-core-public-fast.manifest.json"
    task_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n")
    answer_path.write_text(json.dumps({"version": 4, "answers": answers}, indent=2) + "\n")

    sources = {
        "BLiMP": {"dataset": PUBLIC_SOURCE_IDENTITIES["BLiMP"].repo_id, "split": "train-by-dataset-convention", "perConfig": BLIMP_PER_CONFIG, **source_revisions["BLiMP"]},
        "WiC": {"dataset": PUBLIC_SOURCE_IDENTITIES["WiC"].repo_id, "config": PUBLIC_SOURCE_IDENTITIES["WiC"].config, "split": PUBLIC_SOURCE_IDENTITIES["WiC"].split, "count": WIC_COUNT, "balanced": True, **source_revisions["WiC"]},
        "CoLA": {"dataset": PUBLIC_SOURCE_IDENTITIES["CoLA"].repo_id, "config": PUBLIC_SOURCE_IDENTITIES["CoLA"].config, "split": PUBLIC_SOURCE_IDENTITIES["CoLA"].split, "count": COLA_COUNT, "balanced": True, **source_revisions["CoLA"]},
        "PAWS": {"dataset": PUBLIC_SOURCE_IDENTITIES["PAWS"].repo_id, "config": PUBLIC_SOURCE_IDENTITIES["PAWS"].config, "split": PUBLIC_SOURCE_IDENTITIES["PAWS"].split, "count": PAWS_COUNT, "balanced": True, **source_revisions["PAWS"]},
    }
    manifest_path.write_text(
        json.dumps(
            {
                "version": 4,
                "purpose": "deterministic public-anchor screening set; not a substitute for official full benchmark evaluation",
                "cases": len(tasks),
                "countsBySource": counts,
                "datasetsLibraryVersion": datasets.__version__,
                "huggingfaceHubLibraryVersion": huggingface_hub.__version__,
                "resolvedDatasetFingerprints": fingerprints,
                "sourcePolicy": "evaluation only; never use these rows for model training or prompt optimization",
                "revisionPolicy": "Every requested Hub revision (including default main or a tag) is resolved once to DatasetInfo.sha, and all dataset/config loading uses that immutable resolved commit SHA.",
                "screeningDesign": {
                    "optionOrder": "deterministic SHA-256 permutation for every forced-choice item",
                    "binarySources": "WiC, CoLA, and PAWS are approximately label-balanced in this fast screen",
                    "budgets": "engineering choices for cheap screening, not literature-derived construct weights",
                },
                "sources": sources,
            },
            indent=2,
        ) + "\n"
    )

    print(json.dumps({
        "cases": len(tasks),
        "countsBySource": counts,
        "datasetsVersion": datasets.__version__,
        "huggingfaceHubVersion": huggingface_hub.__version__,
        "resolvedRevisions": {name: meta["resolvedRevision"] for name, meta in source_revisions.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
