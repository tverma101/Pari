#!/usr/bin/env python3
"""Canonical Word Studio parser adapter used by the live Studio service.

The benchmark parser is the single authority for parser modes and usable
candidate admission. This module keeps the small adapter surface used by the
service without forking that contract.
"""
from __future__ import annotations

from typing import Any

from word_studio_output_parser import (  # type: ignore[import-not-found]
    PARSER_VERSION,
    CandidateLedger,
    parse_document,
)


def parse_document_details(raw: str) -> dict[str, Any]:
    document = parse_document(raw)
    return {
        "parserVersion": PARSER_VERSION,
        "parserMode": document.mode,
        "parsedCount": len(document.options),
        "invalidEntryCount": len(document.invalid_entries),
        "invalidEntryTypes": document.invalid_entry_types,
        "codeFenced": document.fenced,
        "leadingProse": document.leading_prose,
        "trailingProse": document.trailing_prose,
        "commentaryMixed": document.commentary_mixed,
        "jsonWrongKeys": list(document.wrong_json_keys),
    }


def parse_options(raw: str) -> tuple[list[str], str]:
    document = parse_document(raw)
    return list(document.options), document.mode


__all__ = [
    "CandidateLedger",
    "PARSER_VERSION",
    "parse_document",
    "parse_document_details",
    "parse_options",
]
