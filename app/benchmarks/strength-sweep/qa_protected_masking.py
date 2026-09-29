#!/usr/bin/env python3
"""Model-free regression for overlapping protected spans in the MLX worker."""

from __future__ import annotations

import importlib.util
from pathlib import Path


WORKER_PATH = Path(__file__).resolve().parents[2] / "native-runtime" / "paraphrase_worker.py"
spec = importlib.util.spec_from_file_location("pari_worker_masking_qa", WORKER_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("Could not load the native worker module.")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def check_overlapping_dates_and_numbers() -> None:
    request = {
        "original_text": (
            "Mina sent the report on May 3, and Theo replied on May 10. "
            "Of 43 invited staff, 31 responded; 19 supported the proposal and 12 opposed it. "
            "The report does not show whether the 12 absent staff support it, and the team should not "
            "call the 19 a majority."
        ),
        # These overlaps are produced by the app's date-plus-number extraction.
        "protected_spans": [
            "May 3",
            "3",
            "May 10",
            "10",
            "43",
            "31",
            "19",
            "12",
            "Mina",
            "Theo",
            "not",
            "should",
        ],
        "mode": "personal",
    }
    candidate = (
        "Mina sent the report on May 3, and Theo replied on May 10. "
        "Out of 43 invited staff, 31 responded; 19 supported the proposal, while 12 opposed it. "
        "It does not show whether the 12 absent staff support it, and the team should not call the "
        "19 respondents a majority."
    )
    result = worker.postprocess(candidate, request)
    assert "\ue000" not in result and "\ue001" not in result, repr(result)
    for span in request["protected_spans"]:
        assert span in result, "Protected span was lost: " + span + " in " + result


def check_many_spans_and_warmth() -> None:
    protected = ["no", "will"] + ["protected-anchor-" + str(index) for index in range(12)]
    request = {
        "original_text": "No further assistance will be provided until the review is complete.",
        "protected_spans": protected,
        "mode": "warmth",
    }
    result = worker.warmth_polish(
        "No further assistance will be provided until the review is complete.",
        request,
    )
    assert "\ue000" not in result and "\ue001" not in result, repr(result)
    assert "No" in result and "will" in result, repr(result)


check_overlapping_dates_and_numbers()
check_many_spans_and_warmth()
print("[qa:protected-masking] overlapping anchors and multi-span warmth checks passed")
