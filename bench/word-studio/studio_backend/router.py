#!/usr/bin/env python3
"""Deterministic operation router for a two-T4 Pari Studio backend."""
from __future__ import annotations

from .contracts import CandidateLane, ExecutionPlan, LanePlan, Operation, SemanticMode, StudioRequest


def semantic_mode_for(operation: Operation) -> SemanticMode:
    if operation == Operation.COMPRESS_GIST:
        return SemanticMode.INTENTIONAL_COMPRESSION
    if operation == Operation.EXPAND:
        return SemanticMode.CONTROLLED_EXPANSION
    return SemanticMode.FULL_PRESERVATION


def families_for(operation: Operation, lane: CandidateLane) -> tuple[str, ...]:
    conservative = {
        Operation.REWRITE: ("natural_rewrite", "syntax_recast", "concise_rewrite"),
        Operation.REPLACE: ("contextual_equivalent", "short_phrase", "lexical_variant"),
        Operation.SHORTEN: ("concise_equivalent", "compression"),
        Operation.EXPAND: ("explicit_equivalent", "natural_expansion"),
        Operation.COMPRESS_GIST: ("gist_label", "compact_concept"),
        Operation.SPLIT: ("two_sentence_split", "clause_split"),
        Operation.JOIN: ("sentence_join", "compact_join"),
        Operation.SIMPLIFY: ("common_vocabulary", "direct_structure"),
        Operation.DIFFERENT_STRUCTURE: ("syntax_recast", "voice_preserving_reorder"),
        Operation.PRESERVE_REGISTER: ("same_register", "same_intensity"),
    }
    exploratory = {
        Operation.REWRITE: ("different_opening", "clause_reorder", "compression", "expansion"),
        Operation.REPLACE: ("word_to_phrase", "phrase_to_word", "different_length", "idiomatic_variant"),
        Operation.SHORTEN: ("phrase_to_word", "clause_compression", "minimal_form"),
        Operation.EXPAND: ("word_to_phrase", "clarifying_structure", "clause_expansion"),
        Operation.COMPRESS_GIST: ("one_word_gist", "two_word_gist", "three_word_gist", "alternate_abstraction"),
        Operation.SPLIT: ("two_sentence_split", "three_part_split", "different_boundary"),
        Operation.JOIN: ("single_sentence_join", "subordinate_join", "coordination_join"),
        Operation.SIMPLIFY: ("common_vocabulary", "shorter_syntax", "direct_rephrase"),
        Operation.DIFFERENT_STRUCTURE: ("fronted_clause", "reordered_clause", "split_or_join", "different_subject_opening"),
        # Register-preserving routes must never request a register change. A
        # "casual_variant" family silently contradicts the PRESERVE_REGISTER
        # operation prompt for formal/technical/emotional sources, so the
        # diversity lane asks for same-register variation instead.
        Operation.PRESERVE_REGISTER: (
            "same_register_lexical_variant",
            "same_intensity",
            "different_length_same_voice",
        ),
    }
    return (conservative if lane == CandidateLane.FAST else exploratory)[operation]


def build_execution_plan(request: StudioRequest) -> ExecutionPlan:
    request.validate()
    requested = request.requested_candidates
    fast_budget = min(requested, max(5, min(12, requested // 2 + 2)))
    diversity_budget = max(0, requested - fast_budget)

    fast = LanePlan(
        lane=CandidateLane.FAST,
        candidate_budget=fast_budget,
        max_new_tokens=420 if request.operation in {Operation.REWRITE, Operation.EXPAND, Operation.SPLIT, Operation.JOIN} else 260,
        families=families_for(request.operation, CandidateLane.FAST),
        temperature=0.35,
        top_p=0.9,
    )
    diversity = None
    if diversity_budget:
        diversity = LanePlan(
            lane=CandidateLane.DIVERSITY,
            candidate_budget=diversity_budget,
            max_new_tokens=640 if request.operation in {Operation.REWRITE, Operation.EXPAND, Operation.SPLIT, Operation.JOIN} else 360,
            families=families_for(request.operation, CandidateLane.DIVERSITY),
            temperature=0.75,
            top_p=0.95,
        )

    thresholds = tuple(dict.fromkeys(x for x in (3, 10, requested) if x <= requested))
    return ExecutionPlan(
        request_id=request.request_id,
        semantic_mode=semantic_mode_for(request.operation),
        fast=fast,
        diversity=diversity,
        progressive_thresholds=thresholds,
    )
