"""Shared conservative parser for English Core forced-choice outputs.

The benchmark requests an option letter only. Accept an explicit choice marker
at the start, with an explanation if present. Never scan arbitrary prose or
infer a choice from its content.

Every forced-choice task freezes its options in a machine-readable
``allowedChoices`` list (for example ``["A", "B"]``). Both the strict
(bare-label) and the recoverable (anchored-wrapper) views enforce that frozen
set, so an impossible label such as ``Z`` on an A/B task is reported as an
invalid option label instead of a protocol-valid but wrong answer. The allowed
set is task metadata only: this module never reads, derives, or consults a gold
answer to resolve a label.

Frozen Unicode and anchoring policy (deliberately conservative):

- Only ASCII ``a-z`` folds to ``A-Z``. Nothing else is case-folded, so Unicode
  lookalikes (full-width ``Ａ``, Cyrillic ``А``, Kelvin ``K``, long s ``ſ``,
  dotless ``ı``) stay unrecognized and can never become valid choices.
- A label is only accepted in an anchored position: the whole output, or an
  already-declared answer wrapper / choice verb. Prose is never scanned.
- Markdown fences, leading bullets, and leading list markers are not anchored
  forms and are rejected.
- A repeated label is only accepted when every anchored label agrees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LABEL_SET = frozenset(ALPHABET)

STATUS_EMPTY = "empty_output"
STATUS_WHITESPACE = "whitespace_only"
STATUS_STRICT_ALLOWED = "strict_allowed_choice"
STATUS_STRICT_INVALID_LABEL = "strict_invalid_option_label"
STATUS_RECOVERABLE_ALLOWED = "recoverable_allowed_choice"
STATUS_RECOVERABLE_INVALID_LABEL = "recoverable_invalid_option_label"
STATUS_AMBIGUOUS = "ambiguous_multiple_choices"
STATUS_NO_ANCHORED_ANSWER = "no_anchored_answer"

CHOICE_STATUSES = (
    STATUS_EMPTY,
    STATUS_WHITESPACE,
    STATUS_STRICT_ALLOWED,
    STATUS_STRICT_INVALID_LABEL,
    STATUS_RECOVERABLE_ALLOWED,
    STATUS_RECOVERABLE_INVALID_LABEL,
    STATUS_AMBIGUOUS,
    STATUS_NO_ANCHORED_ANSWER,
)
ALLOWED_CHOICE_STATUSES = (STATUS_STRICT_ALLOWED, STATUS_RECOVERABLE_ALLOWED)
INVALID_LABEL_STATUSES = (STATUS_STRICT_INVALID_LABEL, STATUS_RECOVERABLE_INVALID_LABEL)

_CHOICE_VERBS = (
    r"(?:I\s+(?:CHOOSE|SELECT|PICK)|I['’]D\s+(?:CHOOSE|PICK)|"
    r"I\s+WOULD\s+(?:CHOOSE|SELECT|PICK)|MY\s+(?:ANSWER|CHOICE|PICK)\s+IS)"
)

# Bare-label forms: the whole output is the label plus at most one delimiter.
_BARE_LABELS = (
    re.compile(r"^([A-Z])$"),
    re.compile(r"^([A-Z])[.)\]:-]$"),
)
# Already-declared anchored answer wrappers, no explanation.
_WRAPPED_LABELS = (
    re.compile(r"^(?:THE\s+)?ANSWER\s+IS\s+([A-Z])[.)\]:-]?$"),
    re.compile(r"^(?:THE\s+)?ANSWER\s*[:=-]\s*([A-Z])[.)\]:-]?$"),
    re.compile(r"^(?:THE\s+)?ANSWER\s+([A-Z])[.)\]:-]?$"),
    re.compile(r"^OPTION\s+([A-Z])[.)\]:-]?$"),
    re.compile(rf"^{_CHOICE_VERBS}\s+([A-Z])[.)\]:-]?$"),
)
_EXPLAINED_LABEL = re.compile(r"^([A-Z])[.)\]:-]\s+(.+)$", re.DOTALL)
_EXPLAINED_PREFIXES = (
    re.compile(r"^(?:THE\s+)?ANSWER\s+IS\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(r"^(?:THE\s+)?ANSWER\s*[:=-]\s*([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(r"^(?:THE\s+)?ANSWER\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(r"^OPTION\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
    re.compile(rf"^{_CHOICE_VERBS}\s+([A-Z])[.)\]:-]?\s+(.+)$", re.DOTALL),
)
_EXPLAINED_BARE_CHOICE = re.compile(
    r"^([A-Z])\s+(?:(?:BECAUSE|SINCE)\b|IS\s+(?:THE\s+)?(?:ANSWER|CORRECT|BEST|RIGHT)\b)([\s\S]*)$",
    re.DOTALL,
)
_AMBIGUOUS_EXPLANATION = re.compile(
    r"^(?:OR\b|AND\b|BOTH\b|EITHER\b|[/&]|[A-Z](?:[.)](?:\s|$)|$)|[A-Z]\s+(?:OR|AND)\b)"
)

# A single ASCII letter standing alone, not the first two characters of a word.
_LONE_LABEL = r"([A-Z])(?![A-Za-z])"
# Repeated answer markers, e.g. "Answer: A. Answer: A" or "... Answer: B".
_REPEATED_WRAPPERS = (
    re.compile(rf"\bANSWER\s+IS\s+{_LONE_LABEL}"),
    re.compile(rf"\bANSWER\s*[:=-]\s*{_LONE_LABEL}"),
    re.compile(rf"\bANSWER\s+{_LONE_LABEL}"),
    re.compile(rf"\bOPTION\s+{_LONE_LABEL}"),
    re.compile(rf"\bI\s+(?:CHOOSE|SELECT|PICK)\s+{_LONE_LABEL}"),
    re.compile(rf"\bI['’]D\s+(?:CHOOSE|PICK)\s+{_LONE_LABEL}"),
    re.compile(rf"\bI\s+WOULD\s+(?:CHOOSE|SELECT|PICK)\s+{_LONE_LABEL}"),
    re.compile(rf"\bMY\s+(?:ANSWER|CHOICE|PICK)\s+IS\s+{_LONE_LABEL}"),
)
# Self-correction to another anchored label, e.g. "A ... actually B".
_SELF_CORRECTION = re.compile(
    r"\b(?:ACTUALLY|CORRECTION|NO\s+WAIT|WAIT|SORRY|I\s+MEAN|REVISED|REVISION)\b"
    rf"[^\n]*?\b(?P<label>{_LONE_LABEL})"
)


def ascii_upper(text: str) -> str:
    """Fold ASCII ``a-z`` to ``A-Z`` only, leaving all other codepoints alone."""
    return "".join(chr(ord(c) - 32) if "a" <= c <= "z" else c for c in text)


def normalize_allowed_choices(allowed_choices: Any) -> tuple[str, ...] | None:
    """Validate and canonicalize a frozen allowed-choice set.

    ``None`` means the task carries no frozen set and the historical permissive
    behavior applies. Anything that is not a non-empty collection of single
    ASCII ``A-Z`` labels is a task-contract bug and raises, rather than
    silently widening or narrowing the set.
    """
    if allowed_choices is None:
        return None
    if isinstance(allowed_choices, str):
        allowed_choices = list(allowed_choices)
    if not isinstance(allowed_choices, (list, tuple)):
        raise ValueError(
            f"allowedChoices must be an array of single letters, got {type(allowed_choices).__name__}"
        )
    labels: list[str] = []
    for value in allowed_choices:
        if not isinstance(value, str):
            raise ValueError(f"allowedChoices entries must be strings, got {type(value).__name__}")
        label = value.strip()
        if len(label) != 1 or label not in _LABEL_SET:
            raise ValueError(f"allowedChoices entries must be single ASCII A-Z labels, got {value!r}")
        if label not in labels:
            labels.append(label)
    if not labels:
        raise ValueError("allowedChoices must not be empty")
    return tuple(sorted(labels, key=ALPHABET.index))


def allowed_choices_from_task(task: Any) -> tuple[str, ...] | None:
    """Read the frozen allowed-choice set from a model-visible task row.

    Accepts the model-visible ``allowedChoices`` key or its snake_case alias.
    Returns ``None`` when no set is frozen so callers can fall back to the
    historical permissive behavior and report that explicitly.
    """
    if not isinstance(task, dict):
        return None
    for key in ("allowedChoices", "allowed_choices"):
        if task.get(key) is not None:
            return normalize_allowed_choices(task[key])
    return None


@dataclass(frozen=True)
class ChoiceParse:
    """Result of one forced-choice parse against a task's frozen allowed set.

    ``letter`` is set only when every anchored label is inside the allowed set.
    ``anchored_label`` keeps the leading label as written and
    ``invalid_option_label`` keeps an out-of-domain label, so diagnostics can
    report ``invalid_option_label`` without re-parsing the output.
    """

    status: str
    letter: str | None
    anchored_label: str | None
    invalid_option_label: str | None
    bare_label_form: bool
    ambiguous: bool
    allowed_choices: tuple[str, ...] | None
    raw_output: str

    @property
    def allowed_set_frozen(self) -> bool:
        return self.allowed_choices is not None

    @property
    def is_allowed_choice(self) -> bool:
        return self.status in ALLOWED_CHOICE_STATUSES

    @property
    def is_invalid_option_label(self) -> bool:
        return self.status in INVALID_LABEL_STATUSES

    @property
    def strict_form(self) -> bool:
        """True when the output is a bare label and that label is allowed."""
        return self.status == STATUS_STRICT_ALLOWED


def _first_out_of_domain(labels: set[str], allowed: tuple[str, ...] | None) -> str | None:
    if allowed is None:
        return None
    for label in sorted(labels, key=ALPHABET.index):
        if label not in allowed:
            return label
    return None


def _self_correction_labels(text: str) -> list[str]:
    return [match.group("label") for match in _SELF_CORRECTION.finditer(text)]


def _repeated_wrapper_labels(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in _REPEATED_WRAPPERS:
        for match in pattern.finditer(text):
            found.add(match.group(1))
    return found


def _result(
    status: str,
    *,
    allowed: tuple[str, ...] | None,
    raw: str,
    letter: str | None = None,
    anchored_label: str | None = None,
    invalid_option_label: str | None = None,
    bare_label_form: bool = False,
    ambiguous: bool = False,
) -> ChoiceParse:
    return ChoiceParse(
        status=status,
        letter=letter,
        anchored_label=anchored_label,
        invalid_option_label=invalid_option_label,
        bare_label_form=bare_label_form,
        ambiguous=ambiguous,
        allowed_choices=allowed,
        raw_output=raw,
    )


def parse_choice(text: str | None, allowed_choices: Any = None) -> ChoiceParse:
    """Parse one forced-choice output against a task's frozen allowed set.

    ``allowed_choices`` is the task's frozen label set. Passing ``None`` keeps
    the historical permissive behavior (any single ``A-Z`` label resolves) for
    task files that predate the frozen contract; ``allowed_set_frozen`` on the
    result records that the set was not enforced.
    """
    allowed = normalize_allowed_choices(allowed_choices)
    raw = str(text or "")
    stripped = raw.strip()
    if not stripped:
        return _result(
            STATUS_EMPTY if raw == "" else STATUS_WHITESPACE,
            allowed=allowed,
            raw=raw,
        )

    upper = ascii_upper(stripped)

    anchored: str | None = None
    bare_form = False
    remainder: str | None = None

    for pattern in _BARE_LABELS:
        match = pattern.match(upper)
        if match:
            anchored = match.group(1)
            bare_form = True
            break

    if anchored is None:
        for pattern in _WRAPPED_LABELS:
            match = pattern.match(upper)
            if match:
                anchored = match.group(1)
                break

    if anchored is None:
        match = _EXPLAINED_LABEL.match(upper)
        if match:
            anchored = match.group(1)
            remainder = match.group(2)

    if anchored is None:
        for pattern in _EXPLAINED_PREFIXES:
            match = pattern.match(upper)
            if match:
                anchored = match.group(1)
                remainder = match.group(2)
                break

    if anchored is None:
        match = _EXPLAINED_BARE_CHOICE.match(upper)
        if match:
            anchored = match.group(1)
            remainder = match.group(2)

    if anchored is None:
        return _result(STATUS_NO_ANCHORED_ANSWER, allowed=allowed, raw=raw)

    labels: set[str] = {anchored}
    if remainder is not None:
        labels.update(_self_correction_labels(remainder))
    labels.update(_repeated_wrapper_labels(upper))

    # An impossible label is a protocol violation, not an English ambiguity, so
    # it wins over an ambiguity report and never counts as a valid output.
    invalid = _first_out_of_domain(labels, allowed)
    if invalid is not None:
        status = STATUS_STRICT_INVALID_LABEL if bare_form else STATUS_RECOVERABLE_INVALID_LABEL
        return _result(
            status,
            allowed=allowed,
            raw=raw,
            anchored_label=anchored,
            invalid_option_label=invalid,
            bare_label_form=bare_form,
        )

    if len(labels) > 1:
        return _result(
            STATUS_AMBIGUOUS,
            allowed=allowed,
            raw=raw,
            anchored_label=anchored,
            bare_label_form=bare_form,
            ambiguous=True,
        )

    if remainder is not None and _AMBIGUOUS_EXPLANATION.match(remainder.lstrip()):
        return _result(
            STATUS_AMBIGUOUS,
            allowed=allowed,
            raw=raw,
            anchored_label=anchored,
            bare_label_form=bare_form,
            ambiguous=True,
        )

    return _result(
        STATUS_STRICT_ALLOWED if bare_form else STATUS_RECOVERABLE_ALLOWED,
        allowed=allowed,
        raw=raw,
        letter=anchored,
        anchored_label=anchored,
        bare_label_form=bare_form,
    )


def parse_choice_letter(text: str | None, allowed_choices: Any = None) -> str | None:
    """Backward-compatible helper returning only the resolved allowed letter.

    ``None`` is returned for an out-of-domain label, an ambiguous output, or a
    non-answer. Callers that need to tell those cases apart should use
    :func:`parse_choice`.
    """
    return parse_choice(text, allowed_choices).letter


def describe_choice_status(status: str) -> str:
    """Human-readable one-liner for a choice status, for reports and docs."""
    return {
        STATUS_EMPTY: "empty output",
        STATUS_WHITESPACE: "whitespace-only output",
        STATUS_STRICT_ALLOWED: "strict protocol-compliant allowed choice",
        STATUS_STRICT_INVALID_LABEL: "bare label outside the task's allowed choices",
        STATUS_RECOVERABLE_ALLOWED: "anchored allowed choice recovered from a wrapper or explanation",
        STATUS_RECOVERABLE_INVALID_LABEL: "anchored label outside the task's allowed choices",
        STATUS_AMBIGUOUS: "multiple or self-correcting anchored choices",
        STATUS_NO_ANCHORED_ANSWER: "no anchored final label (reasoning-only or free prose)",
    }.get(status, status)
