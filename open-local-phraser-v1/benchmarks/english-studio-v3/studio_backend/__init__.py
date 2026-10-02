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
from .router import build_execution_plan

__all__ = [
    "Candidate",
    "CandidateBatch",
    "CandidateLane",
    "ExecutionPlan",
    "LanePlan",
    "Operation",
    "ProtectedSpan",
    "SemanticMode",
    "StudioRequest",
    "TextRange",
    "build_execution_plan",
]
