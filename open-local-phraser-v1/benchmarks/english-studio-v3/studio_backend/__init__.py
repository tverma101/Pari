"""Model-agnostic Pari Word Studio backend primitives."""

from .contracts import (
    Candidate,
    CandidateBatch,
    CandidateLane,
    ExecutionPlan,
    LanePlan,
    Operation,
    ProtectedSpan,
    SemanticMode,
    StudioRequest,
    TextRange,
)
from .engine import LaneAdapter, StudioEngine
from .progressive import CandidateAccumulator
from .prompting import CompiledPrompt, compile_prompt
from .router import build_execution_plan
from .safety import candidate_preserves_protected_content, filter_protected_candidates

__all__ = [
    "Candidate",
    "CandidateAccumulator",
    "CandidateBatch",
    "CandidateLane",
    "CompiledPrompt",
    "ExecutionPlan",
    "LaneAdapter",
    "LanePlan",
    "Operation",
    "ProtectedSpan",
    "SemanticMode",
    "StudioEngine",
    "StudioRequest",
    "TextRange",
    "build_execution_plan",
    "candidate_preserves_protected_content",
    "compile_prompt",
    "filter_protected_candidates",
]
