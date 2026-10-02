#!/usr/bin/env python3
"""Deterministic parser/diagnostics for Pari Word Studio candidate lists."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
COMMENTARY_PREFIX = re.compile(r"^(?:here(?:'s| are)|sure[,!:]|options?:|alternatives?:|note:)", re.I)
OPTIONS_ARRAY_PREFIX = re.compile(r'"options"\s*:\s*\[', re.I)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def parse_options(raw: str) -> tuple[list[str], str]:
    text = (raw or "").strip()
    if not text:
        return [], "empty_output"
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("options"), list):
            vals = [str(x).strip() for x in obj["options"] if str(x).strip()]
            return vals, "json_object"
        if isinstance(obj, list):
            vals = [str(x).strip() for x in obj if str(x).strip()]
            return vals, "json_array"
    except Exception:
        pass

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    bullet_values: list[str] = []
    bullet_matches = 0
    for line in lines:
        m = BULLET_RE.match(line)
        if m:
            bullet_matches += 1
            bullet_values.append(m.group(1).strip())
    if lines and bullet_matches == len(lines):
        return bullet_values, "numbered_or_bulleted_list"

    if 2 <= len(lines) <= 40 and all(not COMMENTARY_PREFIX.match(line.strip()) for line in lines):
        return [line.strip() for line in lines], "newline_list"

    return [], "unparseable"


def partial_candidate_count(raw: str) -> int:
    """Count only fully completed candidates in an in-progress stream.

    This is intentionally conservative. For JSON output it counts completed JSON
    string elements only inside the `options` array. It never guesses from prose.
    """
    text = str(raw or "")
    complete, _ = parse_options(text)
    if complete:
        return len(complete)

    prefix = OPTIONS_ARRAY_PREFIX.search(text)
    if prefix:
        body = text[prefix.end():]
        count = 0
        in_string = False
        escape = False
        saw_nonspace = False
        for ch in body:
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                    count += 1
                continue
            if ch == '"':
                in_string = True
                saw_nonspace = True
            elif ch == "]":
                break
            elif not ch.isspace() and ch not in {",", "["}:
                saw_nonspace = True
        if count or saw_nonspace:
            return count

    # For streamed numbered/bulleted output, count only lines already matching a
    # full list item. A prose preamble intentionally yields zero.
    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        matches = [BULLET_RE.match(line) for line in lines]
        if all(matches):
            return sum(1 for match in matches if match)
    return 0


def diagnose(raw: str, source: str | None = None, requested: int = 10) -> dict[str, Any]:
    options, parser = parse_options(raw)
    norms = [normalize(x) for x in options]
    unique_norms = set(norms)
    source_norm = normalize(source) if source else None
    duplicates = len(norms) - len(unique_norms)
    unchanged = sum(1 for n in norms if source_norm and n == source_norm)
    commentary = sum(1 for x in options if COMMENTARY_PREFIX.match(x.strip()))
    statuses: list[str] = []
    if not raw or not raw.strip():
        statuses.append("empty_output")
    if parser == "unparseable":
        statuses.append("word_studio_unparseable_list")
    if len(options) < requested:
        statuses.append("word_studio_too_few_candidates")
    if duplicates > max(1, requested // 5):
        statuses.append("word_studio_excessive_duplicates")
    if unchanged:
        statuses.append("contains_unchanged_source")
    if commentary:
        statuses.append("contains_commentary")
    if not statuses:
        statuses.append("ok")
    return {
        "parserVersion": 2,
        "parserMode": parser,
        "statuses": statuses,
        "requestedCount": requested,
        "parsedCount": len(options),
        "uniqueNormalizedCount": len(unique_norms),
        "duplicateCount": duplicates,
        "unchangedSourceCount": unchanged,
        "commentaryCandidateCount": commentary,
        "lengthChars": [len(x) for x in options],
        "options": options,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="JSON result with outputs[] rows containing output text")
    ap.add_argument("output", type=Path)
    ap.add_argument("--requested", type=int, default=10)
    args = ap.parse_args()
    run = json.loads(args.input.read_text(encoding="utf-8"))
    rows = []
    for row in run.get("outputs", []):
        rows.append({"id": row.get("id"), "diagnostics": diagnose(str(row.get("output") or ""), requested=args.requested)})
    summary = {
        "version": 2,
        "sourceResult": str(args.input),
        "rows": rows,
        "counts": {
            key: sum(1 for r in rows if key in r["diagnostics"]["statuses"])
            for key in sorted({s for r in rows for s in r["diagnostics"]["statuses"]})
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary["counts"], indent=2))


if __name__ == "__main__":
    main()
