#!/usr/bin/env python3
"""Exercise the native prompt contract without loading the MLX checkpoint."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "native-runtime" / "paraphrase_worker.py"
SPEC = importlib.util.spec_from_file_location("pari_paraphrase_worker", WORKER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {WORKER}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


request = {
    "original_text": "The local editor helps writers review drafts.",
    "mode": "personal",
    "strength": 56,
    "protected_spans": [],
    "style_context": {
        "approvedExamples": [
            {
                "originalText": "The tool is useful.",
                "finalText": "The tool is helpful.",
            }
        ],
        "preferredReplacements": [
            {"original": "useful", "replacement": "helpful", "count": 2},
        ],
        "avoidedPhrases": ["utilize"],
        "preferredContractions": ["can't"],
        "sentencePreference": "similar",
    },
}

prompt = MODULE.build_instruction(request)
assert_true("The local editor helps writers review drafts." in prompt, "Current input was lost from the native prompt")
assert_true("The tool is helpful." in prompt, "Approved example was not included in the native prompt")
assert_true("useful -> helpful" in prompt, "Approved replacement preference was not included in the native prompt")
assert_true("do not copy their topic, names, numbers, links, dates, or claims" in prompt, "Native prompt lacks style-example fact isolation")
assert_true("utilize" in prompt and "can't" in prompt, "Avoided phrase or contraction preference was not included")
assert_true("usually approves sentence lengths that are similar" in prompt, "Sentence-shape preference was not included")

empty_prompt = MODULE.build_instruction({"original_text": "A local draft.", "style_context": {}})
assert_true("Learned local style context:" not in empty_prompt, "Empty approval context added an unnecessary prompt block")

print("[qa:native-prompt] PASS")
