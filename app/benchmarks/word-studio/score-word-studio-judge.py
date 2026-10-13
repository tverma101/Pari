#!/usr/bin/env python3
"""Offline judge runner for Word Studio comparisons on Kaggle (Issue #73).

Evaluates candidate outputs through a two-stage process:
1. Hard rules in code:
   - protected content preserved (zero corruption);
   - non-empty and non-echoed source;
   - valid parsed list format and usable count;
   Candidates failing hard rules lose automatically without consulting the model.
2. Blinded judge model:
   - Strips model identities and randomizes A/B order;
   - Scores meaning preservation, grammatical fit, transform goal, and variety;
   - Fixed few-shot structured prompt.
3. Calibration verification against reference pairs (SWORDS, PAWS).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from word_studio_output_parser import diagnose  # noqa: E402
from word_studio_product_score import score_product_output  # noqa: E402


JUDGE_PROMPT_VERSION = 1
DEFAULT_JUDGE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

JUDGE_SYSTEM_PROMPT = """You are an expert impartial judge evaluating two candidate sets of alternative rewrites for a specific text selection within a paragraph.

You must evaluate four criteria:
1. Meaning preservation: does the rewrite preserve essential meaning without inventing facts?
2. Grammatical fit: does the rewrite integrate smoothly and grammatically into the context?
3. Transform goal: does the rewrite achieve the requested operation (e.g. simpler, shorter, more formal)?
4. Option variety: do the options offer genuine lexical/syntactic variety rather than trivial near-duplicates?

Output valid JSON with keys:
- "preferred": "A", "B", or "tie"
- "reason": concise explanation
- "score_A": integer 1-10
- "score_B": integer 1-10
"""

FEW_SHOT_EXAMPLES = [
    {
        "context": "The software is designed to streamline administrative overhead.",
        "selection": "streamline administrative overhead",
        "operation": "simpler",
        "candidates_A": ["reduce paperwork", "make office tasks easier", "cut down on busywork"],
        "candidates_B": ["streamline administrative overhead", "streamlining admin overhead", "streamlined administrative overhead"],
        "preferred": "A",
        "reason": "Candidate set A provides genuinely simpler alternatives with lexical variety. Candidate set B repeats the source with minor morphological shifts.",
        "score_A": 9,
        "score_B": 2,
    }
]


def evaluate_hard_rules(
    raw_output: str,
    *,
    source: str,
    requested: int = 10,
    protected: Sequence[Any] | None = None,
    route: str = "alternatives",
) -> dict[str, Any]:
    """Check deterministic hard rules. Returns pass/fail and diagnostics."""
    score = score_product_output(
        raw_output,
        requested=requested,
        source=source,
        protected=protected,
        route=route,
    )
    passed = bool(
        score["accepted"]
        and score["protectedContentCorruptionCount"] == 0
        and score["usableUniqueCount"] > 0
    )
    return {
        "passed": passed,
        "usableCount": score["usableUniqueCount"],
        "protectedCorruptions": score["protectedContentCorruptionCount"],
        "statuses": score["statuses"],
        "duplicateTaxonomy": score["duplicateTaxonomy"],
        "rawScore": score,
    }


def compare_hard_rules(
    eval_a: dict[str, Any],
    eval_b: dict[str, Any],
) -> dict[str, Any] | None:
    """If one candidate fails hard rules while the other passes, return definitive winner."""
    pass_a = eval_a["passed"]
    pass_b = eval_b["passed"]
    if pass_a and not pass_b:
        return {
            "decided_by": "hard_rules",
            "preferred": "A",
            "reason": f"Candidate B failed hard rules: {eval_b['statuses']}; Candidate A passed.",
            "score_A": 8,
            "score_B": 0,
        }
    if pass_b and not pass_a:
        return {
            "decided_by": "hard_rules",
            "preferred": "B",
            "reason": f"Candidate A failed hard rules: {eval_a['statuses']}; Candidate B passed.",
            "score_A": 0,
            "score_B": 8,
        }
    if not pass_a and not pass_b:
        # Both failed hard rules: compare usable count
        if eval_a["usableCount"] > eval_b["usableCount"]:
            return {
                "decided_by": "hard_rules_both_failed",
                "preferred": "A",
                "reason": f"Both candidates failed hard rules, but A had more usable options ({eval_a['usableCount']} vs {eval_b['usableCount']}).",
                "score_A": 3,
                "score_B": 1,
            }
        elif eval_b["usableCount"] > eval_a["usableCount"]:
            return {
                "decided_by": "hard_rules_both_failed",
                "preferred": "B",
                "reason": f"Both candidates failed hard rules, but B had more usable options ({eval_b['usableCount']} vs {eval_a['usableCount']}).",
                "score_A": 1,
                "score_B": 3,
            }
        return {
            "decided_by": "hard_rules_both_failed_tie",
            "preferred": "tie",
            "reason": "Both candidates failed hard rules equally.",
            "score_A": 1,
            "score_B": 1,
        }
    # Both passed hard rules -> proceed to model judge
    return None


def format_judge_prompt(
    context: str,
    selection: str,
    operation: str,
    options_a: Sequence[str],
    options_b: Sequence[str],
) -> str:
    """Build standardized, blinded prompt for the judge model."""
    body = {
        "task": {
            "context": context,
            "selection": selection,
            "operation": operation,
        },
        "candidate_set_A": list(options_a),
        "candidate_set_B": list(options_b),
    }
    return (
        f"{JUDGE_SYSTEM_PROMPT}\n\n"
        f"Example:\n{json.dumps(FEW_SHOT_EXAMPLES[0], indent=2)}\n\n"
        f"Evaluation Target:\n{json.dumps(body, indent=2)}\n\n"
        f"Your JSON verdict:"
    )


def blind_and_compare(
    task: Mapping[str, Any],
    cand_1_output: str,
    cand_2_output: str,
    *,
    seed: int = 42,
    model_evaluator: Any = None,
) -> dict[str, Any]:
    """Full evaluation of two outputs for one task with blinding and hard-rule checks."""
    protected = task.get("protectedSpans")
    # If protectedSpans has items, they are indexed against sourceText (paragraph context)
    source_context = str(task.get("sourceText") or task.get("paragraph") or "")
    selection = str(task.get("selectedText") or source_context)
    source = source_context if (protected and source_context) else selection
    context = str(task.get("paragraph") or task.get("sourceText") or source)
    operation = str(task.get("semanticMode") or task.get("operation") or "alternatives")
    requested = int(task.get("requestedCount") or 10)

    # 1. Evaluate hard rules for both
    eval_1 = evaluate_hard_rules(cand_1_output, source=source, requested=requested, protected=protected)
    eval_2 = evaluate_hard_rules(cand_2_output, source=source, requested=requested, protected=protected)

    # 2. Blinding: randomize assignment to A and B based on deterministic task hash
    task_hash = int(hashlib.sha256(f"{task.get('id', '')}-{seed}".encode()).hexdigest()[:8], 16)
    swap = (task_hash % 2) == 1

    eval_a = eval_2 if swap else eval_1
    eval_b = eval_1 if swap else eval_2
    cand_a_raw = cand_2_output if swap else cand_1_output
    cand_b_raw = cand_1_output if swap else cand_2_output

    # Check hard-rules shortcut
    hard_decision = compare_hard_rules(eval_a, eval_b)
    if hard_decision is not None:
        preferred = hard_decision["preferred"]
        # Map back from blinded A/B to candidate 1/2
        if preferred == "A":
            winner = 2 if swap else 1
        elif preferred == "B":
            winner = 1 if swap else 2
        else:
            winner = 0

        return {
            "decided_by": hard_decision["decided_by"],
            "winner": winner,
            "preferred_blinded": preferred,
            "swapped": swap,
            "reason": hard_decision["reason"],
            "score_cand1": hard_decision["score_B"] if swap else hard_decision["score_A"],
            "score_cand2": hard_decision["score_A"] if swap else hard_decision["score_B"],
            "eval_cand1": eval_1,
            "eval_cand2": eval_2,
        }

    # 3. Model judge
    diag_a = diagnose(cand_a_raw, source=source, requested=requested)
    diag_b = diagnose(cand_b_raw, source=source, requested=requested)
    prompt = format_judge_prompt(context, selection, operation, diag_a["options"], diag_b["options"])

    if model_evaluator is not None:
        model_result = model_evaluator(prompt)
    else:
        # Default deterministic heuristic if no LLM worker is attached
        options_a_len = len(diag_a["options"])
        options_b_len = len(diag_b["options"])
        if options_a_len > options_b_len:
            model_result = {"preferred": "A", "reason": "Candidate set A provided more options.", "score_A": 8, "score_B": 6}
        elif options_b_len > options_a_len:
            model_result = {"preferred": "B", "reason": "Candidate set B provided more options.", "score_B": 8, "score_A": 6}
        else:
            model_result = {"preferred": "tie", "reason": "Candidates had equal usable candidate depth and passed hard rules.", "score_A": 7, "score_B": 7}

    preferred = model_result.get("preferred", "tie")
    if preferred == "A":
        winner = 2 if swap else 1
    elif preferred == "B":
        winner = 1 if swap else 2
    else:
        winner = 0

    return {
        "decided_by": "judge_model",
        "winner": winner,
        "preferred_blinded": preferred,
        "swapped": swap,
        "reason": model_result.get("reason", ""),
        "score_cand1": model_result.get("score_B" if swap else "score_A", 5),
        "score_cand2": model_result.get("score_A" if swap else "score_B", 5),
        "eval_cand1": eval_1,
        "eval_cand2": eval_2,
        "judge_prompt": prompt,
    }


def calibrate_judge_on_pairs(pairs: Sequence[Mapping[str, Any]], evaluator: Any = None) -> dict[str, Any]:
    """Test judge discrimination against pairs with known human preference (e.g. SWORDS/PAWS)."""
    correct = 0
    total = len(pairs)
    results = []
    for pair in pairs:
        task = {
            "id": pair.get("id", "calib"),
            "sourceText": pair["source"],
            "selectedText": pair.get("selection", pair["source"]),
            "requestedCount": 1,
            "operation": pair.get("operation", "alternatives"),
        }
        good_output = json.dumps([pair["good_candidate"]])
        bad_output = json.dumps([pair["bad_candidate"]])
        res = blind_and_compare(task, good_output, bad_output, model_evaluator=evaluator)
        is_correct = (res["winner"] == 1)
        if is_correct:
            correct += 1
        results.append({
            "id": pair.get("id"),
            "correct": is_correct,
            "winner": res["winner"],
            "decided_by": res["decided_by"],
            "reason": res["reason"],
        })

    accuracy = correct / total if total > 0 else 0.0
    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "calibrated": accuracy >= 0.8,
        "details": results,
    }
