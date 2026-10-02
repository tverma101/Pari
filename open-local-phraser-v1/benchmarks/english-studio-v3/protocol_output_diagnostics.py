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
        "protocolVersion": 2,
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


def expected_token_limit(result: dict[str, Any], task: dict[str, Any]) -> int | None:
    if isinstance(task.get("maxNewTokens"), int):
        return int(task["maxNewTokens"])
    decoding = result.get("decoding") or {}
    key = "maxNewTokens" if task.get("generative") else "forcedChoiceMaxNewTokens"
    value = decoding.get(key)
    return int(value) if isinstance(value, int) else None


def annotate(result: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    output_rows = result.get("outputs", [])
    output_ids = [row.get("id") for row in output_rows if isinstance(row, dict)]
    duplicate_output_ids = sorted({str(x) for x in output_ids if output_ids.count(x) > 1})
    foreign_output_ids = sorted(str(x) for x in set(output_ids) - set(tasks))
    missing_output_ids = sorted(str(x) for x in set(tasks) - set(output_ids))

    for output in output_rows:
        if not isinstance(output, dict):
            continue
        task_id = output.get("id")
        task = tasks.get(task_id)
        if task is None:
            continue
        text = str(output.get("output") or "")
        finish_reason = output.get("finishReason")
        token_limit = expected_token_limit(result, task)
        token_count = output.get("completionTokenCount")
        likely_limit = (
            finish_reason is None
            and isinstance(token_count, int)
            and isinstance(token_limit, int)
            and token_count >= token_limit
        )
        is_word_studio = str(task.get("suite") or "").startswith("word_studio_")
        if is_word_studio:
            compare_source = task.get("selectedText") or task.get("sourceText")
            diag = diagnose_word_studio(
                text,
                source=compare_source,
                requested=int(task.get("requestedCount") or 10),
            )
            if finish_reason in {"length", "max_tokens", "token_limit"}:
                diag["statuses"] = list(dict.fromkeys([*diag["statuses"], "max_tokens_truncation"]))
            elif likely_limit:
                diag["statuses"] = list(dict.fromkeys([*diag["statuses"], "max_tokens_truncation_suspected"]))
            diag["finishReason"] = finish_reason
            diag["completionTokenCount"] = token_count
            diag["expectedTokenLimit"] = token_limit
            diag["kind"] = "word_studio"
        elif not task.get("generative"):
            diag = classify_choice(text, finish_reason)
            if likely_limit and "max_tokens_truncation" not in diag["statuses"]:
                diag["statuses"].append("max_tokens_truncation_suspected")
            diag["completionTokenCount"] = token_count
            diag["expectedTokenLimit"] = token_limit
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
            elif likely_limit:
                statuses.append("max_tokens_truncation_suspected")
            if text.strip().startswith("<think>") and "</think>" not in text:
                statuses.append("unclosed_thinking_block")
            if not statuses:
                statuses.append("ok")
            diag = {
                "protocolVersion": 2,
                "kind": "generative",
                "statuses": statuses,
                "finishReason": finish_reason,
                "completionTokenCount": token_count,
                "expectedTokenLimit": token_limit,
                "reasoningMarkersPresent": bool(REASONING_RE.search(text)),
            }
        for status in diag["statuses"]:
            counts[status] += 1
        annotated.append({"id": task_id, "diagnostics": diag})

    structural_statuses = []
    if duplicate_output_ids:
        structural_statuses.append("duplicate_output_ids")
    if foreign_output_ids:
        structural_statuses.append("foreign_output_ids")
    if missing_output_ids:
        structural_statuses.append("missing_output_ids")
    if len(output_rows) != len(tasks):
        structural_statuses.append("wrong_number_of_outputs")

    return {
        "version": 2,
        "sourceRunId": result.get("runId"),
        "expectedTaskCount": len(tasks),
        "outputCount": len(output_rows),
        "annotatedCount": len(annotated),
        "structuralStatuses": structural_statuses or ["ok"],
        "duplicateOutputIds": duplicate_output_ids,
        "foreignOutputIds": foreign_output_ids,
        "missingOutputIds": missing_output_ids,
        "statusCounts": dict(sorted(counts.items())),
        "rows": annotated,
        "interpretation": [
            "Diagnostics are protocol/format observations only; they do not replace lane-specific English scoring.",
            "recoverableExplicitChoice uses a frozen conservative parser and never consults gold labels.",
            "max_tokens_truncation_suspected is diagnostic when the runtime omitted an explicit finish reason but consumed the declared token limit.",
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"statusCounts": report["statusCounts"], "structuralStatuses": report["structuralStatuses"]}, indent=2))
    if report["structuralStatuses"] != ["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
