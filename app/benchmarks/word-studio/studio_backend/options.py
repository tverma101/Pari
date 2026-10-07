#!/usr/bin/env python3
"""Deterministic model-output parser used by the live Studio adapter."""
from __future__ import annotations

import json
import re

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")


def parse_options(raw: str) -> tuple[list[str], str]:
    text = str(raw or "").strip()
    if not text:
        return [], "empty"
    try:
        value = json.loads(text)
        if isinstance(value, dict) and isinstance(value.get("options"), list):
            return [str(x).strip() for x in value["options"] if str(x).strip()], "json_object"
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()], "json_array"
    except json.JSONDecodeError:
        pass

    lines = [line for line in text.splitlines() if line.strip()]
    parsed: list[str] = []
    for line in lines:
        match = _BULLET.match(line)
        if match:
            parsed.append(match.group(1).strip())
    if parsed and len(parsed) == len(lines):
        return parsed, "numbered_or_bulleted"
    return [], "unparseable"
