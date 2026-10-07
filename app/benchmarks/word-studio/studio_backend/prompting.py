#!/usr/bin/env python3
"""Compile stable, model-agnostic prompts for Pari Studio generation lanes."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import CandidateLane, LanePlan, Operation, SemanticMode, StudioRequest, detect_protected_spans


@dataclass(frozen=True)
class CompiledPrompt:
    system: str
    user: str
    lane: CandidateLane
    candidate_budget: int
    max_new_tokens: int
    temperature: float
    top_p: float


_SYSTEM = """You are Pari Word Studio, a precision English transformation engine.
Return editable alternatives, not commentary. Never invent facts, reasons, evidence,
outcomes, names, dates, numbers, or stronger claims. Preserve the writer's register
and intensity unless the requested operation explicitly changes them."""


_OPERATION = {
    Operation.REWRITE: "Rewrite the selected text with materially different natural wording or syntax.",
    Operation.REPLACE: "Replace only the selected text with context-valid equivalents.",
    Operation.SHORTEN: "Make the selected text shorter while preserving its intended meaning.",
    Operation.EXPAND: "Expand the selected text into a fuller natural expression without adding unsupported information.",
    Operation.COMPRESS_GIST: "Compress the selected text into a compact gist label; intentional detail loss is allowed, invention is not.",
    Operation.SPLIT: "Split the selected text into a clearer multi-sentence or multi-clause form while preserving claims and order.",
    Operation.JOIN: "Join the selected text into a more compact natural structure while preserving claims and order.",
    Operation.SIMPLIFY: "Use ordinary common English and simpler structure without weakening or strengthening the claim.",
    Operation.DIFFERENT_STRUCTURE: "Keep the meaning and voice but use a clearly different sentence structure.",
    Operation.PRESERVE_REGISTER: "Generate alternatives in the same register, intensity, and voice as the selected text.",
}


def _context(request: StudioRequest) -> str:
    start = max(0, request.selection.start - request.context_before_chars)
    end = min(len(request.document_text), request.selection.end + request.context_after_chars)
    return request.document_text[start:end]


def _semantic_rule(mode: SemanticMode) -> str:
    if mode == SemanticMode.INTENTIONAL_COMPRESSION:
        return "Preserve the central gist. Omission of secondary detail is intentional; do not introduce a new proposition."
    if mode == SemanticMode.CONTROLLED_EXPANSION:
        return "Preserve all supported meaning and make implicit wording more explicit only when the surrounding context supports it."
    return "Preserve actor roles, polarity, negation, modality, quantities, certainty, comparison direction, chronology, and logical relations."


def compile_prompt(request: StudioRequest, lane: LanePlan, semantic_mode: SemanticMode) -> CompiledPrompt:
    request.validate()
    detected = detect_protected_spans(request.document_text)
    combined = {span.text for span in (*detected, *request.protected_spans) if span.text}
    protected = "\n".join(f"- {value}" for value in sorted(combined)) or "- none detected"
    target = ""
    if request.target_min_words is not None or request.target_max_words is not None:
        target = (
            f"\nTarget word range: {request.target_min_words or 1}–"
            f"{request.target_max_words or 'unbounded'} words per alternative."
        )

    # Put the stable document/context block before per-lane search instructions so
    # repeated edits over the same paragraph maximize prefix-cache reuse.
    user = f"""DOCUMENT CONTEXT
{_context(request)}

PROTECTED VALUES
{protected}

SELECTED TEXT
{request.selected_text}

TRANSFORMATION
{_OPERATION[request.operation]}
{_semantic_rule(semantic_mode)}
Strength: {request.strength}/100. Strength controls wording/structure distance, not vocabulary sophistication or opinion intensity.{target}

SEARCH LANE
Lane: {lane.lane.value}
Candidate families: {', '.join(lane.families)}
Return exactly {lane.candidate_budget} distinct alternatives as JSON only:
{{"options":["...", "..."]}}
Do not include explanations, labels, markdown, or text outside the JSON object."""

    return CompiledPrompt(
        system=_SYSTEM,
        user=user,
        lane=lane.lane,
        candidate_budget=lane.candidate_budget,
        max_new_tokens=lane.max_new_tokens,
        temperature=lane.temperature,
        top_p=lane.top_p,
    )
