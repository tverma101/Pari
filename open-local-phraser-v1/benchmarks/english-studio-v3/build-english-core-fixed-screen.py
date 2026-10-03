#!/usr/bin/env python3
"""Assemble the frozen 1,943-case model-visible English Core screen.

This concatenates already-built lane task files without changing their prompts,
order, labels, or benchmark weighting. Gold files are never opened or copied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANES = (
    ("shadow", "english-core-shadow.jsonl", 68, "author_labeled_unvalidated"),
    ("public_fast", "english-core-public-fast.jsonl", 1570, "public_prompted_fast"),
    ("semanticqa_lcc", "semanticqa-lcc-english-core.jsonl", 305, "public_prompted_native_protocol"),
)
GOLD_KEYS = {"answer", "answers", "label", "gold", "correct", "correct_answer", "expected"}
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# SemanticQA LCC renders its 8-category taxonomy into the prompt and the model
# answers with a category *name*, so its frozen allowed set is the ordered label
# list rather than first-N letters. The label set is pinned here from the
# benchmark's own taxonomy and cross-checked against the rendered prompt.
SEMANTICQA_LCC_LABELS = ("Magn", "AntiMagn", "Ver", "AntiVer", "Bon", "AntiBon", "Son", "Oper1")
SEMANTICQA_LCC_BENCHMARK = "SemanticQA-LCC-8cat"


def answer_protocol(row: dict, lane: str, line_number: int) -> str:
    """Resolve which frozen-answer contract a forced-choice row declares.

    A row that declares neither form is a contract bug: the caller reports it
    rather than guessing, so a missing set can never be silently accepted.
    """
    declared = row.get("answerProtocol")
    has_letters = row.get("allowedChoices") is not None
    has_labels = row.get("allowedAnswerLabels") is not None
    if has_letters and has_labels:
        # Checked before the declared protocol so an explicit declaration cannot
        # let a stale set from the other protocol ride along unexamined.
        raise SystemExit(
            f"{lane}:{line_number}: task declares both allowedChoices and allowedAnswerLabels; "
            "exactly one frozen answer protocol is allowed"
        )
    if declared is None:
        if has_letters and not has_labels:
            return "letter"
        if has_labels and not has_letters:
            return "label"
        raise SystemExit(
            f"{lane}:{line_number}: forced-choice task declares no frozen answer set "
            "(expected allowedChoices for a letter protocol or allowedAnswerLabels for a label protocol)"
        )
    if declared not in {"letter", "label"}:
        raise SystemExit(f"{lane}:{line_number}: unknown answerProtocol {declared!r}")
    if declared == "letter" and not has_letters:
        raise SystemExit(f"{lane}:{line_number}: answerProtocol 'letter' but allowedChoices is absent")
    if declared == "label" and not has_labels:
        raise SystemExit(f"{lane}:{line_number}: answerProtocol 'label' but allowedAnswerLabels is absent")
    return str(declared)


def validate_letter_choices(row: dict, lane: str, line_number: int) -> None:
    """Every forced-choice task must freeze a validated allowed label set.

    The set is model-visible task metadata derived from structured option
    metadata at build time, never from gold and never scraped from prompt prose
    at scoring time. Generative tasks must not carry one.
    """
    choices = row.get("allowedChoices")
    if row.get("generative"):
        if choices is not None:
            raise SystemExit(f"{lane}:{line_number}: generative task must not carry allowedChoices")
        return
    if choices is None:
        raise SystemExit(
            f"{lane}:{line_number}: forced-choice task is missing the frozen allowedChoices set"
        )
    if not isinstance(choices, list) or not choices:
        raise SystemExit(f"{lane}:{line_number}: allowedChoices must be a non-empty array")
    expected = list(ALPHABET[: len(choices)])
    if choices != expected:
        raise SystemExit(
            f"{lane}:{line_number}: allowedChoices must be the first N labels in order, got {choices}"
        )


def validate_letter_option_block(row: dict, lane: str, line_number: int) -> None:
    """Cross-check the frozen set against the rendered option lines.

    This is a build-time assertion that the derived set matches the prompt the
    model actually sees, not a scoring-time parser.
    """
    if row.get("generative"):
        return
    allowed = row["allowedChoices"]
    lines = row["prompt"].splitlines()
    rendered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) >= 2 and stripped[0].isalpha() and stripped[1] == ".":
            rendered.append(stripped[0])
        elif rendered:
            break
    if rendered != list(allowed):
        raise SystemExit(
            f"{lane}:{line_number}: rendered option labels {rendered} do not match "
            f"allowedChoices {list(allowed)}"
        )


def validate_label_choices(row: dict, lane: str, line_number: int) -> None:
    """A label-protocol task must freeze the pinned ordered category names.

    The names must be exactly the benchmark's 8-category taxonomy, in order, so
    an answer can never be read against a re-derived or reordered set.
    """
    labels = row["allowedAnswerLabels"]
    if not isinstance(labels, list) or not labels:
        raise SystemExit(f"{lane}:{line_number}: allowedAnswerLabels must be a non-empty array")
    if any(not isinstance(value, str) for value in labels):
        raise SystemExit(f"{lane}:{line_number}: allowedAnswerLabels entries must be strings")
    if len(set(labels)) != len(labels):
        raise SystemExit(f"{lane}:{line_number}: allowedAnswerLabels must not repeat a category")
    if tuple(labels) != SEMANTICQA_LCC_LABELS:
        raise SystemExit(
            f"{lane}:{line_number}: allowedAnswerLabels must be the ordered SemanticQA 8-category "
            f"taxonomy {list(SEMANTICQA_LCC_LABELS)}, got {labels}"
        )
    if row.get("benchmark") != SEMANTICQA_LCC_BENCHMARK:
        raise SystemExit(
            f"{lane}:{line_number}: label protocol is reserved for {SEMANTICQA_LCC_BENCHMARK}; "
            f"got benchmark {row.get('benchmark')!r}"
        )


def validate_label_block(row: dict, lane: str, line_number: int) -> None:
    """Cross-check the frozen label set against the rendered taxonomy block.

    The taxonomy is substituted into the prompt, so every allowed category name
    the model may answer with must actually be present in the prompt text.
    """
    missing = [label for label in row["allowedAnswerLabels"] if label not in row["prompt"]]
    if missing:
        raise SystemExit(
            f"{lane}:{line_number}: prompt does not render the allowed categories {missing}"
        )


def validate_allowed_choices(row: dict, lane: str, line_number: int) -> str:
    """Validate a forced-choice row against its declared frozen answer protocol."""
    protocol = answer_protocol(row, lane, line_number)
    if protocol == "letter":
        validate_letter_choices(row, lane, line_number)
        validate_letter_option_block(row, lane, line_number)
    else:
        validate_label_choices(row, lane, line_number)
        validate_label_block(row, lane, line_number)
    return protocol


def sha256_bytes(data: bytes) -> str:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=HERE / "english-core-fixed-screen.jsonl")
    ap.add_argument("--manifest", type=Path, default=HERE / "english-core-fixed-screen.manifest.json")
    args = ap.parse_args()

    task_lines: list[str] = []
    seen: set[str] = set()
    lane_records = []
    answer_protocol_counts: Counter[str] = Counter()
    for lane, filename, expected_count, evidence_status in LANES:
        source_path = HERE / filename
        if not source_path.is_file():
            raise SystemExit(f"Missing {source_path}; build each lane with its documented pinned source first")
        source_bytes = source_path.read_bytes()
        lines = [line for line in source_bytes.decode("utf-8").splitlines() if line.strip()]
        if len(lines) != expected_count:
            raise SystemExit(f"{lane}: expected {expected_count} cases, got {len(lines)}")
        lane_ids = []
        for line_number, line in enumerate(lines, 1):
            row = json.loads(line)
            if not isinstance(row, dict) or not row.get("id") or not isinstance(row.get("prompt"), str):
                raise SystemExit(f"{lane}:{line_number}: task needs a non-empty id and prompt")
            leaked = sorted(GOLD_KEYS.intersection(row))
            if leaked:
                raise SystemExit(f"{lane}:{line_number}: gold-bearing task fields are forbidden: {leaked}")
            if not row.get("generative"):
                answer_protocol_counts[validate_allowed_choices(row, lane, line_number)] += 1
            else:
                if row.get("allowedChoices") is not None or row.get("allowedAnswerLabels") is not None:
                    raise SystemExit(
                        f"{lane}:{line_number}: generative task must not carry a frozen answer set"
                    )
            task_id = row["id"]
            if task_id in seen:
                raise SystemExit(f"Duplicate task ID across lanes: {task_id}")
            seen.add(task_id)
            lane_ids.append(task_id)
            task_lines.append(line)
        lane_records.append({
            "lane": lane,
            "sourceFile": filename,
            "taskFileSha256": sha256_bytes(source_bytes),
            "cases": len(lines),
            "evidenceStatus": evidence_status,
            "taskIds": lane_ids,
        })

    combined = ("\n".join(task_lines) + "\n").encode("utf-8")
    if len(seen) != 1943:
        raise SystemExit(f"Frozen fixed screen must contain exactly 1,943 unique cases; got {len(seen)}")
    atomic_write(args.output, combined)
    manifest = {
        "version": 1,
        "screen": "english_studio_v3_fixed_1943",
        "cases": len(seen),
        "taskFile": str(args.output.resolve()),
        "taskFileSha256": sha256_bytes(combined),
        "sourcePolicy": "evaluation only; never train on these rows or tune prompts/weights after seeing results",
        "assemblyPolicy": "lane JSONL rows concatenated byte-for-byte after newline parsing; no prompt, option, or weighting changes",
        "allowedChoicesPolicy": "Every forced-choice task in every lane freezes exactly one model-visible answer set, declared by answerProtocol. A 'letter' protocol task carries allowedChoices as the first N labels for its N rendered options and the rendered 'A. ..' option block must match it; the letter-choice parser rejects any label outside that set as invalid_option_label, a parser/protocol correction rather than a model change. A 'label' protocol task (SemanticQA LCC 8-category) carries allowedAnswerLabels as the ordered benchmark taxonomy names, because the model answers with a category name and the prompt renders the taxonomy rather than lettered options. Generative tasks carry no frozen answer set. In both protocols the set is derived from structured metadata at build time, never from gold and never scraped from prompt prose at scoring time.",
        "answerProtocolCounts": dict(sorted(answer_protocol_counts.items())),
        "modelVisibleOnly": True,
        "goldPolicy": "answer keys remain in lane-specific files and are never read or included by this builder",
        "lanes": lane_records,
    }
    atomic_write(args.manifest, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"cases": len(seen), "taskFileSha256": manifest["taskFileSha256"], "lanes": {r["lane"]: r["cases"] for r in lane_records}}, indent=2))


if __name__ == "__main__":
    main()
