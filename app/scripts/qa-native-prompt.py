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
assert_true("never invent a person, cause, amount, event, or outcome" in prompt, "Native prompt lacks the anti-invention constraint")
assert_true("A standalone fragment beginning with “Because of …”" in prompt, "Native prompt lacks standalone-fragment guidance")

deep_prompt = MODULE.build_instruction({
    "original_text": "Although the schedule was tight, the team completed the review because everyone shared the work.",
    "mode": "personal",
    "strength": 90,
    "protected_spans": [],
})
assert_true("deep structural paraphrase" in deep_prompt, "High Rewrite amount lacks deep structural guidance")
assert_true("sentence openings, clause order, and grammatical framing" in deep_prompt, "High Rewrite amount lacks sentence and clause restructuring guidance")
assert_true("instead of merely replacing isolated words" in deep_prompt, "High Rewrite amount still permits synonym-only rewriting")
assert_true("same sentence count" in deep_prompt, "High Rewrite amount dropped the sentence-count safeguard")

balanced_prompt = MODULE.build_instruction({
    "original_text": "The local editor helps writers review drafts.",
    "mode": "personal",
    "strength": 56,
    "protected_spans": [],
})
assert_true("deep structural paraphrase" not in balanced_prompt, "Balanced Rewrite amount received deep-only structural guidance")

empty_prompt = MODULE.build_instruction({"original_text": "A local draft.", "style_context": {}})
assert_true("Learned local style context:" not in empty_prompt, "Empty approval context added an unnecessary prompt block")

print("[qa:native-prompt] PASS")
