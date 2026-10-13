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
from .engine import LaneAdapter, LaneResult, StudioEngine
from .errors import ClientErrorCode, ModelBackendError
from .progressive import CandidateAccumulator
from .prompting import CompiledPrompt, compile_prompt, parse_prompt_payload, serialize_prompt_payload
from .router import build_execution_plan
from .safety import candidate_preserves_protected_content, filter_protected_candidates
from .service_limits import ServiceLimits, studio_request_from_wire

__all__ = [
    "Candidate",
    "CandidateAccumulator",
    "CandidateBatch",
    "CandidateLane",
    "ClientErrorCode",
    "CompiledPrompt",
    "ExecutionPlan",
    "LaneAdapter",
    "LanePlan",
    "LaneResult",
    "ModelBackendError",
    "Operation",
    "ProtectedSpan",
    "SemanticMode",
    "ServiceLimits",
    "StudioEngine",
    "StudioRequest",
    "TextRange",
    "build_execution_plan",
    "candidate_preserves_protected_content",
    "compile_prompt",
    "filter_protected_candidates",
    "parse_prompt_payload",
    "serialize_prompt_payload",
    "studio_request_from_wire",
]
