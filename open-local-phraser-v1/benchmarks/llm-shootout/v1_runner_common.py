"""Shared prompt/render/parse helpers for Pari English Studio V1 shootouts.

This module deliberately separates benchmark task semantics from model transport.
Direct MLX, llama.cpp, Bonsai, or any OpenAI-compatible runtime should receive the
same behavioral contract, with only the runtime/chat wrapper changing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE = ROOT / "benchmarks/english-studio-v3/v1-core.internal.jsonl"
CONTRACTS_PATH = ROOT / "benchmarks/english-studio-v3/v1-prompt-contracts.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_contracts() -> dict[str, Any]:
    return json.loads(CONTRACTS_PATH.read_text())


def strength_instruction(contracts: dict[str, Any], strength: int | None) -> str:
    chosen = int(strength or 40)
    table = contracts["strength"]
    if str(chosen) not in table:
        raise ValueError(f"Unsupported rewrite strength {chosen}; expected one of {sorted(table)}")
    return table[str(chosen)]


def global_rules(contracts: dict[str, Any]) -> str:
    return "\n".join(f"- {rule}" for rule in contracts["globalRules"])


def render_prompt(case: dict[str, Any], *, strength: int | None = None, candidate_count: int | None = None) -> str:
    contracts = load_contracts()
    route = case["route"]
    context = case["input"]
    selected = case.get("selection")
    rules = global_rules(contracts)
    strength_text = strength_instruction(contracts, strength)

    if route in {"paragraph_first_draft", "safety_meaning", "strength_register"}:
        return f"""You are assisting a human who will edit the result manually.

Task: produce ONE useful rewritten draft of the text below.
Rewrite strength: {strength or 40}/90-ish scale.
Strength behavior: {strength_text}

Global rules:
{rules}
- Preserve paragraph boundaries where they carry meaning.
- Do not summarize.
- Do not explain your edits.

Source text:
<context>
{context}
</context>

Return only the rewritten text."""

    if route in {"word_phrase_alternatives", "protected_containment", "local_edit_containment"}:
        if not selected:
            raise ValueError(f"{route} requires an explicit selected span: {case.get('instanceId')}")
        count = int(candidate_count or 10)
        return f"""You are generating replacement wording for a human-controlled editor.

Full context:
<context>
{context}
</context>

Selected span:
<selection>{selected}</selection>

Generate {count} materially different replacement candidates for ONLY the selected span.
The human will insert one candidate back into the original context.

Rules:
{rules}
- The replacement may be much shorter or longer than the selected span.
- One word may become several words; several words may become one word.
- Every candidate must fit grammatically when inserted into the full context.
- Preserve the selected span's meaning, intensity, tense, negation and role in context.
- Do not rewrite or quote unrelated surrounding text.
- Avoid near-duplicate candidates.
- Prefer ordinary natural English over academic/thesaurus inflation.

Return exactly one replacement candidate per line. No explanations, labels, numbering, or commentary."""

    if route == "sentence_alternatives":
        if not selected:
            raise ValueError(f"sentence_alternatives requires a selected sentence: {case.get('instanceId')}")
        count = int(candidate_count or 5)
        return f"""You are generating sentence alternatives for a human-controlled editor.

Paragraph context:
<context>
{context}
</context>

Selected sentence or clause:
<selection>{selected}</selection>

Generate {count} materially different replacement alternatives for the selected text only.

Rules:
{rules}
- Preserve every supported claim, relationship, negation and uncertainty.
- Vary sentence/clause structure rather than merely swapping synonyms.
- Keep approximately the same register and vocabulary level.
- Do not make the text more academic or verbose by default.
- Do not rewrite unrelated surrounding text.

Return exactly one replacement candidate per line. No explanations, labels, numbering, or commentary."""

    raise ValueError(f"Unsupported V1 route: {route}")


def expanded_jobs(case: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Expand correlated settings without pretending they are unique source examples."""
    if case["route"] == "strength_register":
        for strength in case.get("strengths", [15, 40, 60, 90]):
            yield {**case, "runVariant": f"strength-{strength}", "strength": int(strength)}
        return

    if case["route"] == "word_phrase_alternatives":
        yield {**case, "runVariant": "candidates-10", "candidateCount": 10, "strength": 40}
        return

    if case["route"] == "sentence_alternatives":
        yield {**case, "runVariant": "candidates-5", "candidateCount": 5, "strength": 40}
        return

    if case["route"] in {"protected_containment", "local_edit_containment"}:
        yield {**case, "runVariant": "candidates-5", "candidateCount": 5, "strength": 40}
        return

    yield {**case, "runVariant": "default", "strength": 40}


def strip_control_text(text: str) -> str:
    value = text.strip()
    if value.startswith("<think>"):
        end = value.find("</think>")
        if end != -1:
            value = value[end + len("</think>") :].strip()
    return value.strip()


_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[A-Za-z][.)])\s+")


def parse_candidates(raw: str, limit: int | None = None) -> list[str]:
    """Parse common list formats while preserving candidate text for later scoring."""
    text = strip_control_text(raw)
    candidates: list[str] = []

    # Prefer a valid JSON string array when a model happens to return one.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
            candidates = [x.strip() for x in parsed if x.strip()]
    except json.JSONDecodeError:
        pass

    if not candidates:
        for line in text.splitlines():
            line = _PREFIX.sub("", line).strip()
            line = line.strip('"“”')
            if not line:
                continue
            if line.lower().startswith(("candidate:", "replacement:")):
                line = line.split(":", 1)[1].strip()
            if line:
                candidates.append(line)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = " ".join(candidate.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if limit is not None and len(unique) >= limit:
            break
    return unique


def is_candidate_route(route: str) -> bool:
    return route in {
        "word_phrase_alternatives",
        "sentence_alternatives",
        "protected_containment",
        "local_edit_containment",
    }
