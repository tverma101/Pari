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
- The same rule is enforced by the admission ledger itself, not only by the
  JSON reader, so a non-string handed to ``CandidateLedger.add`` by any
  consumer is rejected as ``typed_invalid`` and can never be stringified into
  a candidate.
- A Markdown-fenced completion is unwrapped before parsing. Only the fenced
  body is the candidate source; text before or after the fence is wrapper prose
  and is diagnosed (``word_studio_leading_prose`` /
  ``word_studio_trailing_commentary``), never scored. A fence whose closing
  marker has not arrived yet is handled by the same rule while streaming, so a
  truncated fenced stream cannot score its own fence marker or partial JSON
  line as candidates.
- Near-duplicate detection is deterministic and cheap (documented edit/token
  thresholds). There is no model judge and no embedding lookup.

GitHub issue #43.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PARSER_VERSION = 5
OPERATION_CONTRACT_VERSION = 1

BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
COMMENTARY_PREFIX = re.compile(
    r"^(?:here(?:'s| are)|sure[,!:]|options?:|alternatives?:|note:|explanations?:|"
    r"the following|based on your request|i hope this helps|let me know)",
    re.I,
)
# Wrapper prose that can follow an otherwise valid list.
COMMENTARY_TAIL_RE = re.compile(
    r"^\s*(?:here(?:'s| are)|i hope this helps|let me know|note[:\s]|explanations?:|"
    r"options?:|alternatives?:|would you like|feel free to|if you'd like)\b",
    re.I,
)
OPTIONS_ARRAY_PREFIX = re.compile(r'"options"\s*:\s*\[', re.I)
# Anchored at the fence itself but tolerant of wrapper prose: a model that wraps
# its JSON in a Markdown fence frequently appends a sign-off ("Hope this
# helps!") or a preamble afterwards. Anchoring the *whole* completion to the
# fence made `_strip_code_fence` decline any such output, so the fenced JSON,
# the fence markers and the trailing prose all fell through to the newline-list
# branch and were counted as four usable candidates. Matching only the fenced
# block keeps the JSON recoverable and lets the leftover prose be diagnosed as
# commentary instead of scored.
CODE_FENCE_RE = re.compile(r"```[^\n`]*\n(?P<body>.*?)\n?[ \t]*```", re.S)
# An opening fence whose closing marker has not arrived yet. Used by the
# streaming path so an in-progress fenced completion is never mistaken for a
# newline list: without this, a truncated ```` ```json {"options":["a" ````
# stream scored the fence marker and the partial JSON line as two candidates.
OPEN_FENCE_RE = re.compile(r"^[ \t]*```[^\n`]*\n(?P<body>.*)\Z", re.S)
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
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

# --- near-duplicate semantic guards -----------------------------------------

# A candidate pair that differs only in a number is never "materially the same":
# "$50" vs "$60" and "99.9%" vs "99.8%" are different claims, not reformatting.
# Numeric tokens are compared as a multiset so ordering and repetition do not
# matter. This guard needs no vocabulary, so it cannot drift.
NEAR_DUPLICATE_NUMERIC_TOKEN_RE = re.compile(r"\d+(?:[.,:/-]\d+)*")

# High-signal polarity/modality words. A pair that differs in whether one of these
# is present is treated as materially different ("formal" vs "informal"),
# because such a word alone can invert the candidate's meaning.
#
# Scope note: this is a *dedupe* guard, deliberately small and self-contained.
# studio_backend/protected_content.py (issue #51) owns the authoritative
# negation/modality vocabulary for protected-content diagnostics; do not extend
# this list to cover general grammar, only words that flip polarity by themselves.
NEAR_DUPLICATE_POLARITY_TOKENS = frozenset(
    {
        "not",
        "never",
        "no",
        "nor",
        "neither",
        "cannot",
        "without",
        "must",
        "mustn't",
        "should",
        "shouldn't",
        "may",
        "might",
        "always",
        "informal",
        "optional",
        "required",
    }
)

# --- route semantics -------------------------------------------------------

# Routes whose contract asks for an actual transformation. An exact copy of the
# source cannot advance useful depth on these routes.
ROUTE_ALTERNATIVES = "alternatives"
# ``intentional_compression`` is a separate semantic scoring contract, so an
# unchanged copy is not rejected by the generic full-equivalence check here.
# When a task declares a concrete gist/form target, OperationContract below is
# still responsible for enforcing that declared form.
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

WORD_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
SENTENCE_END_RE = re.compile(r"""[.!?]["'’”)\]}]*$""")

# Selected-span replacements must not quietly return the surrounding sentence.
# This deterministic n-gram check is intentionally narrow: four consecutive
# comparison-key words from the source that are not wholly inside the selection
# and appear in the candidate are treated as context leakage.
SELECTED_ONLY_NGRAM = 4


# Frozen deterministic form constraints declared by task metadata. Prompt prose is
# never parsed for these values; only explicit operation/category ids and word
# target fields participate.
_OPERATION_RULES: dict[tuple[str, str], dict[str, Any]] = {
    ("word_to_phrase", "phrase"): {"min_words": 2, "max_words": 6},
    ("phrase_to_word", "word"): {"min_words": 1, "max_words": 1},
    ("phrase_to_word", "micro"): {"min_words": 1, "max_words": 3},
    ("sentence_rewrite", "sentence"): {"require_sentence": True},
    ("sentence_rewrite", "gist3"): {"min_words": 1, "max_words": 3},
    ("phrase_to_phrase", "shorter"): {"direction": "shorter"},
    ("expansion_compression", "shorter"): {"direction": "shorter"},
    ("expansion_compression", "longer"): {"direction": "longer"},
}
_OPERATION_ALIASES: dict[str, dict[str, Any]] = {
    "gist3": {"min_words": 1, "max_words": 3},
    "compress_gist": {"min_words": 1, "max_words": 3},
}


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


@dataclass(frozen=True)
class OperationContract:
    """Deterministic eligibility constraints derived from frozen task metadata.

    This is intentionally not a semantic judge. It encodes only form constraints
    the benchmark already declares: word-count targets, explicit shorter/longer
    direction, sentence shape, and selected-span-only context containment.
    """

    operation: str | None = None
    source_category: str | None = None
    min_words: int | None = None
    max_words: int | None = None
    direction: str | None = None
    require_sentence: bool = False
    source_text: str | None = None
    selected_text: str | None = None

    @property
    def declared(self) -> bool:
        return bool(
            self.operation
            or self.source_category
            or self.min_words is not None
            or self.max_words is not None
            or self.direction
            or self.require_sentence
        )

    def to_diagnostics(self) -> dict[str, Any]:
        """Provenance without raw task text."""
        return {
            "version": OPERATION_CONTRACT_VERSION,
            "declared": self.declared,
            "operation": self.operation,
            "sourceCategory": self.source_category,
            "minWords": self.min_words,
            "maxWords": self.max_words,
            "direction": self.direction,
            "requireSentence": self.require_sentence,
            "selectedOnly": self.enforces_selected_only,
        }

    @property
    def enforces_selected_only(self) -> bool:
        if not self.source_text or not self.selected_text:
            return False
        return near_key(self.source_text) != near_key(self.selected_text)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def operation_contract_from_task(task: Mapping[str, Any] | None) -> OperationContract:
    """Build the versioned operation contract from explicit task fields only."""
    if not isinstance(task, Mapping):
        return OperationContract()
    operation = str(
        task.get("operation")
        or task.get("operationId")
        or task.get("operation_id")
        or ""
    ).strip().lower() or None
    source_category = str(
        task.get("sourceCategory")
        or task.get("source_category")
        or ""
    ).strip().lower() or None
    rules = dict(_OPERATION_RULES.get((source_category or "", operation or ""), {}))
    if not rules and operation in _OPERATION_ALIASES:
        rules = dict(_OPERATION_ALIASES[operation])

    min_words = _optional_int(
        task.get("targetMinWords")
        if task.get("targetMinWords") is not None
        else task.get("target_min_words", task.get("minWords"))
    )
    max_words = _optional_int(
        task.get("targetMaxWords")
        if task.get("targetMaxWords") is not None
        else task.get("target_max_words", task.get("maxWords"))
    )
    source_text = task.get("sourceText") or task.get("source_text") or None
    selected_text = task.get("selectedText") or task.get("selected_text") or None
    return OperationContract(
        operation=operation,
        source_category=source_category,
        min_words=min_words if min_words is not None else rules.get("min_words"),
        max_words=max_words if max_words is not None else rules.get("max_words"),
        direction=rules.get("direction"),
        require_sentence=bool(rules.get("require_sentence")),
        source_text=str(source_text) if source_text is not None else None,
        selected_text=str(selected_text) if selected_text is not None else None,
    )


def coerce_operation_contract(value: Any) -> OperationContract:
    if isinstance(value, OperationContract):
        return value
    if isinstance(value, Mapping):
        known = {
            "operation",
            "source_category",
            "min_words",
            "max_words",
            "direction",
            "require_sentence",
            "source_text",
            "selected_text",
        }
        aliases = {
            "sourceCategory": "source_category",
            "minWords": "min_words",
            "maxWords": "max_words",
            "requireSentence": "require_sentence",
            "sourceText": "source_text",
            "selectedText": "selected_text",
        }
        normalized: dict[str, Any] = {}
        for key in known:
            if key in value:
                normalized[key] = value[key]
        for source, target in aliases.items():
            if target not in normalized and source in value:
                normalized[target] = value[source]
        return OperationContract(**normalized)
    return OperationContract()


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


def _numeric_tokens(key: str) -> tuple[str, ...]:
    """Sorted numeric-token multiset of a comparison key, for the dedupe guard."""
    return tuple(sorted(NEAR_DUPLICATE_NUMERIC_TOKEN_RE.findall(comparison_key(key))))


def _polarity_tokens(key: str) -> tuple[str, ...]:
    """Sorted polarity/modality token multiset of a comparison key."""
    tokens = WORD_RE.findall(comparison_key(key))
    return tuple(sorted(token for token in tokens if token in NEAR_DUPLICATE_POLARITY_TOKENS))


def near_duplicate_keys(left: str, right: str) -> bool:
    """Deterministic, cheap "materially the same candidate" test.

    Two comparison keys are near-duplicates when the shorter one is at least
    ``NEAR_DUPLICATE_MIN_CHARS`` long and either:

    - the character similarity ratio is >= ``NEAR_DUPLICATE_RATIO``, or
    - token-multiset overlap is >= ``NEAR_DUPLICATE_TOKEN_OVERLAP`` while the
      token counts stay within ``NEAR_DUPLICATE_LENGTH_SLACK`` of each other.

    Two guards veto the pairing first, because a purely lexical test would
    otherwise collapse alternatives whose whole point is the token that differs:

    - a difference in the numeric-token multiset ("$50" vs "$60", "99.9%" vs
      "99.8%") is a different claim, not a reformatting;
    - a difference in the polarity/modality token multiset (see
      ``NEAR_DUPLICATE_POLARITY_TOKENS``) can invert the meaning ("formal" vs
      "informal", "must" vs "must not").

    Genuinely different alternatives ("a concise summary" vs "an unrelated
    anecdote") fall well below both thresholds, and the guards keep genuinely
    different *near*-neighbours apart.
    """
    if left == right:
        return True
    if not left or not right:
        return False
    if min(len(left), len(right)) < NEAR_DUPLICATE_MIN_CHARS:
        return False
    if _numeric_tokens(left) != _numeric_tokens(right):
        return False
    if _polarity_tokens(left) != _polarity_tokens(right):
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
# Deterministic operation-form eligibility


def word_count(text: str) -> int:
    """Count natural word tokens without depending on whitespace formatting."""
    return len(WORD_RE.findall(comparison_key(text)))


def _token_ngrams(tokens: Sequence[str], size: int) -> set[tuple[str, ...]]:
    if len(tokens) < size:
        return set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def _selection_context_leakage(candidate: str, contract: OperationContract) -> bool:
    """Detect a selected-span replacement that returned surrounding context.

    The rule is intentionally conservative and mechanical: a candidate is
    rejected only when it contains a four-token source n-gram that is not wholly
    inside the selected span. Semantic similarity is still left to human review.
    """
    if not contract.enforces_selected_only:
        return False
    source_tokens = comparison_key(contract.source_text or "").split()
    selected_tokens = comparison_key(contract.selected_text or "").split()
    candidate_ngrams = _token_ngrams(comparison_key(candidate).split(), SELECTED_ONLY_NGRAM)
    if not candidate_ngrams:
        return False
    selected_ngrams = _token_ngrams(selected_tokens, SELECTED_ONLY_NGRAM)
    return any(
        ngram not in selected_ngrams
        for ngram in _token_ngrams(source_tokens, SELECTED_ONLY_NGRAM)
        if ngram in candidate_ngrams
    )


def operation_form_violation(
    candidate: str,
    *,
    source: str | None,
    contract: OperationContract,
) -> list[str]:
    """Return deterministic form violations for one candidate.

    Empty contracts impose no operation-form eligibility. Human review still
    judges naturalness, meaning, and quality.
    """
    if not contract.declared:
        return []
    raw = str(candidate or "")
    words = word_count(raw)
    reference = contract.selected_text or source
    violations: list[str] = []
    if contract.min_words is not None and words < contract.min_words:
        violations.append("min_words")
    if contract.max_words is not None and words > contract.max_words:
        violations.append("max_words")
    if contract.direction and reference:
        source_words = word_count(reference)
        if contract.direction == "shorter" and words >= source_words:
            violations.append("direction_shorter")
        if contract.direction == "longer" and words <= source_words:
            violations.append("direction_longer")
    if contract.require_sentence and (words < 3 or not SENTENCE_END_RE.search(raw.strip())):
        violations.append("require_sentence")
    if _selection_context_leakage(raw, contract):
        violations.append("selection_context_leakage")
    return violations


# ---------------------------------------------------------------------------
# Protected content
#
# The corruption rule is owned by studio_backend/protected_content.py (issue
# #51). Import it lazily inside the adapter: studio_backend.__init__ imports
# safety.py, which in turn imports this module, so a module-level import would
# create a cycle during package initialization.


@dataclass(frozen=True)
class ProtectedValue:
    text: str
    start: int | None = None
    end: int | None = None
    range_encoding: str | None = None
    span_id: str | None = None
    kind: str | None = None
    scope: str | None = None
    source_sha256: str | None = None
    protected_span_sha256: str | None = None
    candidate_start: int | None = None
    candidate_end: int | None = None


def normalize_protected(values: Iterable[Any] | None) -> tuple[ProtectedValue, ...]:
    """Accept strings, ``{text,start,end}`` mappings or ProtectedValue in order."""
    out: list[ProtectedValue] = []
    seen: set[tuple[int | None, int | None, str, str | None]] = set()
    for item in values or ():
        if isinstance(item, ProtectedValue):
            span = item
        elif isinstance(item, str):
            span = ProtectedValue(item)
        elif isinstance(item, Mapping):
            start = item.get("start")
            end = item.get("end")
            range_encoding = item.get("rangeEncoding") or item.get("range_encoding")
            span_id = item.get("id")
            source_sha256 = item.get("sourceSha256")
            protected_span_sha256 = item.get("protectedSpanSha256")
            candidate_start = item.get("candidateStart")
            candidate_end = item.get("candidateEnd")
            span = ProtectedValue(
                str(item.get("text") or ""),
                start if isinstance(start, int) else None,
                end if isinstance(end, int) else None,
                str(range_encoding) if range_encoding else None,
                str(span_id) if span_id is not None else None,
                str(item["kind"]) if item.get("kind") is not None else None,
                str(item["scope"]) if item.get("scope") is not None else None,
                str(source_sha256) if source_sha256 is not None else None,
                str(protected_span_sha256) if protected_span_sha256 is not None else None,
                candidate_start if isinstance(candidate_start, int) else None,
                candidate_end if isinstance(candidate_end, int) else None,
            )
        else:
            continue
        if not span.text:
            continue
        key = (span.start, span.end, span.text, span.range_encoding)
        if key in seen:
            continue
        seen.add(key)
        out.append(span)
    return tuple(out)


def _protected_contract() -> Any:
    """Load the canonical issue #51 module without creating an import cycle."""
    return importlib.import_module("studio_backend.protected_content")


def _protected_payload(span: ProtectedValue) -> dict[str, Any]:
    return {
        "id": span.span_id,
        "kind": span.kind,
        "scope": span.scope,
        "text": span.text,
        "start": span.start,
        "end": span.end,
        "rangeEncoding": span.range_encoding,
        "sourceSha256": span.source_sha256,
        "protectedSpanSha256": span.protected_span_sha256,
        "candidateStart": span.candidate_start,
        "candidateEnd": span.candidate_end,
    }


def _infer_protected_kind(contract: Any, text: str) -> str:
    kinds = {
        span.kind
        for span in contract.extract_protected_spans(str(text or ""))
        if span.text == text
    }
    return next(iter(kinds)) if len(kinds) == 1 else "code"


def _canonical_protected_spans(
    contract: Any,
    source: str | None,
    protected: Iterable[Any] | None,
) -> tuple[tuple[Any, ...], int]:
    """Adapt legacy parser spans to canonical issue #51 span dataclasses.

    Legacy benchmark tasks carry code-point offsets, while the #51 wire contract
    carries UTF-16 offsets. An explicit ``rangeEncoding`` always wins. Otherwise a
    coordinate is treated as a code-point offset when it reproduces the declared
    source text exactly, and only then retried as UTF-16. This keeps existing
    task files valid without weakening wire identity checks.
    """
    values = normalize_protected(protected)
    source_text = str(source or "")
    detected = (
        tuple(contract.extract_protected_spans(source_text)) if source_text else ()
    )
    detected_at_position = {
        (span.start, span.end, span.text): span for span in detected
    }
    detected_by_text: dict[str, list[Any]] = {}
    for span in detected:
        detected_by_text.setdefault(span.text, []).append(span)

    canonical: list[Any] = []
    digest_source = (
        contract.compute_source_sha256(source_text) if source_text else None
    )
    for index, value in enumerate(values):
        position_match = (
            detected_at_position.get((value.start, value.end, value.text))
            if value.start is not None and value.end is not None
            else None
        )
        inferred_kind = (
            value.kind
            or (position_match.kind if position_match is not None else None)
            or _infer_protected_kind(contract, value.text)
        )
        inferred_scope = (
            value.scope
            or (position_match.scope if position_match is not None else None)
            or "required"
        )
        if inferred_kind not in contract.PROTECTED_SPAN_KINDS:
            inferred_kind = "code"
        if inferred_scope not in contract.PROTECTED_SPAN_SCOPES:
            inferred_scope = "required"

        if value.start is not None and value.end is not None and source_text:
            payload = _protected_payload(value)
            encoding = value.range_encoding or ""
            code_point_match = (
                0 <= value.start < value.end <= len(source_text)
                and source_text[value.start : value.end] == value.text
            )
            if encoding or not code_point_match:
                # An explicit encoding is a contract claim, so let the shared
                # validator accept or reject it exactly. Only legacy spans with
                # no declared encoding fall back to UTF-16 wire coordinates.
                payload["rangeEncoding"] = encoding or "utf16-v1"
                span = contract.span_from_wire(
                    source_text,
                    payload,
                    source_sha256=value.source_sha256,
                    index=index,
                )
            else:
                span = contract.ProtectedContentSpan(
                    id=str(
                        value.span_id
                        or (position_match.id if position_match is not None else "")
                        or f"legacy-{index}-{value.start}-{value.end}"
                    ),
                    kind=inferred_kind,
                    scope=inferred_scope,
                    text=value.text,
                    start=value.start,
                    end=value.end,
                    range_encoding="utf16-v1",
                    source_sha256=value.source_sha256 or digest_source,
                    protected_span_sha256=value.protected_span_sha256,
                    candidate_start=value.candidate_start,
                    candidate_end=value.candidate_end,
                )
            canonical.append(
                replace(
                    span,
                    id=str(value.span_id or span.id),
                    kind=inferred_kind,
                    scope=inferred_scope,
                )
            )
            continue

        matches = [
            span
            for span in detected_by_text.get(value.text, ())
            if value.kind is None or span.kind == value.kind
        ]
        if matches:
            for match_index, span in enumerate(matches):
                canonical.append(
                    replace(
                        span,
                        id=str(
                            span.id
                            if not value.span_id or match_index > 0
                            else value.span_id
                        ),
                        kind=inferred_kind,
                        scope=inferred_scope,
                        candidate_start=(
                            value.candidate_start
                            if value.candidate_start is not None
                            else span.candidate_start
                        ),
                        candidate_end=(
                            value.candidate_end
                            if value.candidate_end is not None
                            else span.candidate_end
                        ),
                    )
                )
            continue

        base = contract.normalize_protected_spans([value.text])[0]
        canonical.append(
            replace(
                base,
                id=str(value.span_id or base.id),
                kind=inferred_kind,
                scope=inferred_scope,
            )
        )
    return tuple(canonical), len(values)


def protected_evaluation(
    candidate: str,
    *,
    source: str | None = None,
    protected: Iterable[Any] | None = None,
    protected_route: str = "whole",
    anchor_policy: str | None = None,
    selection: tuple[int, int] | None = None,
    selection_sha256: str | None = None,
    candidate_range: tuple[int, int] | None = None,
    candidate_document: str | None = None,
    source_sha256: str | None = None,
    strict_identity: bool = False,
) -> dict[str, Any]:
    """Adapt the canonical #51 evaluation to the parser's stable public shape.

    The returned keys remain ``protectedCount``, ``missing``, ``altered``,
    ``repeatedMismatch``, ``positionDrift`` and ``corrupted``. Optional keyword
    arguments expose the shared contract's local-route inputs for parity tests;
    ordinary Word Studio diagnostics continue to use ``protected_route="whole"``.
    """
    contract = _protected_contract()
    text = str(candidate or "")
    source_text = str(source or "")
    try:
        spans, declared_count = _canonical_protected_spans(
            contract,
            source_text,
            protected,
        )
        evaluation = contract.evaluate_protected_content(
            source_text,
            text,
            protected=spans,
            route=protected_route,
            anchor_policy=anchor_policy,
            selection=selection,
            selection_sha256=selection_sha256,
            candidate_range=candidate_range,
            candidate_document=candidate_document,
            source_sha256=source_sha256,
            strict_identity=strict_identity,
        )
    except contract.ProtectedContentError:
        if strict_identity:
            raise
        return {
            "protectedCount": len(normalize_protected(protected)),
            "missing": [],
            "altered": [],
            "repeatedMismatch": [],
            "positionDrift": [],
            "corrupted": True,
        }

    def unique(values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    text_by_id = {span.id: span.text for span in spans}

    def span_texts(span_ids: Iterable[str]) -> list[str]:
        return unique(
            text_by_id[span_id]
            for span_id in span_ids
            if span_id in text_by_id
        )

    return {
        "protectedCount": declared_count,
        "missing": span_texts(evaluation.missing_span_ids),
        "altered": span_texts(evaluation.altered_span_ids),
        "repeatedMismatch": span_texts(evaluation.repeated_mismatch_span_ids),
        "positionDrift": span_texts(evaluation.position_drift_span_ids),
        "corrupted": evaluation.corrupted,
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
    markdown_heading: bool = False
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


def _strip_code_fence(text: str) -> tuple[str, bool, bool, bool]:
    """Recover the fenced body and report wrapper prose around the fence.

    Returns ``(body, fenced, leading_prose, trailing_prose)``. Only the fenced
    block is the candidate source; anything outside the fence is prose and must
    never be scored as a candidate. Nothing is regenerated or rewritten -- the
    fenced body is returned byte-for-byte.
    """
    match = CODE_FENCE_RE.search(text)
    if not match:
        return text, False, False, False
    before = text[: match.start()].strip()
    after = text[match.end() :].strip()
    leading = bool(before) and COMMENTARY_PREFIX.match(before.splitlines()[0].strip()) is not None
    trailing = bool(after)
    return match.group("body"), True, leading, trailing


def _string_entries(entries: Sequence[Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Split a JSON list into string candidates and typed invalid entries.

    Non-string entries are never coerced to strings; each is reported with its
    index and JSON type so diagnostics stay honest.
    """
    values: list[str] = []
    invalid: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            # Preserve the candidate text exactly as decoded. Whitespace and
            # invisible characters are handled by ``comparison_key`` for
            # admission/dedupe, never by rewriting the reported candidate.
            values.append(entry)
            continue
        invalid.append({"index": index, "type": _json_entry_kind(entry)})
    return values, invalid


def parse_document(raw: str) -> ParsedDocument:
    """Parse a completion into string candidates plus structural diagnostics."""
    text = str(raw or "").strip()
    if not text:
        return ParsedDocument(mode="empty_output")
    body, fenced, fence_leading_prose, fence_trailing_prose = _strip_code_fence(text)
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
                mode="json_object",
                options=values,
                invalid_entries=invalid,
                fenced=fenced,
                leading_prose=fence_leading_prose,
                trailing_prose=fence_trailing_prose,
            )
        if isinstance(obj, dict) and "options" in obj and not isinstance(obj.get("options"), list):
            return ParsedDocument(
                mode="json_object_scalar_options",
                wrong_json_keys=["options"],
                fenced=fenced,
                leading_prose=fence_leading_prose,
                trailing_prose=fence_trailing_prose,
            )
        if isinstance(obj, dict):
            keys = [str(k) for k in obj.keys()]
            list_keys = [k for k in keys if k in KNOWN_LIST_KEYS]
            return ParsedDocument(
                mode="json_object_wrong_key",
                wrong_json_keys=sorted(list_keys) or sorted(keys),
                fenced=fenced,
                leading_prose=fence_leading_prose,
                trailing_prose=fence_trailing_prose,
            )
        if isinstance(obj, list):
            values, invalid = _string_entries(obj)
            return ParsedDocument(
                mode="json_array",
                options=values,
                invalid_entries=invalid,
                fenced=fenced,
                leading_prose=fence_leading_prose,
                trailing_prose=fence_trailing_prose,
            )
        return ParsedDocument(
            mode="json_object_wrong_key",
            wrong_json_keys=[_json_entry_kind(obj)],
            fenced=fenced,
            leading_prose=fence_leading_prose,
            trailing_prose=fence_trailing_prose,
        )

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ParsedDocument(mode="empty_output", fenced=fenced)
    has_markdown_heading = any(MARKDOWN_HEADING_RE.match(line) for line in lines)

    bullet_values: list[str] = []
    bullet_matches = 0
    for line in lines:
        match = BULLET_RE.match(line)
        if match:
            bullet_matches += 1
            bullet_values.append(match.group(1).strip())

    if lines and bullet_matches == len(lines):
        return ParsedDocument(
            mode="numbered_or_bulleted_list",
            options=bullet_values,
            fenced=fenced,
            leading_prose=fence_leading_prose,
            trailing_prose=fence_trailing_prose,
            markdown_heading=has_markdown_heading,
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
                markdown_heading=has_markdown_heading,
            )
        if any(COMMENTARY_PREFIX.match(x.strip()) for x in tail):
            return ParsedDocument(
                mode="numbered_or_bulleted_list",
                options=bullet_values,
                fenced=fenced,
                commentary_mixed=True,
                markdown_heading=has_markdown_heading,
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
            markdown_heading=has_markdown_heading,
        )

    if 2 <= len(lines) <= 40 and all(not COMMENTARY_PREFIX.match(line.strip()) for line in lines):
        return ParsedDocument(
            mode="newline_list",
            options=[line.strip() for line in lines],
            fenced=fenced,
            markdown_heading=has_markdown_heading,
        )

    return ParsedDocument(
        mode="unparseable",
        fenced=fenced,
        commentary_mixed=True,
        markdown_heading=has_markdown_heading,
    )


def parse_options(raw: str) -> tuple[list[str], str]:
    """Back-compatible wrapper: string candidates plus parser mode.

    Structural detail (invalid entry types, wrapper prose, code fences) is
    available from :func:`parse_document` and surfaced by :func:`diagnose`.
    """
    document = parse_document(raw)
    return list(document.options), document.mode


def partial_candidate_count(raw: str) -> int:
    """Count the raw candidate identities visible in an in-progress stream.

    This stays a *raw* parser count: it never guesses from prose and never counts
    an unterminated JSON string. Line-based lists are already structurally
    delimited by their visible lines, so their final visible line is counted even
    before a trailing newline arrives. Threshold advancement still uses
    :func:`partial_usable_unique_count`, not this number.
    """
    values, _mode = partial_option_values(str(raw or ""))
    return len(values)


def unescape_json_string(value: str) -> str:
    try:
        decoded = json.loads('"' + value + '"')
    except json.JSONDecodeError:
        return value
    return decoded if isinstance(decoded, str) else value


def _json_options_array_prefix_values(body: str) -> tuple[list[str], bool]:
    """Recover only completed top-level string entries from an options array.

    ``body`` starts immediately after ``"options": [``. Each top-level array
    element is buffered until a structural comma or closing bracket proves it
    complete, then decoded with :func:`json.loads`. Non-string entries --
    including object keys inside nested objects -- can therefore never be
    mistaken for candidates in a partial stream.
    """
    values: list[str] = []
    in_string = False
    escape = False
    nested_depth = 0
    element_start = 0
    saw_nonspace = False

    def flush(end: int) -> None:
        raw = body[element_start:end].strip()
        if not raw:
            return
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(value, str) and value.strip():
            values.append(value)

    for index, char in enumerate(body):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
                if nested_depth == 0:
                    # At top level, a closing quote proves the current element
                    # is a complete JSON string even before the comma/closing
                    # bracket arrives. Nested object keys stay buffered because
                    # ``nested_depth`` is non-zero inside objects/arrays.
                    raw = body[element_start : index + 1].strip()
                    try:
                        value = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        value = None
                    if isinstance(value, str) and value.strip():
                        values.append(value)
                        element_start = index + 1
            continue
        if char == '"':
            in_string = True
            saw_nonspace = True
            continue
        if char in "{[":
            nested_depth += 1
            saw_nonspace = True
            continue
        if char in "}]":
            if nested_depth:
                nested_depth -= 1
                saw_nonspace = True
                continue
            if char != "]":
                break
            flush(index)
            return values, True
        if char == "," and nested_depth == 0:
            flush(index)
            element_start = index + 1
            saw_nonspace = True
            continue
        if not char.isspace():
            saw_nonspace = True
    return values, saw_nonspace


def partial_option_values(
    raw: str,
    *,
    include_visible_tail: bool = True,
) -> tuple[list[str], str]:
    """Recover the identities of the candidates completed so far.

    Shared by every streaming runner so identity recovery cannot drift from the
    frozen parser. Only string-typed JSON entries are recovered: a ``null``,
    boolean, number, object or nested list never produces a candidate value.

    ``include_visible_tail`` is true for raw streaming counter parity with the
    line-list parser, and false for the stricter shared incremental state, which
    withholds a growing final line until a structural terminator arrives.

    An opening fence with no closing fence yet is unwrapped before anything
    else. Otherwise a truncated fenced stream reaches the newline-list branch
    and the fence marker plus the partial JSON line are counted as candidates,
    which would let a malformed fragment advance first-1/3/10.
    """
    text = str(raw or "")
    # Only an *unterminated* fence takes this path. A closed fence must fall
    # through to the one-shot parse, otherwise the closing ``` would be scored
    # as a candidate line.
    open_fence = (
        None if CODE_FENCE_RE.search(text) else OPEN_FENCE_RE.match(text)
    )
    if open_fence:
        return _partial_body_values(
            open_fence.group("body"),
            mode_suffix="_fenced",
            include_visible_tail=include_visible_tail,
        )
    options, mode = parse_options(text)
    if options and mode == "numbered_or_bulleted_list" and not include_visible_tail:
        completed: list[str] = []
        for line in text.split(NEWLINE)[:-1]:
            match = BULLET_RE.match(line.rstrip())
            if match:
                completed.append(match.group(1).strip())
        in_progress_mode = "numbered_or_bulleted_list_in_progress"
        return completed, mode if len(completed) == len(options) else in_progress_mode
    if options and mode == "newline_list" and not include_visible_tail:
        terminated = text.split(NEWLINE)[:-1]
        return [line.strip() for line in terminated if line.strip()], "newline_list_in_progress"
    if options:
        # Numbered/bulleted and newline lists are structurally delimited by their
        # visible lines. The streaming runner calls this helper only at candidate
        # completion marks, so the visible final line is a deterministic raw
        # candidate identity even before a trailing newline arrives.
        return options, mode

    return _partial_body_values(text, mode_suffix="", include_visible_tail=include_visible_tail)


def _partial_body_values(
    text: str,
    *,
    mode_suffix: str,
    include_visible_tail: bool,
) -> tuple[list[str], str]:
    """Recover completed candidates from a (possibly fenced) stream body."""
    prefix = OPTIONS_ARRAY_PREFIX.search(text)
    if prefix:
        body = text[prefix.end():]
        values, saw_nonspace = _json_options_array_prefix_values(body)
        if values or saw_nonspace:
            return values, f"json_options_array_in_progress{mode_suffix}"
        return [], f"unparseable{mode_suffix}"

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if lines:
        matches = [BULLET_RE.match(line) for line in lines]
        if all(matches):
            values = [match.group(1).strip() for match in matches]
            if include_visible_tail:
                return values, f"numbered_or_bulleted_list{mode_suffix}"
            completed = [
                match.group(1).strip()
                for match in (BULLET_RE.match(line) for line in lines[:-1])
                if match
            ]
            mode = (
                f"numbered_or_bulleted_list{mode_suffix}"
                if len(completed) == len(values)
                else f"numbered_or_bulleted_list_in_progress{mode_suffix}"
            )
            return completed, mode
    return [], f"unparseable{mode_suffix}"


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

    1. ``typed_invalid`` - a non-string entry is never coerced into a candidate
       (``None``/``True``/``3``/``{"x": 1}`` must not become ``"None"``/``"True"``);
    2. ``commentary`` - wrapper prose is never a candidate;
    3. ``visually_empty`` - nothing survives the comparison key;
    4. ``protected_corruption`` - a protected value is missing, altered or has a
       repeated-count mismatch;
    5. ``unchanged_source`` - exact copy of the source, but only on routes whose
       contract asks for an actual transformation;
    6. ``operation_form`` - deterministic word-count, direction, sentence or
       selected-span containment violation;
    7. ``duplicate`` - same comparison key as an already-usable candidate;
    8. ``near_duplicate`` - documented materially-same test against an
       already-usable candidate.
    """

    def __init__(
        self,
        *,
        source: str | None = None,
        requested: int = 10,
        route: str = ROUTE_ALTERNATIVES,
        protected: Iterable[Any] | None = None,
        operation_contract: Any = None,
        track_near_duplicates: bool = True,
    ) -> None:
        self.source = str(source) if source is not None else None
        self.requested = int(requested)
        self.route = route if route in ROUTES else ROUTE_ALTERNATIVES
        self.protected = normalize_protected(protected)
        self.operation_contract = coerce_operation_contract(operation_contract)
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
        self.operation_form_violation_count = 0
        self.operation_details: list[dict[str, Any]] = []

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
        # A non-string entry is rejected before any comparison key is built.
        # Coercing here would reintroduce exactly the issue-43 failure mode:
        # ``True`` -> "True", ``3`` -> "3", ``{"x": 1}`` -> "{'x': 1}" would
        # all become usable candidate strings. ``diagnose`` already filters
        # typed entries in ``parse_document``; this keeps the shared admission
        # rule safe for every other caller of ``CandidateLedger.add``.
        if not isinstance(text, str):
            self._reject("typed_invalid")
            return self._record(
                CandidateVerdict("", "", False, "typed_invalid")
            )
        raw = text
        key = comparison_key(raw)
        # A candidate that differs only in punctuation or spacing is a
        # *normalized* duplicate, not a near duplicate: the words are identical,
        # only the formatting moved. Token keys are the cheap deterministic test.
        token_key = near_key(key)
        if COMMENTARY_PREFIX.match(raw.strip()) or MARKDOWN_HEADING_RE.match(raw.strip()):
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
                # Candidate-level protected diagnostics deliberately do not echo
                # the rejected candidate or the original source text. Protected
                # values remain visible in the existing list fields for #51
                # compatibility, but arbitrary model/source prose stays out of
                # this diagnostic surface.
                self.protected_details.append({"index": len(self.verbatim), **evaluation})
            if evaluation["corrupted"]:
                self.protected_corruption_count += 1
                self._reject("protected_corruption")
                return self._record(CandidateVerdict(raw, key, False, "protected_corruption"))
        if self.source is not None and (
            key == comparison_key(self.source)
            or (near_key(key) and near_key(key) == near_key(self.source))
        ):
            self.unchanged_source_count += 1
            if not self.unchanged_counts_as_usable:
                self._reject("unchanged_source")
                return self._record(CandidateVerdict(raw, key, False, "unchanged_source"))
        violations = operation_form_violation(
            raw,
            source=self.source,
            contract=self.operation_contract,
        )
        if violations:
            self.operation_form_violation_count += 1
            self.operation_details.append({"index": len(self.verbatim), "violations": violations})
            self._reject("operation_form")
            return self._record(CandidateVerdict(raw, key, False, "operation_form"))
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
    if final:
        options, _mode = parse_options(raw)
        values = options
    else:
        values, _mode = partial_option_values(raw, include_visible_tail=False)
    return usable_unique_count_of(values, **context)


@dataclass(frozen=True)
class IncrementalUsableSnapshot:
    """One deterministic observation from :class:`IncrementalUsableCandidates`."""

    final: bool
    parser_mode: str
    raw_completed_count: int
    usable_values: tuple[str, ...]
    usable_keys: tuple[str, ...]
    usable_unique_count: int
    new_values: tuple[str, ...]
    new_keys: tuple[str, ...]
    newly_reached_thresholds: tuple[int, ...]
    reached_thresholds: tuple[int, ...]
    prefix_stable: bool


class IncrementalUsableCandidates:
    """Shared incremental admission state for streamed Word Studio candidates.

    The runner supplies the accumulated response text at each chunk boundary.
    Every observation re-parses that text with the same
    :class:`CandidateLedger` used by :func:`diagnose`, then reports only the
    newly admitted candidates and newly reached thresholds. Rebuilding from the
    accumulated text is intentional: a provisional list item is withheld until
    a structural terminator arrives, and a later chunk cannot silently retract a
    threshold that was already reported.

    ``finish(final_text)`` performs the one-shot parse. The resulting
    ``usable_values``/``usable_keys`` set and count are exactly the values that
    ``diagnose(final_text, ...)`` reports for the same context.
    """

    def __init__(
        self,
        *,
        thresholds: Iterable[int] = (1, 3, 10),
        **context: Any,
    ) -> None:
        normalized_thresholds: set[int] = set()
        for value in thresholds:
            if isinstance(value, bool):
                continue
            number = int(value)
            if number > 0:
                normalized_thresholds.add(number)
        self.thresholds = tuple(sorted(normalized_thresholds))
        self.context = dict(context)
        if self.context.get("protected") is not None:
            self.context["protected"] = normalize_protected(self.context["protected"])
        if self.context.get("operation_contract") is not None:
            self.context["operation_contract"] = coerce_operation_contract(
                self.context["operation_contract"]
            )
        self._ledger = CandidateLedger(**self.context)
        self._raw = ""
        self._parser_mode = "empty_output"
        self._final = False
        self._scan_generation = 0
        self._last_values: tuple[str, ...] = ()
        self._last_keys: tuple[str, ...] = ()
        self._reached_thresholds: set[int] = set()

    @property
    def ledger(self) -> CandidateLedger:
        return self._ledger

    @property
    def raw(self) -> str:
        return self._raw

    @property
    def parser_mode(self) -> str:
        return self._parser_mode

    @property
    def final(self) -> bool:
        return self._final

    @property
    def scan_generation(self) -> int:
        return self._scan_generation

    @property
    def usable_values(self) -> tuple[str, ...]:
        return tuple(self._ledger.accepted)

    @property
    def usable_keys(self) -> tuple[str, ...]:
        return tuple(self._ledger.accepted_keys)

    @property
    def usable_unique_count(self) -> int:
        return self._ledger.usable_unique_count

    def _extract(self, accumulated: str, *, final: bool) -> tuple[list[str], str]:
        if final:
            document = parse_document(accumulated)
            return list(document.options), document.mode
        values, _mode = partial_option_values(accumulated, include_visible_tail=False)
        return list(values), _mode

    def observe(self, accumulated: str, *, final: bool = False) -> IncrementalUsableSnapshot:
        """Observe the full response text accumulated so far."""
        text = str(accumulated or "")
        values, mode = self._extract(text, final=final)
        ledger = CandidateLedger(**self.context)
        for value in values:
            ledger.add(value)
        usable_values = tuple(ledger.accepted)
        usable_keys = tuple(ledger.accepted_keys)
        prefix_stable = usable_values[: len(self._last_values)] == self._last_values
        if prefix_stable:
            new_values = usable_values[len(self._last_values) :]
            new_keys = usable_keys[len(self._last_keys) :]
        else:
            # A malformed or structurally reclassified response must not make a
            # runner retract an earlier threshold. Expose the change instead.
            prior_keys = set(self._last_keys)
            new_values = tuple(
                value
                for value, key in zip(usable_values, usable_keys)
                if key not in prior_keys
            )
            new_keys = tuple(key for key in usable_keys if key not in prior_keys)
        current_count = len(usable_values)
        newly_reached = tuple(
            threshold
            for threshold in self.thresholds
            if threshold not in self._reached_thresholds and current_count >= threshold
        )
        self._reached_thresholds.update(newly_reached)
        self._ledger = ledger
        self._raw = text
        self._parser_mode = mode
        self._final = bool(final)
        self._scan_generation += 1
        self._last_values = usable_values
        self._last_keys = usable_keys
        return IncrementalUsableSnapshot(
            final=self._final,
            parser_mode=mode,
            raw_completed_count=len(values),
            usable_values=usable_values,
            usable_keys=usable_keys,
            usable_unique_count=current_count,
            new_values=new_values,
            new_keys=new_keys,
            newly_reached_thresholds=newly_reached,
            reached_thresholds=tuple(
                threshold for threshold in self.thresholds if threshold in self._reached_thresholds
            ),
            prefix_stable=prefix_stable,
        )

    def finish(self, final_text: str) -> IncrementalUsableSnapshot:
        """Finalize the stream with the complete response text."""
        return self.observe(final_text, final=True)

    def one_shot_agreement(self) -> bool:
        """Prove the finalized state equals a one-shot ``diagnose`` call."""
        if not self._final:
            return False
        context = dict(self.context)
        diagnostic = diagnose(
            self._raw,
            source=context.get("source"),
            requested=int(context.get("requested", 10)),
            route=context.get("route", ROUTE_ALTERNATIVES),
            protected=context.get("protected"),
            operation_contract=context.get("operation_contract"),
        )
        expected_values = tuple(
            diagnostic["options"][index] for index in diagnostic["usableIndices"]
        )
        return (
            expected_values == self.usable_values
            and diagnostic["usableUniqueCount"] == self.usable_unique_count
        )


# ---------------------------------------------------------------------------
# Offline diagnostics


def diagnose(
    raw: str,
    source: str | None = None,
    requested: int = 10,
    *,
    route: str = ROUTE_ALTERNATIVES,
    protected: Iterable[Any] | None = None,
    operation_contract: Any = None,
) -> dict[str, Any]:
    """Full deterministic diagnostics for one Word Studio completion."""
    document = parse_document(raw)
    options = document.options

    ledger = CandidateLedger(
        source=source,
        requested=requested,
        route=route,
        protected=protected,
        operation_contract=operation_contract,
    )
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
    if document.markdown_heading:
        statuses.append("word_studio_markdown_heading")
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
    if ledger.operation_form_violation_count:
        statuses.append("word_studio_operation_form_violation")

    statuses = list(dict.fromkeys(statuses)) or ["ok"]

    return {
        "parserVersion": PARSER_VERSION,
        "operationContractVersion": OPERATION_CONTRACT_VERSION,
        "operationContract": ledger.operation_contract.to_diagnostics(),
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
        "operationFormViolationCount": ledger.operation_form_violation_count,
        "operationDiagnostics": ledger.operation_details,
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
                operation_contract=operation_contract_from_task(task),
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
