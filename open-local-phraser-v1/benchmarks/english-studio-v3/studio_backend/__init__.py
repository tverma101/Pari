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
from .progressive import CandidateAccumulator
from .prompting import CompiledPrompt, compile_prompt
from .router import build_execution_plan

__all__ = [
    "Candidate",
    "CandidateAccumulator",
    "CandidateBatch",
    "CandidateLane",
    "CompiledPrompt",
    "ExecutionPlan",
    "LanePlan",
    "Operation",
    "ProtectedSpan",
    "SemanticMode",
    "StudioRequest",
    "TextRange",
    "build_execution_plan",
    "compile_prompt",
]
