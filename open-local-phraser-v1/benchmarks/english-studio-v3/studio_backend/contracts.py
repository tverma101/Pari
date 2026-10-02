#!/usr/bin/env python3
"""Stable request/response contracts for the future Pari Word Studio backend."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import re
import uuid


class Operation(str, Enum):
    REWRITE = "rewrite"
    REPLACE = "replace"
    SHORTEN = "shorten"
    EXPAND = "expand"
    COMPRESS_GIST = "compress_gist"
    SPLIT = "split"
    JOIN = "join"
    SIMPLIFY = "simplify"
    DIFFERENT_STRUCTURE = "different_structure"
    PRESERVE_REGISTER = "preserve_register"


class SemanticMode(str, Enum):
    FULL_PRESERVATION = "full_preservation"
    INTENTIONAL_COMPRESSION = "intentional_compression"
    CONTROLLED_EXPANSION = "controlled_expansion"


class CandidateLane(str, Enum):
    FAST = "fast"
    DIVERSITY = "diversity"


@dataclass(frozen=True)
class TextRange:
    start: int
    end: int

    def validate(self, text: str) -> None:
        if self.start < 0 or self.end <= self.start or self.end > len(text):
            raise ValueError(f"invalid selection range {self.start}:{self.end} for text length {len(text)}")


@dataclass(frozen=True)
class ProtectedSpan:
    text: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class StudioRequest:
    document_text: str
    selection: TextRange
    operation: Operation
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    strength: int = 60
    requested_candidates: int = 40
    target_min_words: int | None = None
    target_max_words: int | None = None
    protected_spans: tuple[ProtectedSpan, ...] = ()
    context_before_chars: int = 900
    context_after_chars: int = 900

    @property
    def selected_text(self) -> str:
        return self.document_text[self.selection.start : self.selection.end]

    def validate(self) -> None:
        if not self.document_text.strip():
            raise ValueError("document_text must not be empty")
        self.selection.validate(self.document_text)
        if not self.selected_text.strip():
            raise ValueError("selected text must not be whitespace")
        if not 0 <= self.strength <= 100:
            raise ValueError("strength must be in [0,100]")
        if not 1 <= self.requested_candidates <= 40:
            raise ValueError("requested_candidates must be in [1,40]")
        if self.target_min_words is not None and self.target_min_words < 1:
            raise ValueError("target_min_words must be >=1")
        if self.target_max_words is not None and self.target_max_words < 1:
            raise ValueError("target_max_words must be >=1")
        if self.target_min_words is not None and self.target_max_words is not None and self.target_min_words > self.target_max_words:
            raise ValueError("target_min_words cannot exceed target_max_words")
        if self.context_before_chars < 0 or self.context_after_chars < 0:
            raise ValueError("context windows must be non-negative")


@dataclass(frozen=True)
class Candidate:
    text: str
    lane: CandidateLane
    family: str
    generation_index: int
    model_id: str | None = None
    raw_score: float | None = None


@dataclass(frozen=True)
class CandidateBatch:
    request_id: str
    sequence: int
    candidates: tuple[Candidate, ...]
    cumulative_unique_count: int
    final: bool
    cancelled: bool = False


@dataclass(frozen=True)
class LanePlan:
    lane: CandidateLane
    candidate_budget: int
    max_new_tokens: int
    families: tuple[str, ...]
    temperature: float
    top_p: float


@dataclass(frozen=True)
class ExecutionPlan:
    request_id: str
    semantic_mode: SemanticMode
    fast: LanePlan
    diversity: LanePlan | None
    progressive_thresholds: tuple[int, ...]


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_MONEY_RE = re.compile(r"(?<!\w)\$\d+(?:,\d{3})*(?:\.\d{2})?")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s?(?:AM|PM|a\.m\.|p\.m\.)?\b", re.I)
_FILENAME_RE = re.compile(r"\b[\w.-]+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|json|md)\b", re.I)
_QUOTE_RE = re.compile(r"[“\"]([^”\"]+)[”\"]")


def detect_protected_spans(text: str) -> tuple[ProtectedSpan, ...]:
    """Cheap deterministic baseline; product safety can add richer extractors later."""
    matches: list[ProtectedSpan] = []
    for pattern in (_EMAIL_RE, _MONEY_RE, _TIME_RE, _FILENAME_RE, _QUOTE_RE):
        for match in pattern.finditer(text):
            matches.append(ProtectedSpan(match.group(0), match.start(), match.end()))
    seen: set[tuple[int | None, int | None, str]] = set()
    out: list[ProtectedSpan] = []
    for item in sorted(matches, key=lambda x: (x.start if x.start is not None else -1, -len(x.text))):
        key = (item.start, item.end, item.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return tuple(out)


def to_wire_request(request: StudioRequest) -> dict[str, Any]:
    request.validate()
    return {
        "version": 1,
        "requestId": request.request_id,
        "documentText": request.document_text,
        "selection": {"start": request.selection.start, "end": request.selection.end},
        "selectedText": request.selected_text,
        "operation": request.operation.value,
        "strength": request.strength,
        "requestedCandidates": request.requested_candidates,
        "targetMinWords": request.target_min_words,
        "targetMaxWords": request.target_max_words,
        "protectedSpans": [
            {"text": span.text, "start": span.start, "end": span.end}
            for span in request.protected_spans
        ],
    }
