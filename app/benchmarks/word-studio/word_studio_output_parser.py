#!/usr/bin/env python3
"""Canonical usable-candidate contract for Pari Word Studio candidate lists.

This module is the single authority for "what counts as a usable Word Studio
candidate". Offline diagnostics (:func:`diagnose`), the CLI, and the streamed
first-1/3/10 timing path all consume the same admission rule
(:class:`CandidateLedger`) so they cannot drift apart.

Design rules:

- Raw candidate text is never rewritten. Stripping, unescaping or normalizing a
  completion would falsify the recorded completion. Raw text is preserved and a
  separate *comparison key* is derived for dedupe/security diagnostics only.
- The comparison key is deliberately conservative: NFC canonical equivalence,
  full-width ASCII folding, exotic-whitespace folding and removal of invisible
  format characters. It never applies full NFKC, so compatibility characters that
  can change meaning are left alone.
- Structured JSON entries must be strings. ``null``, booleans, numbers, objects
  and nested lists are rejected and reported; they never become candidates.
- Near-duplicate detection is deterministic and cheap (documented edit/token
  thresholds). There is no model judge and no embedding lookup.

GitHub issue #43.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PARSER_VERSION = 3

BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
COMMENTARY_PREFIX = re.compile(
    r"^(?:here(?:'s| are)|sure[,!:]|options?:|alternatives?:|note:|"
    r"the following|based on your request|i hope this helps|let me know)",
    re.I,
)
# Wrapper prose that can follow an otherwise valid list.
COMMENTARY_TAIL_RE = re.compile(
    r"^\s*(?:here(?:'s| are)|i hope this helps|let me know|note[:\s]|"
    r"options?:|alternatives?:|would you like|feel free to|if you'd like)\b",
    re.I,
)
OPTIONS_ARRAY_PREFIX = re.compile(r'"options"\s*:\s*\[', re.I)
CODE_FENCE_RE = re.compile(r"^\s*```[^\n`]*\n(?P<body>.*?)\n?\s*```\s*$", re.S)
NEWLINE = chr(10)

# Keys a model plausibly uses when it returns structured JSON for a list.
KNOWN_LIST_KEYS = ("options", "alternatives", "candidates", "suggestions", "results")

# --- invisible / exotic character handling ---------------------------------

# Zero-width space/non-joiner/joiner, word joiner, invisible math operators,
# deprecated format characters, Mongolian vowel separator, soft hyphen, BOM.
INVISIBLE_RE = re.compile("[​‌‍⁠⁡⁢⁣⁤⁪⁫⁬⁭⁮⁯᠎­﻿]")
# Bidi marks, embeddings, overrides, isolates.
BIDI_RE = re.compile("[‎‏‪-‮⁦-⁩]")
# C0/C1 control characters (tab/newline are handled by whitespace folding).
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Every Unicode space separator plus ASCII tabs/newlines.
EXOTIC_WHITESPACE_RE = re.compile("[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")

FULLWIDTH_START = 0xFF01
FULLWIDTH_END = 0xFF5E
IDEOGRAPHIC_SPACE = "　"

# --- near-duplicate thresholds (documented, deterministic) ------------------

# Two candidates are "materially the same" when the character similarity of their
# comparison keys is at least this ratio, or the token multisets overlap at least
# this much while staying nearly the same length.
NEAR_DUPLICATE_RATIO = 0.92
NEAR_DUPLICATE_TOKEN_OVERLAP = 0.75
# The token-multiset branch is only trusted when the raw comparison keys are
# also character-similar. Without this guard a one-word swap between two genuinely
# different alternatives ("simplify the language" / "simplify the wording") would
# look like a near-duplicate.
NEAR_DUPLICATE_TOKEN_CHAR_RATIO = 0.85
NEAR_DUPLICATE_LENGTH_SLACK = 0.25
# Below this many comparison-key characters only exact-key rules apply, so short
# candidates ("ok", "no") are never merged into longer real alternatives.
NEAR_DUPLICATE_MIN_CHARS = 6

# --- route semantics -------------------------------------------------------

# Routes whose contract asks for an actual transformation. An exact copy of the
# source cannot advance useful depth on these routes.
ROUTE_ALTERNATIVES = "alternatives"
# ``intentional_compression`` is a separate semantic contract: a gist label may
# legitimately differ from the source in any way, so strict full-equivalence
# "unchanged means unusable" logic must not be applied to it.
ROUTE_INTENTIONAL_COMPRESSION = "intentional_compression"
# Routes that explicitly permit identity / no-op output.
ROUTE_IDENTITY_ALLOWED = "identity_allowed"
ROUTES = (ROUTE_ALTERNATIVES, ROUTE_INTENTIONAL_COMPRESSION, ROUTE_IDENTITY_ALLOWED)
# Routes where an exact copy of the source still counts as a usable candidate.
ROUTES_WHERE_UNCHANGED_IS_USABLE = frozenset(
    {ROUTE_INTENTIONAL_COMPRESSION, ROUTE_IDENTITY_ALLOWED}
)

# Candidate JSON entry kinds reported by ``invalidEntryTypes``.
_JSON_KIND_BY_TYPE = {
    type(None): "null",
    bool: "boolean",
    int: "number",
    float: "number",
    str: "string",
    list: "array",
    dict: "object",
}

# A coordinate-bearing protected value that survives but slides this far from
# its source offset is reported as position drift. Deterministic and cheap: a
# quarter of the source length (min 8 characters).
POSITION_DRIFT_FRACTION = 0.25
POSITION_DRIFT_MIN_CHARS = 8

DIGIT_RE = re.compile(r"\d")
NUMERIC_TOKEN_RE = re.compile(r"[\w$€£¥%.,:/-]*\d[\w$€£¥%.,:/-]*", re.UNICODE)


def route_from_task(task: Mapping[str, Any] | None) -> str:
    """Resolve the route contract for a task row without guessing from prose."""
    if not isinstance(task, Mapping):
        return ROUTE_ALTERNATIVES
    declared = str(task.get("route") or "").strip().lower()
    if declared in ROUTES:
        return declared
    semantic = str(
        task.get("semanticMode") or task.get("semantic_mode") or ""
    ).strip().lower()
    if semantic == ROUTE_INTENTIONAL_COMPRESSION:
        return ROUTE_INTENTIONAL_COMPRESSION
    if "identity" in declared or "no_op" in declared or "noop" in declared:
        return ROUTE_IDENTITY_ALLOWED
    return ROUTE_ALTERNATIVES


# ---------------------------------------------------------------------------
# Comparison keys (diagnostics only; never used to rewrite candidate text)


def fold_fullwidth(text: str) -> str:
    """Fold full-width ASCII variants (U+FF01..U+FF5E) to their ASCII forms.

    This is a targeted subset of NFKC: it covers full-width punctuation and
    letters without touching compatibility characters that can change meaning.
    """
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if FULLWIDTH_START <= code <= FULLWIDTH_END:
            out.append(chr(code - (FULLWIDTH_START - 0x21)))
        elif ch == IDEOGRAPHIC_SPACE:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def normalize(text: str) -> str:
    """Back-compatible whitespace/case normalizer.

    Retained because runners and older fixtures import it. New code should use
    :func:`comparison_key`, which additionally folds invisible characters,
    exotic whitespace and full-width ASCII, so Unicode variants cannot trivially
    inflate unique depth. Both collapse internal whitespace and casefold; neither
    rewrites the raw candidate text that is reported.
    """
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def comparison_key(text: str) -> str:
    """Conservative key used for dedupe, unchanged-source and corruption checks.

    Applies, in order: full-width ASCII folding, invisible/bidi/control handling,
    exotic-whitespace folding, NFC canonical composition, whitespace collapse and
    casefolding. The result is a comparison artifact only; candidate text is
    always reported raw.
    """
    value = fold_fullwidth(str(text or ""))
    value = INVISIBLE_RE.sub("", value)
    value = BIDI_RE.sub("", value)
    value = CONTROL_RE.sub(" ", value)
    value = EXOTIC_WHITESPACE_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    value = unicodedata.normalize("NFC", value)
    return value.strip().casefold()


def near_key(text: str) -> str:
    """Punctuation-insensitive token key used only for near-duplicate pairing."""
    key = comparison_key(text)
    stripped = "".join(ch for ch in key if not unicodedata.category(ch).startswith("P"))
    return re.sub(r"\s+", " ", stripped).strip()


def near_duplicate_keys(left: str, right: str) -> bool:
    """Deterministic, cheap "materially the same candidate" test.

    Two comparison keys are near-duplicates when the shorter one is at least
    ``NEAR_DUPLICATE_MIN_CHARS`` long and either:

    - the character similarity ratio is >= ``NEAR_DUPLICATE_RATIO``, or
    - token-multiset overlap is >= ``NEAR_DUPLICATE_TOKEN_OVERLAP`` while the
      token counts stay within ``NEAR_DUPLICATE_LENGTH_SLACK`` of each other.

    Genuinely different alternatives ("a concise summary" vs "an unrelated
    anecdote") fall well below both thresholds.
    """
    if left == right:
        return True
    if not left or not right:
        return False
    if min(len(left), len(right)) < NEAR_DUPLICATE_MIN_CHARS:
        return False
    char_ratio = SequenceMatcher(None, left, right).ratio()
    if char_ratio >= NEAR_DUPLICATE_RATIO:
        return True
    left_stripped = near_key(left)
    right_stripped = near_key(right)
    if left_stripped == right_stripped:
        # Identical words, different punctuation/spacing only.
        return True
    if char_ratio < NEAR_DUPLICATE_TOKEN_CHAR_RATIO:
        return False
    left_tokens = left_stripped.split()
    right_tokens = right_stripped.split()
    if not left_tokens or not right_tokens:
        return False
    longer, shorter = sorted((len(left_tokens), len(right_tokens)), reverse=True)
    if longer - shorter > max(1, longer * NEAR_DUPLICATE_LENGTH_SLACK):
        return False
    shared = sum(min(left_tokens.count(t), right_tokens.count(t)) for t in set(left_tokens))
    union = len(set(left_tokens) | set(right_tokens))
    return union > 0 and (shared / union) >= NEAR_DUPLICATE_TOKEN_OVERLAP


# ---------------------------------------------------------------------------
# Protected content
#
# The corruption rule is the exact-presence contract already used by
# studio_backend/safety.py::candidate_preserves_protected_content. It is
# reimplemented here (rather than imported) so that standalone benchmark runners
# do not need the FastAPI-backed studio_backend package on sys.path.


@dataclass(frozen=True)
class ProtectedValue:
    text: str
    start: int | None = None
    end: int | None = None


def normalize_protected(values: Iterable[Any] | None) -> tuple[ProtectedValue, ...]:
    """Accept strings, ``{text,start,end}`` mappings or ProtectedValue in order."""
    out: list[ProtectedValue] = []
    seen: set[tuple[int | None, int | None, str]] = set()
    for item in values or ():
        if isinstance(item, ProtectedValue):
            span = item
        elif isinstance(item, str):
            span = ProtectedValue(item)
        elif isinstance(item, Mapping):
            start = item.get("start")
            end = item.get("end")
            span = ProtectedValue(
                str(item.get("text") or ""),
                start if isinstance(start, int) else None,
                end if isinstance(end, int) else None,
            )
        else:
            continue
        if not span.text:
            continue
        key = (span.start, span.end, span.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(span)
    return tuple(out)


def protected_evaluation(
    candidate: str,
    *,
    source: str | None = None,
    protected: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Candidate-level protected-content diagnostics.

    Corruption is exact-presence based:

    - ``missing``: a protected value does not occur in the candidate at all;
    - ``altered``: a digit-bearing protected value is absent but the candidate
      substituted a different number-like token carrying the same digit count
      (a changed number/date/amount rather than a plain omission);
    - ``repeated_mismatch``: the source repeats the protected value, so plain
      substring presence is misleading; the candidate must keep the same
      occurrence count;
    - ``positionDrift``: a coordinate-bearing span survives but moved far enough
      that location-sensitive placement is no longer preserved. Reported, but
      not treated as corruption on its own.
    """
    spans = normalize_protected(protected)
    text = str(candidate or "")
    source_text = str(source or "")
    missing: list[str] = []
    altered: list[str] = []
    repeated_mismatch: list[str] = []
    position_drift: list[str] = []

    for span in spans:
        if span.text in text:
            occurrences = text.count(span.text)
            source_occurrences = source_text.count(span.text) if source_text else 1
            if source_occurrences > 1 and occurrences != source_occurrences:
                repeated_mismatch.append(span.text)
            if (
                span.start is not None
                and source_text
                and source_occurrences == 1
                and occurrences == 1
                and text.find(span.text) != span.start
                and abs(text.find(span.text) - span.start) > max(
                    POSITION_DRIFT_MIN_CHARS, int(len(source_text) * POSITION_DRIFT_FRACTION)
                )
            ):
                position_drift.append(span.text)
            continue
        if DIGIT_RE.search(span.text):
            width = len(DIGIT_RE.findall(span.text))
            substituted = any(
                len(DIGIT_RE.findall(token)) == width for token in NUMERIC_TOKEN_RE.findall(text)
            )
            if substituted:
                altered.append(span.text)
                continue
        missing.append(span.text)

    return {
        "protectedCount": len(spans),
        "missing": missing,
        "altered": altered,
        "repeatedMismatch": repeated_mismatch,
        "positionDrift": position_drift,
        "corrupted": bool(missing or altered or repeated_mismatch),
    }


# ---------------------------------------------------------------------------
# Parsing


@dataclass
class ParsedDocument:
    mode: str
    options: list[str] = field(default_factory=list)
    invalid_entries: list[dict[str, Any]] = field(default_factory=list)
    fenced: bool = False
    leading_prose: bool = False
    trailing_prose: bool = False
    commentary_mixed: bool = False
    wrong_json_keys: list[str] = field(default_factory=list)

    @property
    def invalid_entry_types(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.invalid_entries:
            counts[item["type"]] = counts.get(item["type"], 0) + 1
        return dict(sorted(counts.items()))


def _json_entry_kind(value: Any) -> str:
    if isinstance(value, str):
        return "string"
    return _JSON_KIND_BY_TYPE.get(type(value), type(value).__name__)


def _strip_code_fence(text: str) -> tuple[str, bool]:
    match = CODE_FENCE_RE.match(text)
    if not match:
        return text, False
    return match.group("body"), True


def _string_entries(entries: Sequence[Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Split a JSON list into string candidates and typed invalid entries.

    Non-string entries are never coerced to strings; each is reported with its
    index and JSON type so diagnostics stay honest.
    """
    values: list[str] = []
    invalid: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            values.append(entry.strip())
            continue
        invalid.append({"index": index, "type": _json_entry_kind(entry)})
    return values, invalid


def parse_document(raw: str) -> ParsedDocument:
    """Parse a completion into string candidates plus structural diagnostics."""
    text = str(raw or "").strip()
    if not text:
        return ParsedDocument(mode="empty_output")
    body, fenced = _strip_code_fence(text)
    body = body.strip()
    if not body:
        return ParsedDocument(mode="empty_output", fenced=fenced)
    text = body

    try:
        obj = json.loads(text)
    except Exception:
        pass
    else:
        if isinstance(obj, dict) and isinstance(obj.get("options"), list):
            values, invalid = _string_entries(obj["options"])
            return ParsedDocument(
                mode="json_object", options=values, invalid_entries=invalid, fenced=fenced
            )
        if isinstance(obj, dict) and "options" in obj and not isinstance(obj.get("options"), list):
            return ParsedDocument(
                mode="json_object_scalar_options", wrong_json_keys=["options"], fenced=fenced
            )
        if isinstance(obj, dict):
            keys = [str(k) for k in obj.keys()]
            list_keys = [k for k in keys if k in KNOWN_LIST_KEYS]
            return ParsedDocument(
                mode="json_object_wrong_key",
                wrong_json_keys=sorted(list_keys) or sorted(keys),
                fenced=fenced,
            )
        if isinstance(obj, list):
            values, invalid = _string_entries(obj)
            return ParsedDocument(
                mode="json_array", options=values, invalid_entries=invalid, fenced=fenced
            )
        return ParsedDocument(
            mode="json_object_wrong_key",
            wrong_json_keys=[_json_entry_kind(obj)],
            fenced=fenced,
        )

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ParsedDocument(mode="empty_output", fenced=fenced)

    bullet_values: list[str] = []
    bullet_matches = 0
    for line in lines:
        match = BULLET_RE.match(line)
        if match:
            bullet_matches += 1
            bullet_values.append(match.group(1).strip())

    if lines and bullet_matches == len(lines):
        return ParsedDocument(
            mode="numbered_or_bulleted_list", options=bullet_values, fenced=fenced
        )

    if bullet_matches and bullet_matches < len(lines):
        # Some lines are list items and the rest are wrapper prose. Trailing
        # commentary after an otherwise valid list keeps the candidates.
        tail = lines[bullet_matches:]
        leading = COMMENTARY_PREFIX.match(lines[0].strip()) is not None
        if all(COMMENTARY_TAIL_RE.match(x.strip()) for x in tail):
            return ParsedDocument(
                mode="numbered_or_bulleted_list",
                options=bullet_values,
                fenced=fenced,
                leading_prose=leading,
                trailing_prose=True,
                commentary_mixed=not leading,
            )
        if any(COMMENTARY_PREFIX.match(x.strip()) for x in tail):
            return ParsedDocument(
                mode="numbered_or_bulleted_list",
                options=bullet_values,
                fenced=fenced,
                commentary_mixed=True,
            )

    if bullet_matches:
        # A prose preamble in front of an otherwise valid list stays unparseable.
        # The frozen contract has always refused that shape and guessing which
        # lines are candidates would inflate depth. It is now diagnosed.
        return ParsedDocument(
            mode="unparseable",
            fenced=fenced,
            leading_prose=COMMENTARY_PREFIX.match(lines[0].strip()) is not None,
            commentary_mixed=True,
        )

    if 2 <= len(lines) <= 40 and all(not COMMENTARY_PREFIX.match(line.strip()) for line in lines):
        return ParsedDocument(
            mode="newline_list", options=[line.strip() for line in lines], fenced=fenced
        )

    return ParsedDocument(mode="unparseable", fenced=fenced, commentary_mixed=True)


def parse_options(raw: str) -> tuple[list[str], str]:
    """Back-compatible wrapper: string candidates plus parser mode.

    Structural detail (invalid entry types, wrapper prose, code fences) is
    available from :func:`parse_document` and surfaced by :func:`diagnose`.
    """
    document = parse_document(raw)
    return list(document.options), document.mode


def partial_candidate_count(raw: str) -> int:
    """Count only fully completed candidates in an in-progress stream.

    This stays a *raw* completion count: it never guesses from prose and never
    counts an unterminated JSON string. Threshold advancement uses
    :func:`partial_usable_unique_count`, not this number.
    """
    text = str(raw or "")
    complete, _mode = parse_options(text)
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

    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        matches = [BULLET_RE.match(line) for line in lines]
        if all(matches):
            return sum(1 for match in matches if match)
    return 0


def unescape_json_string(value: str) -> str:
    try:
        decoded = json.loads('"' + value + '"')
    except json.JSONDecodeError:
        return value
    return decoded if isinstance(decoded, str) else value


def partial_option_values(raw: str) -> tuple[list[str], str]:
    """Recover the identities of the candidates completed so far.

    Shared by every streaming runner so identity recovery cannot drift from the
    frozen parser. Only string-typed JSON entries are recovered: a ``null``,
    boolean, number, object or nested list never produces a candidate value.
    """
    text = str(raw or "")
    options, mode = parse_options(text)
    if options and mode != "newline_list":
        return options, mode
    if options:
        # A streamed newline list is optimistic: ``parse_options`` counts every
        # non-empty line, including a fragment that has not been terminated yet.
        # Only newline-terminated lines are complete candidates.
        terminated = text.split(NEWLINE)[:-1]
        return [line.strip() for line in terminated if line.strip()], "newline_list_in_progress"

    prefix = OPTIONS_ARRAY_PREFIX.search(text)
    if prefix:
        body = text[prefix.end():]
        values: list[str] = []
        in_string = False
        escape = False
        start = 0
        for index, char in enumerate(body):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                    value = unescape_json_string(body[start:index])
                    # A malformed or mid-edit stream can surface separators as
                    # pseudo-values. Only a recovered string with content is a
                    # candidate; whitespace-only fragments are not.
                    if value.strip():
                        values.append(value)
                continue
            if char == '"':
                in_string = True
                start = index + 1
            elif char == "]":
                break
        return values, "json_options_array_in_progress"

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if lines:
        matches = [BULLET_RE.match(line) for line in lines]
        if all(matches):
            return [match.group(1).strip() for match in matches], "numbered_or_bulleted_list"
    return [], "unparseable"


# ---------------------------------------------------------------------------
# The one admission rule shared by offline and streaming paths


@dataclass(frozen=True)
class CandidateVerdict:
    text: str
    key: str
    usable: bool
    reason: str


class CandidateLedger:
    """Sequential usable-unique accounting over candidate texts.

    :func:`diagnose` (offline) and the streamed trackers both build one of these,
    so a duplicate, protected corruption, unchanged copy, malformed entry or
    commentary line is rejected identically on both paths.

    Admission order, first failure wins:

    1. ``commentary`` - wrapper prose is never a candidate;
    2. ``visually_empty`` - nothing survives the comparison key;
    3. ``protected_corruption`` - a protected value is missing, altered or has a
       repeated-count mismatch;
    4. ``unchanged_source`` - exact copy of the source, but only on routes whose
       contract asks for an actual transformation;
    5. ``duplicate`` - same comparison key as an already-usable candidate;
    6. ``near_duplicate`` - documented materially-same test against an
       already-usable candidate.
    """

    def __init__(
        self,
        *,
        source: str | None = None,
        requested: int = 10,
        route: str = ROUTE_ALTERNATIVES,
        protected: Iterable[Any] | None = None,
        track_near_duplicates: bool = True,
    ) -> None:
        self.source = str(source) if source is not None else None
        self.requested = int(requested)
        self.route = route if route in ROUTES else ROUTE_ALTERNATIVES
        self.protected = normalize_protected(protected)
        self.track_near_duplicates = track_near_duplicates
        self.accepted: list[str] = []
        self.accepted_keys: list[str] = []
        self._accepted_token_keys: list[str] = []
        self.verbatim: list[CandidateVerdict] = []
        self.rejected_reasons: dict[str, int] = {}
        self.unchanged_source_count = 0
        self.commentary_count = 0
        self.protected_corruption_count = 0
        self.protected_details: list[dict[str, Any]] = []
        self.exact_raw_duplicate_count = 0
        self.normalized_duplicate_count = 0
        self.near_duplicate_count = 0
        self.visually_empty_count = 0

    @property
    def usable_unique_count(self) -> int:
        return len(self.accepted_keys)

    @property
    def unchanged_counts_as_usable(self) -> bool:
        return self.route in ROUTES_WHERE_UNCHANGED_IS_USABLE

    def _reject(self, reason: str) -> None:
        self.rejected_reasons[reason] = self.rejected_reasons.get(reason, 0) + 1

    def add(self, text: Any) -> CandidateVerdict:
        """Admit one candidate text and return its verdict."""
        raw = str(text or "")
        key = comparison_key(raw)
        # A candidate that differs only in punctuation or spacing is a
        # *normalized* duplicate, not a near duplicate: the words are identical,
        # only the formatting moved. Token keys are the cheap deterministic test.
        token_key = near_key(key)
        if COMMENTARY_PREFIX.match(raw.strip()):
            self.commentary_count += 1
            self._reject("commentary")
            return self._record(CandidateVerdict(raw, key, False, "commentary"))
        if not key:
            self.visually_empty_count += 1
            self._reject("visually_empty")
            return self._record(CandidateVerdict(raw, key, False, "visually_empty"))
        if self.protected:
            evaluation = protected_evaluation(raw, source=self.source, protected=self.protected)
            # Position drift is reported even when the value itself survives, so
            # a location-sensitive failure is never invisible.
            if any(evaluation[field] for field in ("missing", "altered", "repeatedMismatch", "positionDrift")):
                self.protected_details.append({"text": raw, **evaluation})
            if evaluation["corrupted"]:
                self.protected_corruption_count += 1
                self._reject("protected_corruption")
                return self._record(CandidateVerdict(raw, key, False, "protected_corruption"))
        if self.source is not None and key == comparison_key(self.source):
            self.unchanged_source_count += 1
            if not self.unchanged_counts_as_usable:
                self._reject("unchanged_source")
                return self._record(CandidateVerdict(raw, key, False, "unchanged_source"))
        if key in self.accepted_keys:
            if raw in self.accepted:
                self.exact_raw_duplicate_count += 1
            self.normalized_duplicate_count += 1
            self._reject("duplicate")
            return self._record(CandidateVerdict(raw, key, False, "duplicate"))
        # Same words, different punctuation/spacing -> normalized duplicate.
        for index, prior in enumerate(self.accepted_keys):
            if token_key and token_key == self._accepted_token_keys[index]:
                if raw in self.accepted:
                    self.exact_raw_duplicate_count += 1
                self.normalized_duplicate_count += 1
                self._reject("duplicate")
                return self._record(CandidateVerdict(raw, key, False, "duplicate"))
        if self.track_near_duplicates:
            for prior in self.accepted_keys:
                if near_duplicate_keys(key, prior):
                    self.near_duplicate_count += 1
                    self._reject("near_duplicate")
                    return self._record(CandidateVerdict(raw, key, False, "near_duplicate"))
        self.accepted.append(raw)
        self.accepted_keys.append(key)
        self._accepted_token_keys.append(token_key)
        return self._record(CandidateVerdict(raw, key, True, "accepted"))

    def _record(self, verdict: CandidateVerdict) -> CandidateVerdict:
        self.verbatim.append(verdict)
        return verdict

    def usable_indices(self) -> list[int]:
        return [index for index, item in enumerate(self.verbatim) if item.usable]


def usable_unique_count_of(values: Iterable[Any], **context: Any) -> int:
    """Usable unique count for an explicit sequence of candidate strings."""
    ledger = CandidateLedger(**context)
    for value in values:
        ledger.add(value)
    return ledger.usable_unique_count


def partial_usable_unique_count(raw: str, *, final: bool = True, **context: Any) -> int:
    """Usable unique candidate count over the candidates visible in `raw`.

    `final=True` (the default) treats `raw` as a *completed* stream and must
    agree exactly with :func:`diagnose` on ``usableUniqueCount``. `final=False`
    applies the conservative in-progress rule that keeps an unterminated tail
    line out of the count, which is what a live chunk boundary must do. The
    streamed trackers pass the same admission rule through CandidateLedger.
    """
    values, _mode = partial_option_values(raw)
    if final:
        options, _mode = parse_options(raw)
        values = options
    return usable_unique_count_of(values, **context)


# ---------------------------------------------------------------------------
# Offline diagnostics


def diagnose(
    raw: str,
    source: str | None = None,
    requested: int = 10,
    *,
    route: str = ROUTE_ALTERNATIVES,
    protected: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Full deterministic diagnostics for one Word Studio completion."""
    document = parse_document(raw)
    options = document.options

    ledger = CandidateLedger(source=source, requested=requested, route=route, protected=protected)
    # Duplicate taxonomy is measured over *every* parsed candidate, before the
    # admission rule runs, so an unchanged copy that is also repeated still
    # reports its duplication instead of hiding behind the unchanged verdict.
    seen_raw: set[str] = set()
    seen_keys: set[str] = set()
    seen_token_keys: set[str] = set()
    exact_raw_duplicates = 0
    normalized_duplicates = 0
    for value in options:
        if value in seen_raw:
            exact_raw_duplicates += 1
        else:
            seen_raw.add(value)
        key = comparison_key(value)
        token_key = near_key(key)
        # A normalized duplicate repeats either the comparison key exactly or
        # the same words with different punctuation/spacing. Both are formatting
        # variants of the same candidate, not a distinct suggestion.
        if key in seen_keys or (token_key and token_key in seen_token_keys):
            normalized_duplicates += 1
        else:
            seen_keys.add(key)
            if token_key:
                seen_token_keys.add(token_key)
        ledger.add(value)

    keys = [comparison_key(x) for x in options]
    unique_keys = set(keys)

    statuses: list[str] = []
    if not raw or not str(raw).strip():
        statuses.append("empty_output")
    if document.fenced:
        statuses.append("word_studio_markdown_code_fence")
    if document.wrong_json_keys:
        statuses.append("word_studio_json_wrong_key")
    if document.leading_prose:
        statuses.append("word_studio_leading_prose")
    if document.trailing_prose:
        statuses.append("word_studio_trailing_commentary")
    if document.commentary_mixed:
        statuses.append("word_studio_commentary_mixed")
    if document.invalid_entries:
        statuses.append("word_studio_typed_invalid_entries")
    if document.mode in {"unparseable", "empty_output", "json_object_wrong_key", "json_object_scalar_options"}:
        statuses.append("word_studio_unparseable_list")
    if requested > 1 and not options and document.mode == "unparseable":
        statuses.append("word_studio_single_paragraph_for_multi_request")
    if ledger.protected_corruption_count:
        statuses.append("word_studio_protected_corruption")
    if any(item["altered"] for item in ledger.protected_details):
        statuses.append("word_studio_protected_value_altered")
    if any(item["repeatedMismatch"] for item in ledger.protected_details):
        statuses.append("word_studio_protected_repeated_mismatch")
    if any(item["positionDrift"] for item in ledger.protected_details):
        statuses.append("word_studio_protected_position_drift")

    usable_unique = ledger.usable_unique_count
    if usable_unique < int(requested):
        statuses.append("word_studio_too_few_candidates")
    total_duplicates = normalized_duplicates + ledger.near_duplicate_count
    if total_duplicates > max(1, int(requested) // 5):
        statuses.append("word_studio_excessive_duplicates")
    if ledger.unchanged_source_count and not ledger.unchanged_counts_as_usable:
        statuses.append("contains_unchanged_source")
    if ledger.commentary_count:
        statuses.append("contains_commentary")
    if ledger.visually_empty_count:
        statuses.append("word_studio_visually_empty_candidate")

    statuses = list(dict.fromkeys(statuses)) or ["ok"]

    return {
        "parserVersion": PARSER_VERSION,
        "parserMode": document.mode,
        "route": ledger.route,
        "unchangedCountsAsUsable": ledger.unchanged_counts_as_usable,
        "statuses": statuses,
        "requestedCount": int(requested),
        "parsedCount": len(options),
        "usableUniqueCount": usable_unique,
        "uniqueNormalizedCount": len(unique_keys),
        "duplicateCount": normalized_duplicates + ledger.near_duplicate_count,
        "duplicateTaxonomy": {
            "exactRawDuplicateCount": exact_raw_duplicates,
            "normalizedExactDuplicateCount": normalized_duplicates,
            "nearDuplicateCount": ledger.near_duplicate_count,
            "uniqueUsableCount": usable_unique,
        },
        "unchangedSourceCount": ledger.unchanged_source_count,
        "unchangedSourceUnusableCount": (
            0 if ledger.unchanged_counts_as_usable else ledger.unchanged_source_count
        ),
        "commentaryCandidateCount": ledger.commentary_count,
        "visuallyEmptyCandidateCount": ledger.visually_empty_count,
        "invalidEntryCount": len(document.invalid_entries),
        "invalidEntryTypes": document.invalid_entry_types,
        "invalidEntries": document.invalid_entries,
        "codeFenced": document.fenced,
        "jsonWrongKeys": document.wrong_json_keys,
        "protectedContentCorruptionCount": ledger.protected_corruption_count,
        "protectedContentDiagnostics": ledger.protected_details,
        "rejectedCandidateReasons": dict(sorted(ledger.rejected_reasons.items())),
        "lengthChars": [len(x) for x in options],
        "options": options,
        "usableIndices": [i for i, v in enumerate(ledger.verbatim) if v.usable],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="JSON result with outputs[] rows containing output text")
    ap.add_argument("output", type=Path)
    ap.add_argument("--requested", type=int, default=10)
    ap.add_argument("--route", default=ROUTE_ALTERNATIVES, choices=list(ROUTES))
    ap.add_argument("--tasks", type=Path, help="optional JSONL tasks for per-row source/protected/route")
    args = ap.parse_args()
    run = json.loads(args.input.read_text(encoding="utf-8"))

    tasks: dict[str, dict[str, Any]] = {}
    if args.tasks and args.tasks.exists():
        for line in args.tasks.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                tasks[str(row.get("id"))] = row

    rows = []
    for row in run.get("outputs", []):
        task = tasks.get(str(row.get("id")), {})
        rows.append({
            "id": row.get("id"),
            "diagnostics": diagnose(
                str(row.get("output") or ""),
                source=task.get("selectedText") or task.get("sourceText"),
                requested=int(task.get("requestedCount") or args.requested),
                route=route_from_task(task) if task else args.route,
                protected=task.get("protectedSpans"),
            ),
        })
    summary = {
        "version": PARSER_VERSION,
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
