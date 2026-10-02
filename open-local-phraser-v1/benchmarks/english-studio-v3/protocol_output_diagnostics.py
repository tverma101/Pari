#!/usr/bin/env python3
"""Annotate benchmark outputs with deterministic protocol diagnostics.

This module never opens answer keys and never changes a model score. It separates
format/protocol behavior from linguistic correctness so runtime or formatting
problems are not mistaken for bad English.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from english_core_choice_parser import parse_choice_letter
from word_studio_output_parser import diagnose as diagnose_word_studio

STRICT_CHOICE_RE = re.compile(r"^\s*([A-Z])\s*$")
AMBIGUOUS_CHOICE_RE = re.compile(
    r"(?:^|\b)([A-Z])\s*(?:/|\bor\b|\band\b|&)\s*([A-Z])(?:\b|$)", re.I
)
REFUSAL_RE = re.compile(
    r"\b(?:i\s+(?:can(?:not|'t)|won't|will not)|unable to|cannot comply|"
    r"i must refuse|i have to refuse|as an ai)\b",
    re.I,
)
REASONING_RE = re.compile(
    r"(?:<think>|</think>|\b(?:let me think|reasoning|analysis|step[- ]by[- ]step)\b)",
    re.I,
)
ANSWER_CUE_RE = re.compile(r"\b(?:answer|option|choice|select|pick)\b", re.I)


def classify_choice(text: str, finish_reason: str | None = None) -> dict[str, Any]:
    raw = str(text or "")
    stripped = raw.strip()
    strict = STRICT_CHOICE_RE.fullmatch(raw)
    recoverable = parse_choice_letter(raw)
    ambiguous = bool(AMBIGUOUS_CHOICE_RE.search(stripped))
    has_reasoning = bool(REASONING_RE.search(stripped))
    refusal = bool(REFUSAL_RE.search(stripped))
    statuses: list[str] = []

    if raw == "":
        statuses.append("empty_output")
    elif not stripped:
        statuses.append("whitespace_only")

    if finish_reason in {"length", "max_tokens", "token_limit"}:
        statuses.append("max_tokens_truncation")
    if ambiguous:
        statuses.append("ambiguous_multiple_choices")
    if refusal:
        statuses.append("refusal_or_nonanswer")

    if stripped:
        if recoverable is None:
            if has_reasoning and not ANSWER_CUE_RE.search(stripped):
                statuses.append("reasoning_only_no_answer")
            elif not ambiguous and not refusal:
                statuses.append("malformed_choice")
        elif strict is None:
            if has_reasoning or len(stripped) > 2:
                statuses.append("reasoning_leak_with_answer")

    if stripped.startswith("<think>") and "</think>" not in stripped:
        statuses.append("unclosed_thinking_block")

    if not statuses:
        statuses.append("ok")

    return {
        "protocolVersion": 1,
        "statuses": statuses,
        "strictLetterOnly": strict.group(1) if strict else None,
        "recoverableExplicitChoice": recoverable,
        "recoverableDiffersFromStrict": bool(recoverable and not strict),
        "ambiguous": ambiguous,
        "refusalLike": refusal,
        "reasoningMarkersPresent": has_reasoning,
        "finishReason": finish_reason,
    }


def load_tasks(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        task_id = row.get("id")
        if not task_id or task_id in rows:
            raise SystemExit(f"invalid/duplicate task id in {path}: {task_id!r}")
        rows[task_id] = row
    return rows


def annotate(result: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    missing_task_ids: list[str] = []
    for output in result.get("outputs", []):
        task_id = output.get("id")
        task = tasks.get(task_id)
        if task is None:
            missing_task_ids.append(str(task_id))
            continue
        text = str(output.get("output") or "")
        finish_reason = output.get("finishReason")
        is_word_studio = str(task.get("suite") or "").startswith("word_studio_")
        if is_word_studio:
            diag = diagnose_word_studio(
                text,
                source=task.get("input") or task.get("sourceText"),
                requested=int(task.get("requestedCount") or 10),
            )
            if finish_reason in {"length", "max_tokens", "token_limit"}:
                diag["statuses"] = list(dict.fromkeys([*diag["statuses"], "max_tokens_truncation"]))
            diag["finishReason"] = finish_reason
            diag["kind"] = "word_studio"
        elif not task.get("generative"):
            diag = classify_choice(text, finish_reason)
            diag["kind"] = "forced_choice"
        else:
            statuses: list[str] = []
            if text == "":
                statuses.append("empty_output")
            elif not text.strip():
                statuses.append("whitespace_only")
            if REFUSAL_RE.search(text):
                statuses.append("refusal_or_nonanswer")
            if finish_reason in {"length", "max_tokens", "token_limit"}:
                statuses.append("max_tokens_truncation")
            if text.strip().startswith("<think>") and "</think>" not in text:
                statuses.append("unclosed_thinking_block")
            if not statuses:
                statuses.append("ok")
            diag = {
                "protocolVersion": 1,
                "kind": "generative",
                "statuses": statuses,
                "finishReason": finish_reason,
                "reasoningMarkersPresent": bool(REASONING_RE.search(text)),
            }
        for status in diag["statuses"]:
            counts[status] += 1
        annotated.append({"id": task_id, "diagnostics": diag})

    return {
        "version": 1,
        "sourceRunId": result.get("runId"),
        "outputCount": len(result.get("outputs", [])),
        "annotatedCount": len(annotated),
        "missingTaskIds": missing_task_ids,
        "statusCounts": dict(sorted(counts.items())),
        "rows": annotated,
        "interpretation": [
            "Diagnostics are protocol/format observations only; they do not replace lane-specific English scoring.",
            "recoverableExplicitChoice uses a frozen conservative parser and never consults gold labels.",
            "Runtime failures are handled separately by kaggle_failure_taxonomy.py and must not become English zeros.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", type=Path)
    ap.add_argument("tasks", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    tasks = load_tasks(args.tasks)
    report = annotate(result, tasks)
    if report["missingTaskIds"]:
        raise SystemExit(f"result contains IDs missing from task file: {report['missingTaskIds'][:10]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["statusCounts"], indent=2))


if __name__ == "__main__":
    main()
