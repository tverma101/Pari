#!/usr/bin/env python3
"""Run Pari's bundled MLX paraphrase model for one native request.

The worker is deliberately one-shot. A process boundary keeps the MLX graph
and allocator out of the WebKit process and makes a failed or missing runtime
recoverable without changing the browser editor's deterministic fallback.
"""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _context_value(context: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in context:
            return context[key]
    return default


def _compact_style_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _protected_placeholder(index: int) -> str:
    """Use a one-character private marker so protected values cannot overlap it."""
    codepoint = 0xE100 + index
    if codepoint > 0xF8FF:
        codepoint = 0xF0000 + index - 0x1800
    return "\ue000" + chr(codepoint) + "\ue001"


def _mask_protected_spans(value: str, spans: list[str]) -> tuple[str, list[str]]:
    """Replace protected text in one pass, preferring the longest overlapping span."""
    ordered = sorted(
        {str(span).strip() for span in spans if str(span).strip()},
        key=lambda span: (-len(span), span.casefold(), span),
    )
    if not ordered:
        return value, ordered
    pattern = re.compile("|".join(re.escape(span) for span in ordered))
    placeholders = {span: _protected_placeholder(index) for index, span in enumerate(ordered)}
    masked = pattern.sub(lambda match: placeholders[match.group(0)], value)
    return masked, ordered


def _restore_protected_spans(value: str, ordered: list[str]) -> str:
    for index, span in enumerate(ordered):
        value = value.replace(_protected_placeholder(index), span)
    return value


def render_style_context(request: dict[str, Any]) -> str:
    """Render bounded approval memory as style guidance, never as source facts."""
    raw_context = request.get("style_context")
    if not isinstance(raw_context, dict):
        return ""

    lines = [
        "Learned local style context:",
        "- The current paragraph is the only source of facts. Use these approved examples only to learn voice, rhythm, and wording preferences; do not copy their topic, names, numbers, links, dates, or claims into the current rewrite.",
    ]

    examples = _context_value(raw_context, "approvedExamples", "approved_examples", default=[])
    if isinstance(examples, list):
        for index, example in enumerate(examples[:3], start=1):
            if not isinstance(example, dict):
                continue
            source = _compact_style_text(_context_value(example, "originalText", "original_text"), 420)
            approved = _compact_style_text(_context_value(example, "finalText", "final_text"), 420)
            if source and approved:
                lines.append(f'- Approved example {index} (style only): source="{source}" -> approved="{approved}"')

    replacements = _context_value(raw_context, "preferredReplacements", "preferred_replacements", default=[])
    replacement_lines: list[str] = []
    if isinstance(replacements, list):
        for entry in replacements[:12]:
            if not isinstance(entry, dict):
                continue
            original = _compact_style_text(_context_value(entry, "original"), 80)
            replacement = _compact_style_text(_context_value(entry, "replacement"), 80)
            if original and replacement:
                replacement_lines.append(f"{original} -> {replacement}")
    if replacement_lines:
        lines.append("- Repeatedly approved wording preferences (use only when the grammar and meaning fit): " + "; ".join(replacement_lines))

    avoided = _context_value(raw_context, "avoidedPhrases", "avoided_phrases", default=[])
    avoided_lines = [
        _compact_style_text(phrase, 80)
        for phrase in (avoided[:8] if isinstance(avoided, list) else [])
        if _compact_style_text(phrase, 80)
    ]
    if avoided_lines:
        lines.append("- Phrases the writer has reverted before; avoid them when a natural equivalent preserves the meaning: " + ", ".join(avoided_lines))

    contractions = _context_value(raw_context, "preferredContractions", "preferred_contractions", default=[])
    contraction_lines = [
        _compact_style_text(contraction, 32)
        for contraction in (contractions[:8] if isinstance(contractions, list) else [])
        if _compact_style_text(contraction, 32)
    ]
    if contraction_lines:
        lines.append("- Preferred contractions when they fit the selected mode and sentence: " + ", ".join(contraction_lines))

    sentence_preference = _context_value(raw_context, "sentencePreference", "sentence_preference")
    if sentence_preference in {"shorter", "longer", "similar"}:
        lines.append(f"- The writer usually approves sentence lengths that are {sentence_preference}; preserve clarity and the source relationship first.")

    return "\n".join(lines) if len(lines) > 2 else ""


def build_instruction(request: dict[str, Any]) -> str:
    original = str(request.get("original_text", "")).strip()
    mode = str(request.get("mode", "personal")).strip().lower()
    protected = request.get("protected_spans", [])
    protected_text = ", ".join(
        f"{index + 1}. {str(span).strip()}"
        for index, span in enumerate(protected)
        if str(span).strip()
    )
    strength = int(request.get("strength", 56))
    repair_pass = bool(request.get("repair_pass", False))
    custom_instructions = str(request.get("custom_instructions", "")).strip()
    style_tweaks = request.get("style_tweaks") if isinstance(request.get("style_tweaks"), dict) else {}
    if mode == "warmth":
        variation = "Make the wording noticeably warmer and more human. Replace robotic, cold, cynical, or needlessly harsh phrasing with considerate, natural English. Keep the writer's honest meaning, including real problems, limits, disagreement, and negative facts; do not add cheerleading, fake empathy, or praise. Prefer clear contractions and direct human phrasing when they fit."
    elif strength >= 75:
        variation = "Make a substantial, natural wording change across the paragraph. Prefer fresh sentence framing and meaningful phrase changes over a pile of thesaurus substitutions."
    elif strength >= 50:
        variation = "Make a clearly noticeable wording change while keeping the original voice, detail, and factual emphasis. Use natural phrase alternatives where they fit."
    elif strength >= 25:
        variation = "Make a balanced wording change: refresh several useful phrases but preserve familiar sentence framing when it already reads well."
    else:
        variation = "Make a light, natural wording change and keep familiar phrasing where it is already good."

    structure_guidance = (
        "At this Deep Rewrite amount, make a deep structural paraphrase: vary sentence openings, clause order, and grammatical framing across the paragraph instead of merely replacing isolated words. Aim to reframe at least two intact sentences, and recast a substantial clause in more sentences when natural, while keeping the same sentence count, every proposition, and every cause, contrast, condition, and time relationship explicit. Keep the result natural and readable; do not make it artificially formal."
        if strength >= 82
        else
        "At this Strong Rewrite amount, make one or more safe sentence-level structural changes when the paragraph allows them: vary a sentence opening or move a clear relationship clause instead of relying only on isolated synonym substitutions. Preserve the source sentence count, propositions, and relationships."
        if strength >= 69
        else ""
    )

    protected_block = protected_text or "None detected; still preserve all names, numbers, links, dates, and quoted text."
    repair_block = (
        "This is a stricter repair pass after an earlier draft failed a quality check. Before you answer, silently audit the draft for missing or added negation, changed modal force, changed quantity words, changed point of view, broken verb frames, filler openings, and choppy sentence flow. Correct those issues while retaining every recoverable fact. Return only the final paragraph."
        if repair_pass
        else ""
    )
    custom_block = ""
    if custom_instructions:
        custom_block += f"\n- Custom mode guidance: {custom_instructions}\n- Treat custom guidance as a bounded style preference only. Never override meaning, grammar, protected facts, or safety checks."
    if style_tweaks.get("warmthPolish") is True:
        custom_block += "\n- This custom mode requests a warmer final register: use human, considerate wording without changing honest negative facts."
    if style_tweaks.get("preserveSentenceCount") is True:
        custom_block += "\n- This custom mode prefers the source sentence count whenever the source is not genuinely broken."
    style_context_block = render_style_context(request)
    return f"""Rewrite the text below as a careful, highly capable English editor.

Rules:
- Return only the rewritten paragraph. Do not add a title, preface, bullets, explanation, or quotation marks.
- This is paraphrasing, not summarizing: preserve every fact, detail, number, name, link, date, measurement, quoted phrase, code-like fragment, negation, modality, tense, person, and cause/result/contrast/condition relationship.
- Keep the same number of sentences unless the source is genuinely broken or fragmentary. When the source has fragments, missing punctuation, bad capitalization, repeated words, or broken grammar, rebuild it into complete, grammatical sentences while preserving every recoverable fact; do not invent information.
- Improve sentence flow, cohesion, parallel structure, punctuation, and ordinary English grammar. Prefer clear, natural wording over thesaurus substitutions.
- Keep the subject and the writer's point of view. Do not turn first person into a generic statement.
- Keep every quantity word's scope and strength exactly. In particular, do not turn “most” into “many”, “some” into “few”, or “all” into “many” just to make the wording different.
- If the source is terse or fragmentary, connect the ideas into a readable paragraph instead of preserving choppy three-word fragments.
- Make vague wording clearer only with facts already present; never invent a person, cause, amount, event, or outcome.
- A standalone fragment beginning with “Because of …” or “Due to …” must become a complete sentence that names only that stated cause (for example, “The cause was …”); a standalone “Waiting …” fragment must keep its original object without inventing who is waiting.
- When a dense noun stack ends with “is pending … status,” make it grammatical by putting the stated status first (for example, “The completion status of the implementation review is pending”); preserve every stated noun and do not add a cause or outcome.
- {repair_block}
- {variation}
- {structure_guidance}
- {custom_block}
{style_context_block}
- Protected spans that must appear exactly in the result: {protected_block}

Original paragraph:
{original}

Rewritten paragraph:"""


def render_prompt(tokenizer: Any, instruction: str) -> str:
    messages = [{"role": "user", "content": instruction}]
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
    return instruction + "\n\nRewritten paragraph:"


def clean_output(value: str) -> str:
    value = value.strip()
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"</?(?:analysis|reasoning)>", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^```(?:text|markdown)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    value = re.sub(r"^\s*(?:rewritten paragraph|paraphrase)\s*:\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*#+\s+[^\n]+\n", "", value)
    value = re.sub(r"^\s*\*\*?(?:rewritten paragraph|paraphrase)\*\*?\s*:\s*", "", value, flags=re.IGNORECASE)
    if re.search(r"\brewritten paragraph:\s*", value, flags=re.IGNORECASE):
        value = re.split(r"\brewritten paragraph:\s*", value, flags=re.IGNORECASE)[-1]
    return value.strip().strip('"“”')


def looks_like_control_echo(value: str) -> bool:
    markers = [
        r"\breturn only the rewritten paragraph\b",
        r"\bevery fact, detail, number, name, link, date\b",
        r"\bprotected spans that must appear\b",
        r"\bthe rewritten paragraph should\b",
        r"\bthe goal is to produce a\b",
        r"\boriginal paragraph:\s*",
    ]
    return sum(bool(re.search(marker, value, flags=re.IGNORECASE)) for marker in markers) >= 1


def _article_for(value: str) -> str:
    return "an" if re.match(r"[aeiou]", value.strip(), flags=re.IGNORECASE) else "a"


def _capitalize_sentence(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def _lower_sentence_start(value: str) -> str:
    if not value or re.match(r"I(?:\b|')", value):
        return value
    return value[:1].lower() + value[1:]


def _repair_punctuation_spacing(value: str) -> str:
    """Keep standard meridiem abbreviations intact during repair passes."""
    value = re.sub(r"\b([ap])\.\s*m\.?", lambda match: f"{match.group(1).lower()}.m.", value, flags=re.IGNORECASE)

    def spacing(match: re.Match[str]) -> str:
        punctuation = match.group(1)
        before = value[:match.start() + 1]
        after = value[match.end():]
        if punctuation == "." and re.search(r"(?:^|\s)(?:a|p)\.$", before, flags=re.IGNORECASE) and re.match(r"\s*m(?:\b|[.\s])", after, flags=re.IGNORECASE):
            return punctuation
        return f"{punctuation} "

    return re.sub(r"([,.;!?])(?=[A-Za-z])", spacing, value)


def _capitalize_sentence_starts(value: str) -> str:
    def capitalize(match: re.Match[str]) -> str:
        before = value[:match.start() + 1]
        if re.search(r"\b(?:a|p)\.m\.$", before, flags=re.IGNORECASE):
            return match.group(0)
        return f"{match.group(1)}{match.group(2).upper()}"

    return re.sub(r"(^|[.!?]\s+)([a-z])", capitalize, value)


def _split_repair_fragments(value: str) -> list[str]:
    """Split repair fragments while treating `a.m.`/`p.m.` as one token."""
    marker = "\ue200"
    masked = re.sub(
        r"\b([ap])\.m\.",
        lambda match: f"{match.group(1)}{marker}m{marker}",
        value,
        flags=re.IGNORECASE,
    )
    return [
        part.replace(marker, ".").strip()
        for part in re.split(r"(?:[.!?]+\s*|\r?\n+)", masked)
        if part.strip()
    ]


def _normalize_note_action(action: str, issue: str | None = None) -> str | None:
    protected_marker = r"\ue000[\s\S]\ue001"
    value = re.sub(r"\s+", " ", re.sub(r"[.!?]+$", "", action)).strip()
    if not value:
        return None
    value = re.sub(r"\bno\s+blame\b", "without assigning blame", value, flags=re.IGNORECASE)
    value = re.sub(r"\bwithout\s+blaming\b", "without assigning blame", value, flags=re.IGNORECASE)
    value = re.sub(r"\bkeep\s+message\s+short\b", "keep the message short", value, flags=re.IGNORECASE)
    value = re.sub(r"\bsend\s+update\b", "send an update", value, flags=re.IGNORECASE)
    value = re.sub(r"\bwrite\s+update\b", "write an update", value, flags=re.IGNORECASE).strip()
    follow_up_match = re.search(r"\s+send\s+(?:an?\s+)?update\s+before\s+(.+)$", value, flags=re.IGNORECASE)
    follow_up = f"Send an update before {follow_up_match.group(1).strip()}" if follow_up_match else ""
    if follow_up_match:
        value = value[:follow_up_match.start()].strip()
    if not value and not follow_up:
        return None
    if not value:
        return follow_up
    if issue and re.match(r"^explain\s+(?=(?:clearly\b|without\b|and\b))", value, flags=re.IGNORECASE):
        value = re.sub(r"^explain\b", f"explain the {issue}", value, count=1, flags=re.IGNORECASE)
    if issue and re.match(r"^explain\s+without\b", value, flags=re.IGNORECASE):
        value = re.sub(r"^explain\b", f"explain the {issue}", value, count=1, flags=re.IGNORECASE)
    elif issue and re.match(r"^explain\b", value, flags=re.IGNORECASE):
        value = re.sub(r"^explain\b", f"explain the {issue}", value, count=1, flags=re.IGNORECASE)
    if issue:
        value = re.sub(
            rf"(explain\s+the\s+{re.escape(issue)})\s+({protected_marker})\s+blame\s+and\s+keep\b",
            r"\1, with \2 blame, and keep",
            value,
            flags=re.IGNORECASE,
        )
    def with_follow_up(main: str) -> str:
        return f"{main}. {follow_up}" if follow_up else main

    if re.match(r"^I\s+need\b", value, flags=re.IGNORECASE):
        return with_follow_up(_capitalize_sentence(value))
    if re.match(r"^(?:explain|send|write|review|fix|finish|make|understand|organize|ask|call|check|clarify|keep|address|rewrite|prepare|share|follow)\b", value, flags=re.IGNORECASE):
        return with_follow_up(f"I need to {_lower_sentence_start(value)}")
    return with_follow_up(f"I need {_lower_sentence_start(value)}")


def _normalize_note_subject(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        return None
    state_match = re.match(
        r"^(?:the\s+)?(client|customer|team|manager|user|project|draft|report)\s+(upset|concerned|angry|frustrated|delayed|late|unclear|missing|ready|broken|unfinished|waiting)(?:\s+(?:(?:about|over|due\s+to|for)\s+)?(?:the\s+)?(.+))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if state_match:
        subject, state, remainder = state_match.groups()
        subject_text = f"The {subject.lower()}"
        if not remainder:
            return f"{subject_text} is {state.lower()}"
        remainder = remainder.strip()
        if state.lower() == "waiting":
            waiting_for = remainder if re.match(r"^(?:for|on)\b", remainder, flags=re.IGNORECASE) else f"for {_article_for(remainder)} {remainder}"
            return f"{subject_text} is waiting {waiting_for}"
        return f"{subject_text} is {state.lower()} about the {remainder}"
    if re.match(r"^deadline\s+missed$", normalized, flags=re.IGNORECASE):
        return "The deadline was missed"
    if re.match(r"^meeting\s+(?:today|tomorrow)$", normalized, flags=re.IGNORECASE):
        return _capitalize_sentence(normalized)
    return None


def plan_note_stream(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", re.sub(r"[.!?]+$", "", value)).strip()
    if not normalized or re.search(r"[.!?]", normalized) or len(re.findall(r"[A-Za-z0-9']+", normalized)) < 6:
        return None

    meeting_match = re.match(
        r"^meeting\s+(today|tomorrow)\s+(?:(?:with\s+)?(?:the\s+)?)(client|customer|team|manager|user)\s+(?:who\s+)?(?:is\s+)?(upset|concerned|angry|frustrated)\s+(?:(?:about|over|due\s+to)\s+)?(?:the\s+)?(delay|problem|issue|change)\s+need\s+(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if meeting_match:
        day, entity, emotion, issue, action = meeting_match.groups()
        entity_text = f"a {entity.lower()}" if entity.lower() in {"client", "customer"} else f"the {entity.lower()}"
        action_sentence = _normalize_note_action(action, issue.lower())
        if action_sentence:
            return f"{_capitalize_sentence(day)}'s meeting is with {entity_text} who is {emotion.lower()} about the {issue.lower()}. {action_sentence}."

    paired_status = re.match(
        r"^(?:the\s+)?(deadline)\s+missed\s+(?:the\s+)?(client|customer|team|manager|user)\s+waiting\s+(?:for\s+)?(?:the\s+)?(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if paired_status:
        subject, entity, remainder = paired_status.groups()
        return f"The {subject.lower()} was missed, and the {entity.lower()} is waiting for {_article_for(remainder)} {remainder}."

    tokens = normalized.split()
    action_index = next((index for index, token in enumerate(tokens) if index > 1 and re.match(r"^(?:need|must|should)$", token, flags=re.IGNORECASE)), None)
    if action_index is not None:
        subject = _normalize_note_subject(" ".join(tokens[:action_index]))
        action = _normalize_note_action(" ".join(tokens[action_index + 1:]))
        if subject and action:
            return f"{_capitalize_sentence(subject)}. {action}."
    return None


def has_standalone_note_fragment(value: str) -> bool:
    fragments = [part.strip() for part in re.split(r"(?:[.!?]+\s*|\r?\n+)", value) if part.strip()]
    return any(
        re.match(r"^(?:because\s+of|due\s+to)\s+[^,;:]+$", fragment, flags=re.IGNORECASE)
        or re.match(r"^(?:still\s+)?waiting\s+(?:on|for)\s+.+$", fragment, flags=re.IGNORECASE)
        or re.match(r"^(?:not\s+sure|no\s+idea)\s+.+$", fragment, flags=re.IGNORECASE)
        for fragment in fragments
    )


def repair_pending_status_phrase(value: str) -> str:
    """Reorder one recognizable note-style status frame without adding facts."""
    match = re.match(
        r"^The\s+(.+?)\s+is\s+pending\s+((?:(?:its|the|a|an)\s+)?[^.!?,;:]+?)\s+status([.!?])?$",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return value

    subject = re.sub(r"\s+", " ", match.group(1)).strip()
    status = re.sub(r"^(?:its|the|a|an)\s+", "", match.group(2), flags=re.IGNORECASE)
    status = re.sub(r"\s+", " ", status).strip()
    subject_word_count = len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", subject))
    status_word_count = len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", status))
    if (
        subject_word_count < 3
        or subject_word_count > 12
        or status_word_count < 1
        or status_word_count > 4
        or re.search(r"\b(?:is|are|was|were|has|have)\b", status, flags=re.IGNORECASE)
    ):
        return value

    subject_with_article = (
        subject
        if re.match(r"^(?:the|a|an|my|your|our|their|his|her|its)\b", subject, flags=re.IGNORECASE)
        else f"the {subject}"
    )
    return f"The {status} status of {subject_with_article} is pending{match.group(3) or ''}"


def repair_fragmentary_prose(value: str, request: dict[str, Any]) -> str:
    """Repair obvious note fragments after generation without inventing facts."""
    protected = [str(span).strip() for span in request.get("protected_spans", []) if str(span).strip()]
    original_text = str(request.get("original_text", ""))
    repair_standalone_notes = has_standalone_note_fragment(original_text)
    original_fragments = _split_repair_fragments(original_text)
    masked, ordered_protected = _mask_protected_spans(value, protected)

    def plural_subject(subject: str) -> bool:
        last = subject.strip().split()[-1].lower() if subject.strip() else ""
        if last in {"people", "children", "men", "women", "they", "we", "you", "these", "those"}:
            return True
        return last.endswith("s") and not last.endswith(("ss", "us", "is"))

    no_word_pattern = r"(?:no|\ue000\d+\ue001)"
    no_contest_pattern = re.compile(rf"^{no_word_pattern}\s+contest$", flags=re.IGNORECASE)
    no_idea_pattern = re.compile(rf"^({no_word_pattern})\s+idea\s+where\s+(.+)$", flags=re.IGNORECASE)

    def normalize(fragment: str) -> str:
        item = re.sub(r"^[-*•]+\s*", "", re.sub(r"\s+", " ", re.sub(r"\.{2,}", ".", fragment))).strip()
        if not item:
            return item
        item = repair_pending_status_phrase(item)
        # Add grammatical scaffolding only when the source had the same
        # subjectless note shape. This never supplies an invented actor or
        # outcome to a fragment created by the model.
        if repair_standalone_notes:
            item = re.sub(r"^because\s+of\s+(.+)$", r"The cause was \1", item, flags=re.IGNORECASE)
            item = re.sub(r"^due\s+to\s+(.+)$", r"The reason was \1", item, flags=re.IGNORECASE)
            item = re.sub(r"^still\s+waiting\s+(on|for)\s+(.+)$", r"I am still waiting \1 \2", item, flags=re.IGNORECASE)
            item = re.sub(r"^waiting\s+(on|for)\s+(.+)$", r"I am waiting \1 \2", item, flags=re.IGNORECASE)
            item = re.sub(r"^not\s+sure\s+(.+)$", r"I am not sure \1", item, flags=re.IGNORECASE)
            item = re.sub(r"^no\s+idea\s+(.+)$", r"I have no idea \1", item, flags=re.IGNORECASE)
        item = re.sub(r"\bthey\s+is\b", "they are", item, flags=re.IGNORECASE)
        item = re.sub(r"\b(we|you|these|those|people|students|writers|users)\s+was\b", r"\1 were", item, flags=re.IGNORECASE)
        item = re.sub(r"\b(he|she|it|this|that)\s+are\b", r"\1 is", item, flags=re.IGNORECASE)
        item = re.sub(r"\b(the team|the manager|the client|the project|the system|the user)\s+(say|want|need|have)\b", lambda match: f"{match.group(1)} { {'say':'says','want':'wants','need':'needs','have':'has'}[match.group(2).lower()] }", item, flags=re.IGNORECASE)
        item = re.sub(r"\b(can|could|may|might|must|shall|should|will|would)\s+(explains?|helps?|shows?|makes?|improves?|affects?)\b", lambda match: f"{match.group(1)} {re.sub(r's$', '', match.group(2), flags=re.IGNORECASE)}", item, flags=re.IGNORECASE)
        item = re.sub(r"\bi\b", "I", item)
        item = re.sub(r"^honestly[?!]?$", "Honestly,", item, flags=re.IGNORECASE)
        item = re.sub(r"^no\s+contest$", "There is no contest", item, flags=re.IGNORECASE)
        item = re.sub(r"^no\s+grammar$", "The grammar needs work", item, flags=re.IGNORECASE)
        item = re.sub(r"^ideas?\s+missing$", "Ideas are missing", item, flags=re.IGNORECASE)
        item = re.sub(r"^reason(?:s)?\s+unclear$", "The reasons are unclear", item, flags=re.IGNORECASE)
        item = re.sub(r"^deadline\s+missed$", "The deadline was missed", item, flags=re.IGNORECASE)
        item = re.sub(r"^(.+?)\s+performance\s+unacceptable$", r"The \1's performance is unacceptable", item, flags=re.IGNORECASE)
        item = re.sub(r"^meeting\s+(today|tomorrow)\s+with\s+(.+)$", r"The meeting with \2 is \1", item, flags=re.IGNORECASE)
        item = re.sub(r"^(.+?)\s+not\s+(finished|ready|clear|complete)$", r"\1 is not \2", item, flags=re.IGNORECASE)
        def adjective_fragment(match: re.Match[str]) -> str:
            subject = match.group(1)
            # A complete clause such as “Do not be late” already has a verb;
            # only noun-like note fragments should receive a new copula.
            if re.search(r"\b(?:am|is|are|was|were|be|been|being|has|have|had|do|does|did|can|could|may|might|must|shall|should|will|would)\b", subject, flags=re.IGNORECASE):
                return match.group(0)
            return f"{subject.strip()} {'are' if plural_subject(subject) else 'is'} {match.group(2).lower()}"

        item = re.sub(r"^(.+?)\s+(hard|difficult|easy|important|unclear|missing|gone|ready|late|broken|obvious|unacceptable)$", adjective_fragment, item, flags=re.IGNORECASE)
        item = re.sub(r"^need\s+to\s+(.+)$", r"I need to \1", item, flags=re.IGNORECASE)
        def normalize_need(match: re.Match[str]) -> str:
            remainder = match.group(1)
            prefix = "to " if re.match(r"(explain|send|write|review|fix|finish|make|understand|organize|ask|call|check|clarify)\b", remainder, flags=re.IGNORECASE) else ""
            return f"I need {prefix}{remainder}"
        item = re.sub(r"^need\s+(.+)$", normalize_need, item, flags=re.IGNORECASE)
        item = re.sub(r"^send\s+update\b", "Send an update", item, flags=re.IGNORECASE)
        return item[:1].upper() + item[1:]

    fragments_before_normalize = _split_repair_fragments(masked)
    source_has_honest_best = (
        any(re.match(r"^honestly[?!]?$", part, flags=re.IGNORECASE) for part in original_fragments)
        and any(re.match(r"^best\s+.+$", part, flags=re.IGNORECASE) for part in original_fragments)
        and any(re.match(r"^no\s+contest$", part, flags=re.IGNORECASE) for part in original_fragments)
    )
    source_has_missing_file_location = (
        any(re.match(r"^no\s+idea\s+where\s+.+$", part, flags=re.IGNORECASE) for part in original_fragments)
        and any(re.match(r"^probably\s+(?:on\s+)?the\s+shared\s+drive$", part, flags=re.IGNORECASE) for part in original_fragments)
        and any(re.match(r"^maybe$", part, flags=re.IGNORECASE) for part in original_fragments)
    )
    sequence_repaired: list[str] = []
    index = 0
    while index < len(fragments_before_normalize):
        first = fragments_before_normalize[index]
        second = fragments_before_normalize[index + 1] if index + 1 < len(fragments_before_normalize) else None
        third = fragments_before_normalize[index + 2] if index + 2 < len(fragments_before_normalize) else None
        inline_honest_best = re.match(r"^honestly,?\s+(?:the\s+)?best\s+(.+)$", first, flags=re.IGNORECASE)
        if source_has_honest_best and inline_honest_best:
            best_phrase = inline_honest_best.group(1).strip()
            sequence_repaired.append(f"Honestly, this is the best {best_phrase[:1].lower() + best_phrase[1:]}")
            index += 1
            continue
        if (
            source_has_honest_best
            and second
            and third
            and re.match(r"^honestly[?!]?$", first, flags=re.IGNORECASE)
            and re.match(r"^best\s+(.+)$", second, flags=re.IGNORECASE)
            and no_contest_pattern.match(third)
        ):
            best_phrase = re.sub(r"^best\s+", "", second, count=1, flags=re.IGNORECASE).strip()
            sequence_repaired.append(f"Honestly, this is the best {best_phrase[:1].lower() + best_phrase[1:]}. {third}")
            index += 3
            continue
        if (
            source_has_missing_file_location
            and second
            and third
            and no_idea_pattern.match(first)
            and re.match(r"^probably\s+(?:on\s+)?the\s+shared\s+drive$", second, flags=re.IGNORECASE)
            and re.match(r"^maybe$", third, flags=re.IGNORECASE)
        ):
            no_idea_match = no_idea_pattern.match(first)
            no_word = no_idea_match.group(1) if no_idea_match else "No"
            where_clause = no_idea_match.group(2).strip() if no_idea_match else first
            location_clause = re.sub(r"^probably\s+(?:on\s+)?", "", second, count=1, flags=re.IGNORECASE).strip()
            sequence_repaired.append(f"I have {no_word} idea where {where_clause}; it probably went to {location_clause}, maybe")
            index += 3
            continue
        sequence_repaired.append(first)
        index += 1

    planned = plan_note_stream(". ".join(sequence_repaired))
    if planned:
        masked = planned
    else:
        masked = ". ".join(sequence_repaired)
    masked = re.sub(r"\b(?:the\s+)?reasons?\s+unclear\b", "the reasons are unclear", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bteam\s+say\b", "the team says", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bmanager\s+want\b", "the manager wants", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bthe manager wants answer\b", "the manager wants an answer", masked, flags=re.IGNORECASE)
    fragments = _split_repair_fragments(masked)
    repaired = ". ".join(normalize(fragment).rstrip(".!?") for fragment in fragments)
    repaired = re.sub(r"\s+([,.;!?])", r"\1", repaired).strip()
    if repaired and not re.search(r"[.!?][\"'”’)]?$", repaired):
        repaired += "."

    repaired = _restore_protected_spans(repaired, ordered_protected)
    repaired = re.sub(r"\bI have No\b", "I have no", repaired)
    repaired = re.sub(r"\bno\s+grammar\b", "there is no clear grammar", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\.\s+(is|are|was|were)\s+", r" \1 ", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"(\bwho is [^.!?]+?)(?:,)?\s+(is\s+(?:today|tomorrow)\b)", r"\1, \2", repaired, flags=re.IGNORECASE)
    return re.sub(r"\.{2,}", ".", repaired)


def repair_direct_english(value: str, request: dict[str, Any]) -> str:
    """Remove high-confidence filler while preserving protected markers."""
    protected = [str(span).strip() for span in request.get("protected_spans", []) if str(span).strip()]
    masked, ordered_protected = _mask_protected_spans(value, protected)

    masked = re.sub(r"\bit\s+is\s+(?:important|worth)\s+to\s+note\s+that\s+", "", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bit\s+should\s+be\s+noted\s+that\s+", "", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bit\s+is\s+useful\s+to\s+remember\s+that\s+", "", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bthere\s+are\s+(?:a\s+number|an\s+umber)\s+of\s+", "several ", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bbecause\s+of\s+(?:the\s+)?reasons?\b", "for unspecified reasons", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bbecause\s+reasons?\b", "for unspecified reasons", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bnotwithstanding\s+the\s+fact\s+that\b", "although", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bdue\s+to\s+the\s+fact\s+that\b", "because", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bin\s+order\s+to\b", "to", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bin\s+the\s+event\s+that\b", "if", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bat\s+(?:this|the\s+present)\s+point\s+in\s+time\b", "now", masked, flags=re.IGNORECASE)
    gerund_base_forms = {
        "being": "be",
        "doing": "do",
        "going": "go",
        "making": "make",
        "using": "use",
        "writing": "write",
        "taking": "take",
        "giving": "give",
        "having": "have",
        "seeing": "see",
        "coming": "come",
        "becoming": "become",
        "moving": "move",
        "living": "live",
        "driving": "drive",
        "improving": "improve",
        "proving": "prove",
        "lying": "lie",
        "tying": "tie",
        "dying": "die",
    }

    def infinitive_from_gerund(value: str) -> str:
        known = gerund_base_forms.get(value.lower())
        if known:
            return known.capitalize() if value[:1].isupper() else known
        if not value.lower().endswith("ing") or len(value) <= 4:
            return value
        stem = value[:-3]
        if re.search(r"([b-df-hj-np-tv-z])\1$", stem, flags=re.IGNORECASE):
            stem = stem[:-1]
        return stem

    masked = re.sub(
        r"\bfor\s+the\s+purpose\s+of\s+([A-Za-z]+ing)\b",
        lambda match: f"to {infinitive_from_gerund(match.group(1))}",
        masked,
        flags=re.IGNORECASE,
    )

    negation = r"(?:no|not|never|without|\ue000.\ue001)"
    masked = re.sub(
        rf"\bthere\s+is\s+({negation})\s+indication\s+that\s+",
        r"\1 evidence shows that ",
        masked,
        flags=re.IGNORECASE,
    )

    def direct_negation(match: re.Match[str]) -> str:
        clause = match.group(2).strip()
        copula = re.match(r"(.+?)\s+(is|are|was|were)\s+(.+)", clause, flags=re.IGNORECASE)
        if not copula:
            return match.group(0)
        return f"{copula.group(1).strip().capitalize()} {copula.group(2)} {match.group(1)} {copula.group(3).strip()}"

    masked = re.sub(
        rf"\bit\s+is\s+({negation})\s+the\s+case\s+that\s+(.+?)\s+(is|are|was|were)\s+([^.!?]+)",
        lambda match: f"{match.group(2).strip().capitalize()} {match.group(3)} {match.group(1)} {match.group(4).strip()}",
        masked,
        flags=re.IGNORECASE,
    )

    def direct_reason(match: re.Match[str]) -> str:
        marker, clause, punctuation = match.groups()
        lacking = re.match(r"^(.+?)\s+(?:is|was)\s+lacking\s+in\s+(.+)$", clause.strip(), flags=re.IGNORECASE)
        if not lacking:
            return match.group(0)
        subject, complement = lacking.groups()
        possessive = f"{subject.strip()}'s"
        return f"{possessive.capitalize()} lack of {complement.strip()} {'is not' if marker else 'is'} the reason{punctuation}"

    masked = re.sub(
        r"\bthe\s+reason\s+is\s+(not\s+)?because\s+([^.!?]+)([.!?])",
        direct_reason,
        masked,
        flags=re.IGNORECASE,
    )
    def direct_need(match: re.Match[str]) -> str:
        action = re.sub(r"\bmake\s+improvements\b", "improve", match.group(1).strip(), flags=re.IGNORECASE)
        return f"We need to {action}{match.group(2)}"

    masked = re.sub(
        r"\bthere\s+is\s+a\s+need\s+for\s+us\s+to\s+([^.!?]+)([.!?])",
        direct_need,
        masked,
        flags=re.IGNORECASE,
    )
    masked = re.sub(r"\s{2,}", " ", masked)
    masked = re.sub(r"\s+([,.;!?])", r"\1", masked)
    masked = _repair_punctuation_spacing(masked).strip()

    repaired = _restore_protected_spans(masked, ordered_protected)
    repaired = _capitalize_sentence_starts(repaired)
    return repaired


def repair_quantifier_agreement(value: str) -> str:
    """Repair high-confidence agreement around quantifier phrases."""
    plural_quantifier = r"(?:a number of|a lot of|lots of|plenty of|a few|many|several|both|numerous)"
    plural_noun = r"[A-Za-z][A-Za-z'-]*s"
    repaired = value
    repaired = re.sub(rf"\b({plural_quantifier})\s+({plural_noun})\s+is\b", r"\1 \2 are", repaired, flags=re.IGNORECASE)
    repaired = re.sub(rf"\b({plural_quantifier})\s+({plural_noun})\s+was\b", r"\1 \2 were", repaired, flags=re.IGNORECASE)
    repaired = re.sub(rf"\b({plural_quantifier})\s+({plural_noun})\s+has\b", r"\1 \2 have", repaired, flags=re.IGNORECASE)
    repaired = re.sub(rf"\b({plural_quantifier})\s+({plural_noun})\s+does\b", r"\1 \2 do", repaired, flags=re.IGNORECASE)

    def singularize(match: re.Match[str]) -> str:
        verb = match.group(2).lower()
        replacement = {"are": "is", "were": "was", "have": "has", "do": "does"}[verb]
        return f"the number of {match.group(1)} {replacement}"

    repaired = re.sub(
        r"\bthe\s+number\s+of\s+([A-Za-z][A-Za-z'-]*s)\s+(are|were|have|do)\b",
        singularize,
        repaired,
        flags=re.IGNORECASE,
    )

    def singular_head(match: re.Match[str]) -> str:
        verb = match.group(2).lower()
        replacement = {"are": "is", "were": "was", "have": "has", "do": "does"}[verb]
        return f"{match.group(1)} {replacement}"

    repaired = re.sub(
        r"\b((?:one|each|every|either|neither)\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z'-]*s)\s+(are|were|have|do)\b",
        singular_head,
        repaired,
        flags=re.IGNORECASE,
    )

    def pluralize_head(match: re.Match[str]) -> str:
        verb = match.group(2).lower()
        replacement = {"is": "are", "was": "were", "has": "have", "does": "do"}[verb]
        return f"{match.group(1)} {replacement}"

    repaired = re.sub(
        r"\b((?:both)\s+of\s+(?:the\s+)?[A-Za-z][A-Za-z'-]*)\s+(is|was|has|does)\b",
        pluralize_head,
        repaired,
        flags=re.IGNORECASE,
    )
    repaired = re.sub(
        r"\bthere\s+(is|was)\s+(?=(?:two|three|four|five|many|several|multiple|both|these|those)\b)",
        lambda match: "there were " if match.group(1).lower() == "was" else "there are ",
        repaired,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"\bthere's\s+(?=(?:two|three|four|five|many|several|multiple|both|these|those)\b)",
        "there are ",
        repaired,
        flags=re.IGNORECASE,
    )


def repair_sentence_boundaries(value: str) -> str:
    """Repair clear comma splices without disturbing introductory clauses."""
    clause_subject = r"(?:I|we|you|he|she|they|it|this|that|there|people|students|users|(?:the|a|an|my|your|our|their|some|any|no|each|every|one|both|many|several)\s+[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){0,2})"
    finite_verb = r"(?:is|are|was|were|has|have|had|can|could|may|might|must|should|will|would|do|does|did|[A-Za-z]+(?:s|ed)(?!['’]))"
    pattern = re.compile(rf",\s+(?={clause_subject}\s+{finite_verb}\b)", flags=re.IGNORECASE)
    independent_clause = re.compile(rf"^(?:{clause_subject})\s+[^,.;!?]*\b{finite_verb}\b", flags=re.IGNORECASE)

    def replace_splice(match: re.Match[str]) -> str:
        start = match.start()
        sentence_start = max(value.rfind(".", 0, start), value.rfind("!", 0, start), value.rfind("?", 0, start)) + 1
        left_clause = value[sentence_start:start].strip()
        if re.match(r"^(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b", left_clause, flags=re.IGNORECASE):
            return ", "
        if re.search(r"\b(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b[^,.;!?]*$", left_clause, flags=re.IGNORECASE):
            return ", "
        if not independent_clause.search(left_clause):
            return ", "
        return "; "

    repaired = pattern.sub(replace_splice, value)
    return re.sub(
        r"(^|(?<=[.!?]\s))(\s*(?:because|although|when|if|while|since|unless|after|before|even though|even if|given that)\b[^,.;!?]+?)\s+(?=(?:I|we|you|he|she|they|it|this|that|people|students|users)\s+)",
        r"\1\2, ",
        repaired,
        flags=re.IGNORECASE,
    )


GERUND_DOUBLING = {
    "begin": "beginning",
    "get": "getting",
    "plan": "planning",
    "put": "putting",
    "run": "running",
    "sit": "sitting",
    "stop": "stopping",
    "swim": "swimming",
    "win": "winning",
}


def to_gerund(value: str) -> str:
    normalized = value.lower()
    if normalized in GERUND_DOUBLING:
        replacement = GERUND_DOUBLING[normalized]
    elif normalized.endswith("ing"):
        return value
    elif normalized.endswith("ie"):
        replacement = f"{value[:-2]}ying"
    elif normalized.endswith("e") and not normalized.endswith(("ee", "ye", "oe")):
        replacement = f"{value[:-1]}ing"
    else:
        replacement = f"{value}ing"
    return replacement.capitalize() if value[:1].isupper() else replacement


def repair_parallel_verb_series(value: str) -> str:
    """Repair a narrow gerund-complement list with one stray base verb."""
    pattern = re.compile(
        r"\b((?:likes?|enjoys?|keeps?|starts?|stops?|avoids?|finishes?|continues?|prefers?)\s+)([A-Za-z]+ing),\s+([A-Za-z]+ing),\s+and\s+([A-Za-z]+)\b",
        flags=re.IGNORECASE,
    )
    return pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}, {match.group(3)}, and {to_gerund(match.group(4))}", value)


def repair_english_grammar(value: str, request: dict[str, Any]) -> str:
    """Apply high-confidence agreement, modal, article, and case repairs."""
    protected = [str(span).strip() for span in request.get("protected_spans", []) if str(span).strip()]
    masked, ordered_protected = _mask_protected_spans(value, protected)

    plural = r"(?:we|they|these|those|people|children|men|women|students|writers|users|sentences|ideas|tools|results|problems|tasks|assignments)"
    singular = r"(?:he|she|it|this|that|someone|everyone|each|every|either|neither|nothing|something)"
    masked = re.sub(rf"\b({plural})\s+is\b", r"\1 are", masked, flags=re.IGNORECASE)
    masked = re.sub(rf"\b({plural})\s+was\b", r"\1 were", masked, flags=re.IGNORECASE)
    masked = re.sub(rf"\b({plural})\s+has\b", r"\1 have", masked, flags=re.IGNORECASE)
    masked = re.sub(rf"\b({plural})\s+does\b", r"\1 do", masked, flags=re.IGNORECASE)
    masked = re.sub(rf"\b({singular})\s+are\b", r"\1 is", masked, flags=re.IGNORECASE)
    masked = re.sub(rf"\b({singular})\s+were\b", r"\1 was", masked, flags=re.IGNORECASE)
    masked = re.sub(rf"\b({singular})\s+have\b", r"\1 has", masked, flags=re.IGNORECASE)
    masked = re.sub(rf"\b({singular})\s+do\b", r"\1 does", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bI\s+is\b", "I am", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\byou\s+is\b", "you are", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\byou\s+was\b", "you were", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\b(I|you)\s+has\b", r"\1 have", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\b(I|you)\s+does\b", r"\1 do", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\b(we|they|these|those|people|students|writers|users)\s+doesn't\b", r"\1 don't", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\b(he|she|it|this|that|someone|everyone|each|every)\s+don't\b", r"\1 doesn't", masked, flags=re.IGNORECASE)
    singular_s_words = {
        "analysis", "basis", "business", "crisis", "economics", "gas", "news", "physics",
        "politics", "process", "status", "series", "species", "thesis",
    }

    def plural_noun_agreement(match: re.Match[str]) -> str:
        noun = match.group(1)
        verb = match.group(2).lower()
        normalized = noun.lower()
        if normalized in singular_s_words or re.search(r"(?:ss|us|is)$", normalized):
            return match.group(0)
        replacement = {"is": "are", "was": "were", "has": "have", "does": "do"}[verb]
        return f"{noun} {replacement}"

    masked = re.sub(
        r"\b([A-Za-z][A-Za-z'-]*s)\s+(is|was|has|does)\b",
        plural_noun_agreement,
        masked,
        flags=re.IGNORECASE,
    )
    masked = re.sub(
        rf"\bthere\s+(is|was)\s+(?=(?:the|these|those|many|several)\s+[A-Za-z][A-Za-z'-]*s\b)",
        lambda match: "there were " if match.group(1).lower() == "was" else "there are ",
        masked,
        flags=re.IGNORECASE,
    )
    masked = re.sub(
        rf"\bthere\s+(are|were)\s+(?=(?:a|an|each|every|one)\s+[A-Za-z][A-Za-z'-]*\b)",
        lambda match: "there was " if match.group(1).lower() == "were" else "there is ",
        masked,
        flags=re.IGNORECASE,
    )
    masked = repair_quantifier_agreement(masked)

    modal = r"(?:can|could|may|might|must|shall|should|will|would)"
    for bad, base in (
        (r"explains?", "explain"),
        (r"helps?", "help"),
        (r"shows?", "show"),
        (r"makes?", "make"),
        (r"improves?", "improve"),
        (r"affects?", "affect"),
        (r"uses?", "use"),
        (r"gives?", "give"),
        (r"needs?", "need"),
        (r"has", "have"),
        (r"does", "do"),
    ):
        masked = re.sub(
            rf"\b({modal})\s+{bad}\b",
            lambda match, replacement=base: f"{match.group(1)} {replacement}",
            masked,
            flags=re.IGNORECASE,
        )

    masked = re.sub(r"\bbetween\s+((?:you|he|she|they|we))\s+and\s+I\b", r"between \1 and me", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bbetween\s+you\s+and\s+he\b", "between you and him", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bbetween\s+you\s+and\s+she\b", "between you and her", masked, flags=re.IGNORECASE)

    masked = re.sub(r"\b(could|should|would|might|must)\s+of\b", r"\1 have", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\balot\b", "a lot", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bmore\s+(better|worse|easier|harder|simpler)\b", r"\1", masked, flags=re.IGNORECASE)
    masked = re.sub(r"\bmost\s+(best|worst|easiest|hardest|simplest)\b", r"\1", masked, flags=re.IGNORECASE)
    masked = repair_sentence_boundaries(masked)
    masked = repair_parallel_verb_series(masked)

    def article(match: re.Match[str]) -> str:
        article_word = match.group(1)
        word = match.group(2)
        lowered = word.lower()
        vowel = bool(re.match(r"[aeiou]", lowered))
        if re.match(r"^(?:honest|honor|honour|hour|heir|herb)\b", lowered):
            vowel = True
        if re.match(r"^(?:ewe|euro|one|once|uniform|unique|unit|united|university|use|useful|user|usual)\b", lowered):
            vowel = False
        expected = "an" if vowel else "a"
        if article_word.isupper():
            expected = expected.upper()
        elif article_word[:1].isupper():
            expected = expected.capitalize()
        return f"{expected} {word}"

    masked = re.sub(r"\b(a|an)\s+([A-Za-z][A-Za-z'-]*)\b", article, masked, flags=re.IGNORECASE)
    masked = re.sub(r"\s+([,.;!?])", r"\1", masked)
    masked = _repair_punctuation_spacing(masked)
    masked = _capitalize_sentence_starts(masked)
    masked = re.sub(r"\s{2,}", " ", masked).strip()

    return _restore_protected_spans(masked, ordered_protected)


def repair_safe_lexical_choices(value: str) -> str:
    """Use a few high-confidence everyday alternatives when decoding is inert."""
    repaired = re.sub(r"\bapproved\s+the\s+plan\b", "accepted the plan", value, flags=re.IGNORECASE)
    return re.sub(r"\breviewed\s+the\s+draft\b", "examined the draft", repaired, flags=re.IGNORECASE)


def warmth_polish(value: str, request: dict[str, Any]) -> str:
    if str(request.get("mode", "personal")).strip().lower() != "warmth":
        return value

    protected = [str(span).strip() for span in request.get("protected_spans", []) if str(span).strip()]
    masked, ordered_protected = _mask_protected_spans(value, protected)

    protected_placeholder = r"\ue000[\s\S]\ue001"
    warm_conditional_refusal = re.compile(
        rf"(^|\s)((?:no|{protected_placeholder}))\s+further\s+(?:assistance|help|guide)\s+((?:will|{protected_placeholder}))\s+be\s+(?:provided|given|available)\s+until\s+([^.!?]+)",
        flags=re.IGNORECASE,
    )
    warm_absolute_refusal = re.compile(
        rf"(^|\s)((?:no|{protected_placeholder}))\s+further\s+(?:assistance|help|guide)\s+((?:will|{protected_placeholder}))\s+be\s+(?:provided|given|available)\b(?!\s+until)",
        flags=re.IGNORECASE,
    )
    warm_no_excuses = re.compile(
        rf"(^|\s)((?:no|{protected_placeholder}))\s+excuses\b",
        flags=re.IGNORECASE,
    )

    def warm_conditional(match: re.Match[str]) -> str:
        prefix, no_word, will_word, condition = match.groups()
        return f"{prefix}{no_word} further help {will_word} be available until {condition.strip()}, and clarification about the next step is welcome"

    def warm_absolute(match: re.Match[str]) -> str:
        prefix, no_word, will_word = match.groups()
        return f"{prefix}{no_word} further help {will_word} be available; clarification about the next step is welcome"

    def warm_excuses(match: re.Match[str]) -> str:
        prefix, no_word = match.groups()
        return f"{prefix}{no_word} valid excuses are needed; let's focus on the next step"

    def inflected_use(match: re.Match[str]) -> str:
        word = match.group(0).lower()
        if word.endswith("ing"):
            return "using"
        if word.endswith("ed"):
            return "used"
        if word.endswith("es"):
            return "uses"
        return "use"

    polished = warm_conditional_refusal.sub(warm_conditional, masked)
    polished = warm_absolute_refusal.sub(warm_absolute, polished)
    polished = warm_no_excuses.sub(warm_excuses, polished)
    polished = (polished
        .replace("individuals", "people")
        .replace("Individuals", "People")
        .replace("persons", "people")
        .replace("Persons", "People")
    )
    polished = re.sub(r"\butili[sz](?:e|ed|es|ing)\b", inflected_use, polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bassist(?:s|ed|ing)?\b", lambda match: {
        "assists": "helps",
        "assisted": "helped",
        "assisting": "helping",
    }.get(match.group(0).lower(), "help"), polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bassistance\b", "help", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bfails to provide\b", "doesn't offer", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bfailed to provide\b", "didn't offer", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bis unable to\b", "can't", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bcannot\b", "can't", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bfailed to comply\b", "didn't follow the instructions", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\brequest is invalid\b", "request doesn't meet the requirements", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bthis is your responsibility\b", "you'll need to handle the next step", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bfix immediately\b", "please address this as soon as possible", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bthe problem is obvious\b", "the problem is clear", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bI am disappointed\b", "I'm concerned", polished)
    polished = re.sub(r"\b(team(?:'s)? performance)\s+unacceptable\b", r"\1 is not where it needs to be", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bis unacceptable\b", "is not where it needs to be", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bunacceptable\b", "not where it needs to be", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\bcan't help\b(?!\s+with)", "can't help with this", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\b(the user) (?:didn't|did not) meet the requirements\b", r"\1 didn't meet the requirements. The missing pieces can be worked through", polished, flags=re.IGNORECASE)
    polished = re.sub(r"\b(the deadline) was missed\b", r"\1 was missed. Let's focus on the next step", polished, flags=re.IGNORECASE)

    polished = _restore_protected_spans(polished, ordered_protected)
    polished = re.sub(
        r"\b(no valid excuses are needed;\s+let's focus on what we can do next)(?:\s+will be accepted)?\b",
        r"\1",
        polished,
        flags=re.IGNORECASE,
    )
    return polished


def restore_protected_variants(value: str, request: dict[str, Any]) -> str:
    """Put exact anchors back when a generative model reformats a date or number.

    The browser still runs the final protected-content validator. This small
    repair lets the native draft pass without trusting the model to preserve a
    date's presentation, while leaving ordinary prose untouched.
    """
    protected = [str(span).strip() for span in request.get("protected_spans", []) if str(span).strip()]
    patterns = [
        (re.compile(r"https?://[^\s<>)\]]+", re.IGNORECASE), lambda span: span.startswith(("http://", "https://"))),
        (re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE), lambda span: "@" in span),
        (re.compile(r"(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?)", re.IGNORECASE), lambda span: bool(re.search(r"[-/]\d{1,2}[-/]\d{1,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", span, re.IGNORECASE))),
        (re.compile(r"(?:[$€£¥]\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:USD|EUR|GBP|JPY)\b)", re.IGNORECASE), lambda span: bool(re.search(r"[$€£¥]|\b(?:USD|EUR|GBP|JPY)\b", span, re.IGNORECASE))),
    ]

    repaired = value
    for span in protected:
        if span in repaired:
            continue
        for pattern, matches_span in patterns:
            if not matches_span(span):
                continue
            match = pattern.search(repaired)
            if match:
                repaired = repaired[:match.start()] + span + repaired[match.end():]
                break
    return repaired


def restore_missing_modal_markers(value: str, request: dict[str, Any]) -> str:
    """Repair a narrow, meaning-preserving modal rewrite before browser validation.

    Qwen sometimes turns a source clause such as “I can have difficulty” into
    “I find it difficult.” When the source modal is protected, restore only a
    clearly equivalent local form; do not invent a modal for an unrelated
    clause. The browser still performs the final exact-span and meaning gates.
    """
    original = str(request.get("original_text", "")).strip()
    protected = [str(span).strip() for span in request.get("protected_spans", []) if str(span).strip()]
    repaired = value

    modal_pattern = re.compile(r"\b(?:may|might|could|can|must|should|will|would|shall)\b", re.IGNORECASE)
    original_modals = [match.group(0) for match in modal_pattern.finditer(original)]
    for modal in original_modals:
        if modal not in protected:
            continue
        expected = sum(1 for span in protected if span.lower() == modal.lower())
        actual = len(re.findall(rf"\b{re.escape(modal)}(?!['’])\b", repaired, flags=re.IGNORECASE))
        missing = expected - actual
        if missing <= 0:
            continue

        if modal.lower() == "can":
            # “is/are able to” carries the same capability force and can be
            # safely shortened when the exact protected marker is required.
            for pattern in (r"\bis\s+able\s+to\b", r"\bare\s+able\s+to\b"):
                if missing <= 0:
                    break
                updated, replacements = re.subn(pattern, "can", repaired, count=missing, flags=re.IGNORECASE)
                repaired = updated
                missing -= replacements

            if missing > 0:
                # Prefer the unambiguous “find it difficult” paraphrase over
                # a generic insertion after any first-person subject.
                patterns = (
                    r"\b(I)\s+((?:(?:also|often|sometimes|still)\s+)?find\s+it\s+difficult\b)",
                    r"\b(I)\s+((?:(?:also|often|sometimes|still)\s+)?(?:have|experience|face)\s+(?:difficulty|trouble)\b)",
                )
                for pattern in patterns:
                    if missing <= 0:
                        break
                    repaired, replacements = re.subn(pattern, rf"\1 {modal.lower()} \2", repaired, count=missing, flags=re.IGNORECASE)
                    missing -= replacements

                if missing > 0:
                    # Qwen may replace “I can ...” with “I ...” or
                    # “These symptoms can ...” with “These symptoms ...”.
                    # Recover the source subject from each protected modal
                    # clause and restore the exact marker without replacing
                    # the model's otherwise useful wording.
                    subject_pattern = re.compile(
                        r"\b((?:I|we|you|they|he|she|it|this|that|these|those)(?:\s+[A-Za-z]+){0,3}|(?:the|a|an)\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,2})\s+can\b",
                        flags=re.IGNORECASE,
                    )
                    source_subjects = []
                    for sentence in re.split(r"(?<=[.!?])\s+", original):
                        for subject_match in subject_pattern.finditer(sentence):
                            subject = re.sub(r"\s+", " ", subject_match.group(1)).strip()
                            if subject.lower() not in {item.lower() for item in source_subjects}:
                                source_subjects.append(subject)
                    for subject in source_subjects:
                        if missing <= 0:
                            break
                        if re.search(rf"\b{re.escape(subject)}\s+can(?!['’])\b", repaired, flags=re.IGNORECASE):
                            continue
                        repaired, replacements = re.subn(
                            rf"\b({re.escape(subject)})\s+(?!can(?!['’])\b)",
                            rf"\1 {modal.lower()} ",
                            repaired,
                            count=1,
                            flags=re.IGNORECASE,
                        )
                        missing -= replacements

    return repaired


def repair_discourse_relations(value: str, request: dict[str, Any]) -> str:
    """Keep an explicit source relationship when the model uses a vague frame."""
    original = str(request.get("original_text", ""))
    repaired = value

    # “When there are distractions” and “in the presence of distractions” can
    # be close in ordinary prose, but the latter drops the source's explicit
    # time/condition relationship. Restore it only when the source supplies
    # the matching clause and the candidate supplies the recognizable frame.
    if re.search(r"\bwhen\s+there\s+are\b", original, flags=re.IGNORECASE):
        repaired = re.sub(r"\bin\s+the\s+presence\s+of\b", "when there are", repaired, count=1, flags=re.IGNORECASE)

        # A native draft can retain the content word while dropping the
        # relationship altogether: “stay focused when there are distractions”
        # can become “stay focused over long periods, handle distractions”.
        # Restore only this high-confidence comma-delimited frame; the browser
        # still performs the final meaning contract before accepting the draft.
        source_match = re.search(
            r"\b(when|while|once)\s+there\s+are\s+([^,.;!?]+)",
            original,
            flags=re.IGNORECASE,
        )
        if source_match and not re.search(
            r"\b(?:when|while|once|if|unless|because|although|since)\b",
            repaired,
            flags=re.IGNORECASE,
        ):
            content = source_match.group(2).strip()
            anchor = content.split()[-1] if content else ""
            if len(anchor) >= 5:
                repaired = re.sub(
                    rf",\s*(?:handle|manage|deal with|work through)\s+[^,.;!?]*\b{re.escape(anchor)}\b\s*(?=,)",
                    f", especially {source_match.group(1).lower()} there are {content}",
                    repaired,
                    count=1,
                    flags=re.IGNORECASE,
                )

    return repaired


def repair_point_of_view(value: str, request: dict[str, Any]) -> str:
    """Keep an explicit writer participant in a matching infinitive frame."""
    original = str(request.get("original_text", ""))
    repaired = value
    if re.search(r"\bfor\s+me\s+to\b", original, flags=re.IGNORECASE):
        repaired = re.sub(
            r"\bmakes\s+it\s+(difficult|challenging|hard|easy)\s+to\b",
            r"makes it \1 for me to",
            repaired,
            count=1,
            flags=re.IGNORECASE,
        )
    return repaired


def postprocess(text: str, request: dict[str, Any]) -> str:
    """Shared repair pipeline applied to every candidate."""
    if looks_like_control_echo(text):
        raise ValueError("The native model returned editing instructions instead of the rewrite; Pari will use its safe local repair.")
    text = repair_fragmentary_prose(text, request)
    text = repair_direct_english(text, request)
    text = repair_english_grammar(text, request)
    text = repair_safe_lexical_choices(text)
    text = repair_discourse_relations(text, request)
    text = repair_point_of_view(text, request)
    text = restore_missing_modal_markers(text, request)
    text = warmth_polish(restore_protected_variants(text, request), request)
    if "\ue000" in text or "\ue001" in text:
        raise ValueError("Native postprocessing leaked an internal protected-span marker.")
    return text


def generate(request: dict[str, Any]) -> None:
    from mlx_lm import load
    from mlx_lm.generate import generate_step
    from mlx_lm.sample_utils import make_sampler
    import mlx.core as mx

    model_path = str(request.get("model_path", "")).strip()
    if not model_path:
        raise ValueError("The native generator model path was empty.")

    strength = int(request.get("strength", 56))
    requested_temperature = request.get("temperature")
    temperature = (
        max(0.0, min(float(requested_temperature), 1.0))
        if isinstance(requested_temperature, (int, float))
        else 0.16 if strength < 25 else 0.25 if strength < 50 else 0.38 if strength < 75 else 0.52
    )
    top_p = 0.86 if strength < 50 else 0.92 if strength < 75 else 0.95
    max_tokens = max(96, min(int(request.get("max_tokens", 768)), 1536))
    # Opt-in speculative decoding. The stock MLX-LM API calls this a
    # draft_model; the target still verifies every accepted token. Keep it
    # disabled unless an explicit compatible draft checkpoint is supplied so
    # the shipped path remains identical on machines without that asset.
    draft_model_path = str(request.get("draft_model_path", "")).strip()
    num_draft_tokens = max(1, min(int(request.get("num_draft_tokens", 3)), 10))
    # Best-of-N: extra candidates reuse the loaded model, so each additional
    # generation costs inference only (~1s on M4). The TypeScript layer ranks
    # them with its meaning/grammar gates and falls back to candidate 0.
    candidate_count = max(1, min(int(request.get("candidates", 1)), 4))
    started = time.perf_counter()
    model = draft_model = tokenizer = tokens = sampler = None

    try:
        model, tokenizer = load(model_path)
        prompt = render_prompt(tokenizer, build_instruction(request))
        tokens = mx.array(tokenizer.encode(prompt))
        eos_token_id = getattr(tokenizer, "eos_token_id", None)

        if draft_model_path:
            from mlx_lm.generate import stream_generate

            draft_model, draft_tokenizer = load(draft_model_path)
            target_vocab = getattr(tokenizer, "vocab_size", None)
            draft_vocab = getattr(draft_tokenizer, "vocab_size", None)
            if target_vocab is not None and draft_vocab is not None and target_vocab != draft_vocab:
                raise ValueError(
                    "The opt-in speculative draft must use the same tokenizer vocabulary as the target model."
                )

        candidates: list[dict[str, Any]] = []
        for index in range(candidate_count):
            cand_temp = temperature if index == 0 else min(1.0, round(temperature + 0.22 * index, 2))
            sampler = make_sampler(temp=cand_temp, top_p=top_p)
            pieces: list[str] = []
            if draft_model is not None:
                for response in stream_generate(
                    model=model,
                    tokenizer=tokenizer,
                    prompt=tokens,
                    max_tokens=max_tokens,
                    draft_model=draft_model,
                    num_draft_tokens=num_draft_tokens,
                    sampler=sampler,
                ):
                    piece = str(getattr(response, "text", "") or "")
                    if piece:
                        pieces.append(piece)
                    if getattr(response, "finish_reason", None) is not None:
                        break
            else:
                for token_id, _logprobs in generate_step(
                    tokens,
                    model,
                    sampler=sampler,
                    max_tokens=max_tokens,
                ):
                    if eos_token_id is not None and int(token_id) == eos_token_id:
                        break
                    piece = tokenizer.decode([int(token_id)], skip_special_tokens=True)
                    if piece:
                        pieces.append(piece)

            raw_text = clean_output("".join(pieces))
            try:
                text = postprocess(raw_text, request)
            except ValueError as error:
                if index == 0 and candidate_count == 1:
                    raise
                candidates.append({"text": "", "temperature": cand_temp, "error": str(error)})
                continue
            if not text:
                candidates.append({"text": "", "temperature": cand_temp})
                continue
            candidates.append({"text": text, "temperature": cand_temp})

        primary = next((c for c in candidates if c.get("text")), None)
        if primary is None:
            raise ValueError("The native generator returned no usable paragraph.")
        emit({
            "ok": True,
            "text": primary["text"],
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "temperature": primary["temperature"],
            "candidates": candidates,
        })
    finally:
        try:
            if hasattr(mx, "synchronize"):
                mx.synchronize()
        finally:
            model = draft_model = tokenizer = tokens = sampler = None
            try:
                mx.clear_cache()
            except Exception:
                pass


def main() -> int:
    try:
        request = json.load(sys.stdin)
        generate(request)
        return 0
    except Exception as error:  # noqa: BLE001 - native errors are user-facing recovery state
        emit({"ok": False, "error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
