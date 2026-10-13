"""Fail-closed check that benchmark chat templates disable hidden thinking.

Word Studio measures the visible answer contract. A template that silently turns
on reasoning changes latency, token budgets, and output parsing, so it must be
pinned explicitly rather than inferred from a server default.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class ThinkingModeError(ValueError):
    pass


def load_pinned_chat_templates(path: str | Path) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    templates = data.get("templates") if isinstance(data, Mapping) else None
    if not isinstance(templates, Mapping) or not templates:
        raise ThinkingModeError("pinned chat template fixture must contain a non-empty templates object")
    return {str(name): dict(value) for name, value in templates.items() if isinstance(value, Mapping)}


def thinking_mode_enabled(template: Mapping[str, Any]) -> bool:
    """Interpret common runtime switches conservatively; unknown is enabled."""
    for key in ("enable_thinking", "thinking", "reasoning", "reasoning_enabled"):
        if key in template:
            value = template[key]
            if value is None:
                return True
            if isinstance(value, str):
                return value.strip().lower() not in {"0", "false", "off", "disabled", "none"}
            return bool(value)
    effort = template.get("reasoning_effort")
    if effort is not None:
        return str(effort).strip().lower() not in {"none", "off", "disabled", "0"}
    return True


def assert_thinking_mode_off(name: str, templates: Mapping[str, Mapping[str, Any]]) -> None:
    template = templates.get(name)
    if template is None:
        raise ThinkingModeError(f"no pinned chat template named {name!r}")
    if thinking_mode_enabled(template):
        raise ThinkingModeError(f"thinking mode is not explicitly disabled for {name!r}")
