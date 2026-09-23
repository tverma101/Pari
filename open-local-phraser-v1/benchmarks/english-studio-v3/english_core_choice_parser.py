"""Shared conservative parser for English Core forced-choice outputs.

The benchmark requests an option letter only. A few unambiguous wrappers are
accepted so formatting compliance is not confused with English competence.
Free-form prose, multiple choices, or answers requiring inference are rejected.
"""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"^([A-Z])$"),
    re.compile(r"^([A-Z])[.)\]:-]$"),
    re.compile(r"^(?:THE\s+)?ANSWER\s*(?::|=|-|IS)?\s*([A-Z])[.)\]:-]?$") ,
    re.compile(r"^OPTION\s+([A-Z])[.)\]:-]?$") ,
]


def parse_choice_letter(text: str | None) -> str | None:
    s = str(text or "").strip().upper()
    if not s:
        return None
    for pattern in _PATTERNS:
        match = pattern.match(s)
        if match:
            return match.group(1)
    return None
