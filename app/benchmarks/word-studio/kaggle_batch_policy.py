#!/usr/bin/env python3
"""Shared batch/ladder policy for every canonical benchmark wrapper (Issue #47).

Load feasibility and batch feasibility are separate states. A batch number is a
generation-side parameter, so it can never make a model *load* succeed, and a
load failure must not walk the ladder reloading an identical failing model.

This module is the single source of truth for:

* the canonical English-screen fallback ladder;
* the separate product-stage single-batch policy;
* the bounded transient same-config retry allowance;
* ``decide_after_attempt``, which maps one attempt outcome to exactly one next
  action so every wrapper shares the same retry taxonomy.

Both wrappers keep their own semantics for what the number *means* (vLLM
``max_num_seqs`` versus client request concurrency) and record that explicitly,
but they share the ladder and the decision rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The one canonical English-screen fallback ladder, frozen before any candidate
#: result was observed. 64 is deliberately omitted: at the frozen context bound,
#: 64 concurrent sequences exceed the 16 GB T4 budget for every roster
#: candidate, so the first rung would cost an extra load for no information.
CANONICAL_LADDER: tuple[int, ...] = (32, 16, 8, 4, 1)

#: Product stages are pinned to a single batch and never traverse the ladder.
PRODUCT_BATCH_POLICY: tuple[int, ...] = (1,)

PRODUCT_STAGES: frozenset[str] = frozenset({"word-studio", "transform"})

#: Transient allocator/runtime faults eligible for one exact-config retry after
#: cleanup. This is explicitly NOT a batch step-down: every frozen setting stays
#: identical and both attempts remain in the record.
TRANSIENT_RETRY_CATEGORIES: frozenset[str] = frozenset({
    "cuda_memory_fragmentation",
    "runtime_crash",
})

MAX_TRANSIENT_RETRIES: int = 1

#: What each decision action means, for receipts and documentation.
ACTION_MEANINGS: dict[str, str] = {
    "complete": "attempt succeeded; this batch is the stable serving evidence",
    "step_down_batch": "generation-capacity failure; reduce the batch per the frozen ladder",
    "stop_load_capacity": "load-capacity failure; stop this configuration, do not change batch",
    "stop_generation_capacity": "generation-capacity failure at batch 1; ladder exhausted",
    "retry_same_config": "transient fault; retry the identical frozen configuration once",
    "stop_runtime_failure": "deterministic non-OOM failure; stop immediately",
}

#: Which terminal summary field each stop action maps onto, so #28/#34 can tell
#: load capacity from generation capacity.
FAILURE_CLASS_BY_ACTION: dict[str, str] = {
    "stop_load_capacity": "load_capacity",
    "stop_generation_capacity": "generation_capacity",
    "stop_runtime_failure": "runtime_failure",
}


@dataclass(frozen=True)
class AttemptDecision:
    """What the wrapper must do after one batch attempt."""

    action: str
    reason: str
    oom_class: str | None = None
    transient_retry: bool = False

    @property
    def failure_class(self) -> str | None:
        return FAILURE_CLASS_BY_ACTION.get(self.action)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "oomClass": self.oom_class,
            "transientRetry": self.transient_retry,
            "failureClass": self.failure_class,
        }


def classify_oom(categories: list[str]) -> str | None:
    """Split an OOM category list into load vs generation capacity."""
    if "cuda_oom_load" in categories:
        return "load"
    if "cuda_oom_generate" in categories:
        return "generate"
    return None


def decide_after_attempt(
    *,
    returncode: int,
    categories: list[str],
    batch: int,
    transient_retries_used: int,
    parameter_name: str = "batch",
) -> AttemptDecision:
    """Classify one attempt outcome into exactly one next action.

    ``parameter_name`` only changes the wording of the recorded reason. The
    decision rules are identical across wrappers, so a load OOM can never
    trigger a meaningless parameter walk anywhere.
    """
    if returncode == 0:
        return AttemptDecision("complete", "child exited 0", oom_class=None)

    oom_class = classify_oom(list(categories))
    if oom_class == "load":
        return AttemptDecision(
            "stop_load_capacity",
            (
                "model load OOM at " + str(parameter_name) + " " + str(batch) + "; "
                + parameter_name + " does not affect model construction, so this frozen "
                "configuration is not feasible. A configuration-level fallback (for "
                "example an explicitly roster-declared TP2 candidate) is required instead."
            ),
            oom_class="load",
        )

    if oom_class == "generate":
        if batch == 1:
            return AttemptDecision(
                "stop_generation_capacity",
                (
                    "generation OOM at batch 1; the frozen ladder is exhausted, so this "
                    "frozen model configuration cannot run on this GPU"
                ),
                oom_class="generate",
            )
        return AttemptDecision(
            "step_down_batch",
            (
                "generation OOM at " + str(parameter_name) + " " + str(batch) + "; step "
                "down the frozen canonical ladder " + str(list(CANONICAL_LADDER))
            ),
            oom_class="generate",
        )

    if (
        set(categories) & TRANSIENT_RETRY_CATEGORIES
        and transient_retries_used < MAX_TRANSIENT_RETRIES
    ):
        return AttemptDecision(
            "retry_same_config",
            (
                "transient allocator/runtime fault at " + str(parameter_name) + " "
                + str(batch) + "; retry the identical frozen configuration once after "
                "cleanup (not a step-down)"
            ),
            oom_class=None,
            transient_retry=True,
        )

    return AttemptDecision(
        "stop_runtime_failure",
        "non-OOM runtime failure at " + str(parameter_name) + " " + str(batch) + ": "
        + str(list(categories)),
        oom_class=None,
    )


def ladder_for(stage: str, *, override: tuple[int, ...] | None = None) -> tuple[int, ...]:
    """The frozen ladder a stage may traverse. Product stages never traverse one."""
    if stage in PRODUCT_STAGES:
        return PRODUCT_BATCH_POLICY
    return CANONICAL_LADDER if override is None else override
