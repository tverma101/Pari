"""Shared conservative parser for English Core forced-choice outputs.

The benchmark requests an option letter only. Accept an explicit choice marker
at the start, with an explanation if present. Never scan arbitrary prose or
infer a choice from its content.
"""

from __future__ import annotations

import re

_CHOICE_VERBS = (
    r"(?:I\s+(?:CHOOSE|SELECT|PICK)|I['’]D\s+(?:CHOOSE|PICK)|"
    r"I\s+WOULD\s+(?:CHOOSE|SELECT|PICK)|MY\s+(?:ANSWER|CHOICE|PICK)\s+IS)"
)

_PATTERNS = [
    re.compile(r"^([A-Z])$"),
    re.compile(r"^([A-Z])[.)\]:-]$"),
    re.compile(r"^(?:THE\s+)?ANSWER\s+IS\s+([A-Z])[.)\]:-]?$") ,
    re.compile(r"^(?:THE\s+)?ANSWER\s*[:=-]\s*([A-Z])[.)\]:-]?$") ,
    re.compile(r"^(?:THE\s+)?ANSWER\s+([A-Z])[.)\]:-]?$") ,
    re.compile(r"^OPTION\s+([A-Z])[.)\]:-]?$") ,
    re.compile(rf"^{_CHOICE_VERBS}\s+([A-Z])[.)\]:-]?$") ,
]
_EXPLAINED_LABEL = re.compile(r"^([A-Z])[.)\]:-]\s+(.+)$", re.DOTALL)
_EXPLAINED_PREFIXES = [
    re.compile(r"^(?:THE\s+)?ANSWER\s+IS\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(r"^(?:THE\s+)?ANSWER\s*[:=-]\s*([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(r"^(?:THE\s+)?ANSWER\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(r"^OPTION\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(rf"^{_CHOICE_VERBS}\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
]
_EXPLAINED_BARE_CHOICE = re.compile(
    r"^([A-Z])\s+(?:(?:BECAUSE|SINCE)\b|IS\s+(?:THE\s+)?(?:ANSWER|CORRECT|BEST|RIGHT)\b)([\s\S]*)$",
    re.DOTALL,
)
_AMBIGUOUS_EXPLANATION = re.compile(
    r"^(?:OR\b|AND\b|BOTH\b|EITHER\b|[/&]|[A-Z](?:[.)](?:\s|$)|$)|[A-Z]\s+(?:OR|AND)\b)"
)


def parse_choice_letter(text: str | None) -> str | None:
    s = str(text or "").strip().upper()
    if not s:
        return None
    for pattern in _PATTERNS:
        match = pattern.match(s)
        if match:
            return match.group(1)

    match = _EXPLAINED_LABEL.match(s)
    if match and not _AMBIGUOUS_EXPLANATION.match(match.group(2).lstrip()):
        return match.group(1)

    for pattern in _EXPLAINED_PREFIXES:
        match = pattern.match(s)
        if match and not _AMBIGUOUS_EXPLANATION.match(match.group(2).lstrip()):
            return match.group(1)

    match = _EXPLAINED_BARE_CHOICE.match(s)
    if match and not _AMBIGUOUS_EXPLANATION.match(match.group(2).lstrip()):
        return match.group(1)
    return None
