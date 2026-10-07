#!/usr/bin/env python3
"""Deterministic blinded human/product evaluation pipeline (issue #69).

One module owns the whole frozen chain so no step can drift from another:

1. **Load and verify provenance.** Every task file, every finalist result and
   the usable-candidate parser are bound by exact SHA-256. Mixed
   task/parser/result identities are refused, never silently merged.
2. **Preregister.** A deterministic manifest freezes compared configs, task
   IDs/routes/semantic modes, output artifact hashes, criteria wording, pair
   policy, randomization seed, candidate-depth policy, rater rules, minimum
   annotations, tie/both-unacceptable policy, the primary analysis plan and the
   disagreement/adjudication policy. Finalist identities live *only* in a
   separately hashed private mapping; the preregistration stores that mapping's
   digest and count.
3. **Blind and randomize.** Per-rater packets expose source context, criteria
   wording, opaque item IDs and anonymous sides ``A``/``B``. A/B side is
   balanced and randomized independently per comparison, item order is
   randomized, and a structural + lexical scan proves no model, runtime,
   latency, size, revision or private author-expectation text leaked.
4. **Validate ratings.** A strict schema rejects unknown IDs, duplicate
   rater/pair/criterion rows, outdated packet digests, impossible labels,
   missing required criteria and any accidental exposure of the private
   mapping inside reviewer data.
5. **Analyze.** Criterion-specific paired analysis keeps ties and
   both-unacceptable as first-class outcomes, reports disagreement and
   reliability with stated assumptions, gives deterministic bootstrap
   uncertainty, reconstructs top-k useful-candidate coverage, traces
   per-source strength trajectories, lists exact exclusions, and reveals the
   blinded mapping only as the last step.

This module never contacts a model or a network, never uploads a packet and
never scores quality itself. Rater labels are the only product-quality
evidence; everything here is the machinery that makes those labels auditable.

Synthetic local fixtures only until real raters run (see
``WORD_STUDIO_HUMAN_EVAL_PIPELINE.md``).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import re
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import word_studio_output_parser as parser  # noqa: E402  (path bootstrap above)

#: Alphanumeric runs in the lowercased payload, used for boundary-safe runtime
#: token matching so ordinary prose ("output") cannot trip the scan.
_WORD_RE = re.compile(r"[a-z0-9]+")

# ---------------------------------------------------------------------------
# Frozen protocol identity

#: Bumped only when the packet *shape* changes. Rating/analysis semantics carry
#: their own versions so an old rating document can never be reinterpreted.
PACKET_SCHEMA_VERSION = 1
PREREGISTRATION_SCHEMA_VERSION = 1
RATING_SCHEMA_VERSION = 1
ANALYSIS_SCHEMA_VERSION = 1
MAPPING_SCHEMA_VERSION = 1

#: Human-evaluation protocol document whose bytes define the methodology this
#: pipeline implements. The builder binds its digest into the preregistration.
PROTOCOL_RELATIVE_PATH = "ENGLISH_CORE_HUMAN_EVAL.md"

SEMANTIC_MODE_PRESERVE = "preserve_full_selected_meaning"
SEMANTIC_MODE_COMPRESSION = "intentional_compression"

#: The first-class outcomes. ``tie`` and ``both_unacceptable`` are never folded
#: into a winner; see :func:`directional_score`.
PAIRWISE_LABELS = ("A", "B", "tie", "both_unacceptable")
CANDIDATE_LABELS = ("usable", "not_usable", "unclear")
STRENGTH_BOOLEAN_LABELS = ("yes", "no", "unclear")
STRENGTH_LEVELS = (15, 40, 60, 90)

CRITERION_MEANING = "meaning_preservation"
CRITERION_NATURALNESS = "contextual_naturalness"
CRITERION_REGISTER = "register_preservation"
CRITERION_USEFULNESS = "edit_usefulness"
CRITERION_DIVERSITY = "structural_lexical_diversity"
CRITERION_INFLATION = "unnecessary_inflation"
CRITERION_PROTECTED = "protected_content_correctness"
CRITERION_COMPRESSION = "compression_quality"

#: Criterion wording is frozen here, not in the packet builder, so the packet,
#: the rating schema and the preregistration can never disagree about what a
#: reviewer was asked.
CRITERIA: dict[str, dict[str, Any]] = {
    CRITERION_MEANING: {
        "wording": (
            "Meaning and fact preservation: facts, actors, roles, negation, "
            "modality, quantities, conditions, comparisons, causality and "
            "discourse relations all survive. No invented evidence or claims."
        ),
        "decisionRule": (
            "Only ask this on routes whose contract is full-meaning preservation. "
            "Intentional compression is judged by compression_quality instead."
        ),
        "appliesToSemanticModes": [SEMANTIC_MODE_PRESERVE],
    },
    CRITERION_NATURALNESS: {
        "wording": (
            "Contextual naturalness: fluent, idiomatic English that reads correctly "
            "inside the given source context, as a native or highly proficient "
            "editor would write it."
        ),
        "decisionRule": "Applies to every route.",
        "appliesToSemanticModes": [SEMANTIC_MODE_PRESERVE, SEMANTIC_MODE_COMPRESSION],
    },
    CRITERION_REGISTER: {
        "wording": (
            "Register and intensity preservation: the formality, politeness, voice "
            "and claim strength of the source survive unless the operation "
            "explicitly requested a change."
        ),
        "decisionRule": (
            "Applies to every route. On intentional compression, judged as "
            "gist-faithfulness rather than verbatim register fidelity."
        ),
        "appliesToSemanticModes": [SEMANTIC_MODE_PRESERVE, SEMANTIC_MODE_COMPRESSION],
    },
    CRITERION_USEFULNESS: {
        "wording": (
            "Edit usefulness: the output is a genuinely usable alternative, not a "
            "near-duplicate, cosmetic variant or irrelevant variation."
        ),
        "decisionRule": "Applies to every route.",
        "appliesToSemanticModes": [SEMANTIC_MODE_PRESERVE, SEMANTIC_MODE_COMPRESSION],
    },
    CRITERION_DIVERSITY: {
        "wording": (
            "Structural and lexical diversity: the candidate set offers materially "
            "different wording or structure rather than cosmetic variants of one idea."
        ),
        "decisionRule": (
            "Compare the sets as shown. Judge one side when only one side offers "
            "materially varied options."
        ),
        "appliesToSemanticModes": [SEMANTIC_MODE_PRESERVE, SEMANTIC_MODE_COMPRESSION],
    },
    CRITERION_INFLATION: {
        "wording": (
            "Unnecessary inflation: the output avoids gratuitous length, abstraction, "
            "formality, rare vocabulary or padding."
        ),
        "decisionRule": "Applies to every route.",
        "appliesToSemanticModes": [SEMANTIC_MODE_PRESERVE, SEMANTIC_MODE_COMPRESSION],
    },
    CRITERION_PROTECTED: {
        "wording": (
            "Protected-content and local-edit correctness: names, numbers, dates, "
            "filenames, quotes and other protected context outside the selection are "
            "untouched, and only the selected span is replaced."
        ),
        "decisionRule": (
            "Asked only where the task declares protected content or a "
            "protected-context operation."
        ),
        "appliesToSemanticModes": [SEMANTIC_MODE_PRESERVE, SEMANTIC_MODE_COMPRESSION],
    },
    CRITERION_COMPRESSION: {
        "wording": (
            "Intentional-compression quality: the gist label captures the central "
            "idea faithfully without inventing a new claim. Detail loss is "
            "intentional and is NOT scored as paraphrase loss."
        ),
        "decisionRule": (
            "Replaces meaning_preservation on intentional_compression routes. Strict "
            "full-paraphrase equivalence must never be applied here."
        ),
        "appliesToSemanticModes": [SEMANTIC_MODE_COMPRESSION],
    },
}

#: The every-route floor. ``structural_lexical_diversity`` is included because
#: the packet always shows an ordered candidate set per side.
_BASE_CRITERIA = (
    CRITERION_NATURALNESS,
    CRITERION_REGISTER,
    CRITERION_USEFULNESS,
    CRITERION_DIVERSITY,
    CRITERION_INFLATION,
)

#: Field names that must never appear in a reviewer-visible packet. Structural
#: check, independent of any value scan. ``candidateId`` is deliberately absent:
#: the finalist/config identifier is spelled ``finalistId`` everywhere in this
#: module, so the reviewer's per-side ordinal cannot collide with it.
FORBIDDEN_PACKET_KEYS = frozenset(
    {
        "model",
        "modelId",
        "model_id",
        "candidate_id",
        "configId",
        "config_id",
        "systemId",
        "system_id",
        "systemKey",
        "finalistId",
        "finalist_id",
        "revision",
        "modelRevision",
        "repo",
        "checkpoint",
        "quantization",
        "dtype",
        "tensorParallelSize",
        "runtime",
        "hardware",
        "gpu",
        "accelerator",
        "endpoint",
        "latencySeconds",
        "firstTokenLatencySeconds",
        "firstCandidateLatencySeconds",
        "firstThreeCandidatesLatencySeconds",
        "firstTenCandidatesLatencySeconds",
        "ttft",
        "usage",
        "taskFile",
        "resultPath",
        "expectations",
        "authorExpectations",
        "reviewKey",
        "privateReviewKey",
        "goldHint",
    }
)

#: Tokens that indicate runtime/identity metadata leaked into a packet. Matched
#: on alphanumeric word boundaries so ordinary English prose in source text
#: ("output", "input") cannot raise a false positive.
FORBIDDEN_PACKET_TOKENS = (
    "vllm",
    "llama.cpp",
    "llamacpp",
    "mlx",
    "kaggle",
    "huggingface",
    "hugging face",
    "transformers",
    "tensorparallel",
    "tensor-parallel",
    "cuda",
    "nvidia",
    "tpu",
    "gguf",
    "safetensors",
    "openai",
    "ollama",
    "q4_0",
    "q4_k",
    "q8_0",
)

DEFAULT_DEPTHS = (3, 5, 10)
DEFAULT_MIN_ANNOTATIONS_PER_ITEM = 2
DEFAULT_RATERS = ("r-alpha", "r-beta", "r-gamma")


class HumanEvalContractError(ValueError):
    """Raised when a provenance, blinding or rating contract is violated."""


# ---------------------------------------------------------------------------
# Canonical bytes, hashing, atomic writes


def canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, no incidental whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def document_bytes(value: Any) -> bytes:
    """Reviewer/report file bytes: canonical ordering, human-readable."""
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_object(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def atomic_write(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _derive_int(seed: str, *parts: str) -> int:
    """Stable integer derived from the frozen seed and a label path."""
    message = "|".join(parts).encode("utf-8")
    digest = hmac.new(seed.encode("utf-8"), message, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def _rng(seed: str, *parts: str) -> random.Random:
    return random.Random(_derive_int(seed, *parts))


def _opaque_id(prefix: str, seed: str, *parts: str) -> str:
    """Stable opaque identifier that leaks no ordering or identity."""
    token = hmac.new(seed.encode("utf-8"), "|".join(parts).encode("utf-8"), hashlib.sha256)
    return f"{prefix}-{token.hexdigest()[:12]}"


# ---------------------------------------------------------------------------
# Rubric / policy constants exposed to the preregistration


def rubric_definition() -> dict[str, Any]:
    """The frozen rubric the packets, schema and preregistration all share."""
    return {
        "rubricVersion": 1,
        "pairwiseLabels": list(PAIRWISE_LABELS),
        "candidateLabels": list(CANDIDATE_LABELS),
        "strengthLabels": list(STRENGTH_BOOLEAN_LABELS),
        "strengthLevels": list(STRENGTH_LEVELS),
        "semanticModes": {
            SEMANTIC_MODE_PRESERVE: (
                "Full-meaning preservation routes. meaning_preservation is the "
                "primary semantic criterion."
            ),
            SEMANTIC_MODE_COMPRESSION: (
                "Intentional semantic compression. compression_quality replaces "
                "meaning_preservation; strict full-paraphrase equivalence must never "
                "be applied to these items."
            ),
        },
        "criteria": CRITERIA,
    }


RUBRIC = rubric_definition()


def default_policies(depths: Sequence[int] = DEFAULT_DEPTHS) -> dict[str, Any]:
    """Frozen analysis/adjudication policy. Changing any field is a new version."""
    return {
        "pairGenerationPolicy": {
            "unit": "one blinded comparison per (task, finalist pair)",
            "pairing": "deterministic all-pairs round robin over the frozen finalist order",
            "sideAssignment": (
                "balanced then shuffled; |A-side count - B-side count| <= 1 per system"
            ),
            "itemOrder": "shuffled per rater from the frozen seed",
            "candidateOrder": "model-produced order preserved; top-k coverage reconstructed by prefix",
            "labelsPreserved": list(PAIRWISE_LABELS),
        },
        "candidateDepthPolicy": {
            "depthsShown": sorted(int(x) for x in depths),
            "maxDepthShown": max(int(x) for x in depths),
            "coverageRule": (
                "useful depth at k = count of leading candidates marked usable, capped "
                "at k; reconstruction uses prefix order only"
            ),
        },
        "raterEligibilityPolicy": {
            "anonymousRaterIds": True,
            "personallyIdentifyingInfoRequired": False,
            "minimumProficiency": (
                "strong English proficiency, recorded outside benchmark artifacts"
            ),
            "requiredAnnotationsPerItem": DEFAULT_MIN_ANNOTATIONS_PER_ITEM,
            "distinctRatersPerItem": DEFAULT_MIN_ANNOTATIONS_PER_ITEM,
            "preregisteredExclusionRules": [
                {
                    "id": "incomplete",
                    "rule": "rating document omits a required criterion for any assigned item",
                },
                {
                    "id": "stale-packet",
                    "rule": "packet digest does not match the frozen packet for that rater",
                },
                {
                    "id": "unknown-id",
                    "rule": "rating references an item or side not present in the frozen packet",
                },
            ],
        },
        "primaryAnalysisPlan": {
            "unit": "rater x comparison x criterion annotation",
            "directionalScore": {"A": 1, "B": -1, "tie": 0},
            "bothUnacceptable": "reported as its own count; excluded from the directional mean",
            "uncertainty": "deterministic seeded percentile bootstrap over annotations",
            "reliability": (
                "percent agreement and Fleiss kappa (nominal, no chance correction "
                "assumed) over raters sharing an item; reported with assumptions"
            ),
            "disagreement": "per-item label divergence rate plus highest-divergence item IDs",
            "multiplicity": "no p-value thresholding; intervals are descriptive, not a ranking test",
            "collapsedScalar": "forbidden; no universal winner or opaque product scalar is produced",
        },
        "disagreementAdjudicationPolicy": {
            "objectiveItems": (
                "grammar/meaning/identity disagreements are evidence the item or "
                "instructions are unclear; review the item without model results"
            ),
            "subjectiveItems": (
                "quality disagreements may be legitimate preference; never force "
                "consensus and never average them into a single adjudicated score"
            ),
            "frozenJudgments": "independent judgments are frozen before any adjudication",
            "postHocExclusions": (
                "an exclusion without a preregistered rule id is reported as "
                "exploratory, never silently accepted"
            ),
        },
        "authorExpectationPolicy": {
            "default": "not_used",
            "allowedModes": ["not_used", "reviewer_checklist"],
            "reviewerChecklist": (
                "When explicitly preregistered, author requirements may appear in the "
                "packet only as reviewer checklist text. They are never model input, "
                "never presented as validated gold, and independent rater responses stay "
                "separately recorded."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Input loading and provenance verification


@dataclass(frozen=True)
class TaskArtifact:
    path: Path
    sha256: str
    suite: str
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SystemArtifact:
    """One finalist/config's qualified raw-output artifact for one task file."""

    system_id: str
    label: str
    revision: str | None
    result_path: Path
    result_sha256: str
    task_file_sha256: str
    outputs: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Inputs:
    tasks_by_file: dict[str, TaskArtifact]
    task_index: dict[str, dict[str, Any]]
    task_file_key: dict[str, str]
    systems: list[SystemArtifact]
    parser_sha256: str
    parser_version: int
    protocol_sha256: str
    rubric_sha256: str
    protocol_path: Path


def _read_tasks(path: Path) -> tuple[dict[str, Any], ...]:
    text = Path(path).read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HumanEvalContractError(f"{path}:{line_number}: task row is not JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise HumanEvalContractError(f"{path}:{line_number}: task row must be an object")
        task_id = row.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise HumanEvalContractError(
                f"{path}:{line_number}: task row requires a non-empty string id"
            )
        rows.append(row)
    if not rows:
        raise HumanEvalContractError(f"{path}: task file is empty")
    return tuple(rows)


def _manifest_suite(path: Path) -> str:
    for candidate in (
        path.parent / f"{Path(path).stem}.manifest.json",
        path.with_suffix("").with_suffix(".manifest.json"),
    ):
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            suite = data.get("suite")
            if isinstance(suite, str) and suite:
                return suite
    return Path(path).stem


def load_task_artifact(path: Path, expected_sha256: str | None = None) -> TaskArtifact:
    path = Path(path).resolve()
    if not path.is_file():
        raise HumanEvalContractError(f"task file does not exist: {path}")
    digest = sha256_file(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise HumanEvalContractError(
            f"task file digest mismatch for {path}: expected {expected_sha256}, got {digest}"
        )
    rows = _read_tasks(path)
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise HumanEvalContractError(f"{path}: duplicate task ids")
    return TaskArtifact(path=path, sha256=digest, suite=_manifest_suite(path), rows=rows)


_SYSTEM_ID_KEYS = ("systemId", "configId", "candidateId", "modelId", "model", "id")
_REVISION_KEYS = ("modelRevision", "revision", "commit", "checkpoint")


def _first_str(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_raw_outputs(payload: Mapping[str, Any], path: Path) -> dict[str, str]:
    rows = payload.get("outputs")
    if not isinstance(rows, list) or not rows:
        raise HumanEvalContractError(f"{path}: result artifact requires a non-empty outputs array")
    outputs: dict[str, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HumanEvalContractError(f"{path}: outputs[{index}] must be an object")
        task_id = _first_str(row, ("id", "taskId"))
        if not task_id:
            raise HumanEvalContractError(f"{path}: outputs[{index}] requires a task id")
        raw = row.get("output")
        if not isinstance(raw, str):
            raw = row.get("rawOutput") if isinstance(row.get("rawOutput"), str) else None
        if raw is None:
            raise HumanEvalContractError(
                f"{path}: outputs[{index}] ({task_id}) requires raw output text"
            )
        if task_id in outputs:
            raise HumanEvalContractError(f"{path}: duplicate output row for task {task_id}")
        outputs[task_id] = raw
    return outputs


def _declared_task_hash(path: Path) -> str | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _first_str(payload, ("taskFileSha256", "taskFileSHA256", "taskHash"))


def load_system_artifact(path: Path, *, task_file_sha256: str) -> SystemArtifact:
    path = Path(path).resolve()
    if not path.is_file():
        raise HumanEvalContractError(f"result artifact does not exist: {path}")
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise HumanEvalContractError(f"{path}: result artifact is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HumanEvalContractError(f"{path}: result artifact must be a JSON object")
    declared_task_hash = _first_str(payload, ("taskFileSha256", "taskFileSHA256", "taskHash"))
    if not declared_task_hash:
        raise HumanEvalContractError(f"{path}: result artifact does not declare taskFileSha256")
    if declared_task_hash != task_file_sha256:
        raise HumanEvalContractError(
            f"{path}: result artifact belongs to task file {declared_task_hash}, but the "
            f"frozen task file is {task_file_sha256}; refusing to mix identities"
        )
    system_id = _first_str(payload, _SYSTEM_ID_KEYS)
    if not system_id:
        raise HumanEvalContractError(f"{path}: result artifact does not declare a system/config id")
    outputs = _extract_raw_outputs(payload, path)
    metadata = {
        "model": payload.get("model"),
        "runtime": payload.get("runtime"),
        "decoding": payload.get("decoding"),
        "purpose": payload.get("purpose"),
        "complete": payload.get("complete"),
    }
    return SystemArtifact(
        system_id=system_id,
        label=_first_str(payload, ("label", "displayName")) or system_id,
        revision=_first_str(payload, _REVISION_KEYS),
        result_path=path,
        result_sha256=sha256_bytes(raw_bytes),
        task_file_sha256=declared_task_hash,
        outputs=outputs,
        metadata=metadata,
    )


def load_inputs(
    *,
    task_files: Sequence[Path],
    result_files: Sequence[Path],
    parser_path: Path | None = None,
    protocol_path: Path | None = None,
    expected_task_hashes: Mapping[str, str] | None = None,
) -> Inputs:
    """Load and cross-verify every provenance-qualified input.

    Refuses, rather than reconciles, when two artifacts disagree about the task
    file, when a task file's bytes drift from the frozen hash, or when a result
    file is missing outputs for a task it claims to cover.
    """
    expected_task_hashes = dict(expected_task_hashes or {})
    parser_path = Path(parser_path) if parser_path else HERE / "word_studio_output_parser.py"
    protocol_path = Path(protocol_path) if protocol_path else HERE / PROTOCOL_RELATIVE_PATH
    for required in (parser_path, protocol_path):
        if not required.is_file():
            raise HumanEvalContractError(f"required provenance file is missing: {required}")

    artifacts = [
        load_task_artifact(path, expected_task_hashes.get(Path(path).name)) for path in task_files
    ]
    if not artifacts:
        raise HumanEvalContractError("at least one task file is required")
    if len({artifact.sha256 for artifact in artifacts}) != len(artifacts):
        raise HumanEvalContractError(
            "two task files share the same digest; task identity is ambiguous"
        )

    task_index: dict[str, dict[str, Any]] = {}
    task_file_key: dict[str, str] = {}
    for artifact in artifacts:
        for row in artifact.rows:
            task_id = row["id"]
            if task_id in task_index:
                raise HumanEvalContractError(f"task id {task_id} appears in more than one task file")
            task_index[task_id] = row
            task_file_key[task_id] = artifact.sha256

    systems: list[SystemArtifact] = []
    seen_systems: set[str] = set()
    for path in result_files:
        candidates = [
            artifact
            for artifact in artifacts
            if _declared_task_hash(Path(path)) == artifact.sha256
        ]
        if not candidates:
            raise HumanEvalContractError(
                f"{Path(path).resolve()}: result artifact does not match any frozen task file"
            )
        if len(candidates) > 1:
            raise HumanEvalContractError(
                f"{Path(path).resolve()}: result artifact matches multiple frozen task files"
            )
        system = load_system_artifact(path, task_file_sha256=candidates[0].sha256)
        if system.system_id in seen_systems:
            raise HumanEvalContractError(f"duplicate finalist/config id: {system.system_id}")
        seen_systems.add(system.system_id)
        missing = [row["id"] for row in candidates[0].rows if row["id"] not in system.outputs]
        if missing:
            raise HumanEvalContractError(
                f"{system.result_path.name}: {len(missing)} task(s) have no raw output, first "
                f"missing {missing[0]}; refusing a partial finalist artifact"
            )
        systems.append(system)
    if len(systems) < 2:
        raise HumanEvalContractError(
            "pairwise human comparison needs at least two qualified finalists"
        )

    systems.sort(key=lambda item: item.system_id)
    return Inputs(
        tasks_by_file={artifact.sha256: artifact for artifact in artifacts},
        task_index=task_index,
        task_file_key=task_file_key,
        systems=systems,
        parser_sha256=sha256_file(parser_path),
        parser_version=parser.PARSER_VERSION,
        protocol_sha256=sha256_file(protocol_path),
        rubric_sha256=sha256_object(RUBRIC),
        protocol_path=protocol_path.resolve(),
    )


# ---------------------------------------------------------------------------
# Per-task rubric selection


def semantic_mode_of(task: Mapping[str, Any]) -> str:
    declared = str(task.get("semanticMode") or task.get("semantic_mode") or "").strip().lower()
    if declared == SEMANTIC_MODE_COMPRESSION:
        return SEMANTIC_MODE_COMPRESSION
    if parser.route_from_task(task) == parser.ROUTE_INTENTIONAL_COMPRESSION:
        return SEMANTIC_MODE_COMPRESSION
    return SEMANTIC_MODE_PRESERVE


def _has_protected_context(task: Mapping[str, Any]) -> bool:
    if str(task.get("sourceCategory") or "").strip().lower() == "protected_context":
        return True
    for key in ("protectedValues", "protected", "protectedContent"):
        value = task.get(key)
        if isinstance(value, (list, tuple)) and value:
            return True
    return False


def criteria_for_task(task: Mapping[str, Any]) -> list[str]:
    """Ordered criteria for one task, with the compression separation enforced."""
    mode = semantic_mode_of(task)
    if mode == SEMANTIC_MODE_COMPRESSION:
        selected = [CRITERION_COMPRESSION, *_BASE_CRITERIA]
    else:
        selected = [CRITERION_MEANING, *_BASE_CRITERIA]
    if _has_protected_context(task):
        selected.append(CRITERION_PROTECTED)
    allowed = set(selected)
    # Iterate the frozen CRITERIA order so the packet, preregistration and
    # schema always agree on criterion sequence.
    return [
        criterion
        for criterion in CRITERIA
        if criterion in allowed and mode in CRITERIA[criterion]["appliesToSemanticModes"]
    ]


# ---------------------------------------------------------------------------
# Candidate extraction (delegated to the one canonical parser)


@dataclass(frozen=True)
class CandidateSet:
    """Ordered, parser-admitted candidates for one (task, system)."""

    task_id: str
    system_id: str
    candidates: tuple[str, ...]
    rejected_reasons: dict[str, int]
    usable_unique_count: int
    requested: int
    parse_mode: str


def candidates_for_task(task: Mapping[str, Any], system: SystemArtifact, *, depth: int) -> CandidateSet:
    """Parse one finalist's raw output through the canonical usable-candidate contract."""
    raw = system.outputs.get(task["id"])
    if raw is None:
        raise HumanEvalContractError(
            f"no raw output for task {task['id']} in {system.result_path.name}"
        )
    source = task.get("selectedText") or task.get("sourceText")
    requested = int(task.get("requestedCount") or 10)
    values, parse_mode = parser.parse_options(raw)
    ledger = parser.CandidateLedger(
        source=str(source) if source is not None else None,
        requested=requested,
        route=parser.route_from_task(task),
        protected=task.get("protectedValues") or task.get("protected"),
    )
    for value in values:
        ledger.add(value)
    return CandidateSet(
        task_id=task["id"],
        system_id=system.system_id,
        candidates=tuple(ledger.accepted[:depth]),
        rejected_reasons=dict(sorted(ledger.rejected_reasons.items())),
        usable_unique_count=ledger.usable_unique_count,
        requested=requested,
        parse_mode=parse_mode,
    )


@dataclass(frozen=True)
class DeterministicChange:
    """Deterministic change diagnostics for the strength trajectory."""

    char_similarity: float
    length_ratio: float
    token_delta: int


def change_diagnostics(source: str, candidate: str) -> DeterministicChange:
    source_key = parser.comparison_key(source)
    candidate_key = parser.comparison_key(candidate)
    similarity = (
        SequenceMatcher(None, source_key, candidate_key).ratio()
        if source_key and candidate_key
        else 0.0
    )
    source_tokens = source_key.split()
    candidate_tokens = candidate_key.split()
    return DeterministicChange(
        char_similarity=round(similarity, 6),
        length_ratio=round(len(candidate_tokens) / len(source_tokens), 6) if source_tokens else 0.0,
        token_delta=len(candidate_tokens) - len(source_tokens),
    )


# ---------------------------------------------------------------------------
# Comparisons and preregistration


@dataclass(frozen=True)
class Comparison:
    """One internal comparison unit. Identity fields never reach a packet."""

    internal_id: str
    task_id: str
    task_file_sha256: str
    system_a: str
    system_b: str
    criteria: tuple[str, ...]
    semantic_mode: str
    route: str


def build_comparisons(inputs: Inputs) -> list[Comparison]:
    """Deterministic all-pairs round robin over the frozen finalist order."""
    system_ids = [system.system_id for system in inputs.systems]
    comparisons: list[Comparison] = []
    for task_id in sorted(inputs.task_index):
        task = inputs.task_index[task_id]
        for left_index, left in enumerate(system_ids):
            for right in system_ids[left_index + 1 :]:
                comparisons.append(
                    Comparison(
                        internal_id=f"{task_id}::{left}::{right}",
                        task_id=task_id,
                        task_file_sha256=inputs.task_file_key[task_id],
                        system_a=left,
                        system_b=right,
                        criteria=tuple(criteria_for_task(task)),
                        semantic_mode=semantic_mode_of(task),
                        route=parser.route_from_task(task),
                    )
                )
    if not comparisons:
        raise HumanEvalContractError("no comparisons could be built from the frozen inputs")
    return comparisons


@dataclass(frozen=True)
class StrengthTask:
    """One (source, strength) slider variant, kept grouped by source."""

    task_id: str
    source_key: str
    source_group_id: str
    strength: int


def build_strength_tasks(
    inputs: Inputs, seed: str
) -> tuple[list[StrengthTask], dict[str, list[StrengthTask]]]:
    """Group the four slider variants by source, preserving ordered strength identity."""
    grouped: dict[str, list[StrengthTask]] = {}
    for task_id in sorted(inputs.task_index):
        task = inputs.task_index[task_id]
        if "strength" not in task:
            continue
        try:
            strength = int(task["strength"])
        except (TypeError, ValueError) as exc:
            raise HumanEvalContractError(f"task {task_id} has a non-integer strength") from exc
        if strength not in STRENGTH_LEVELS:
            raise HumanEvalContractError(
                f"task {task_id} strength {strength} is not one of the frozen levels {STRENGTH_LEVELS}"
            )
        source_key = str(task.get("sourceId") or task.get("source") or task_id)
        grouped.setdefault(source_key, []).append(
            StrengthTask(
                task_id=task_id,
                source_key=source_key,
                source_group_id=_opaque_id("src", seed, "strength-group", source_key),
                strength=strength,
            )
        )
    ordered = {
        source_key: sorted(grouped[source_key], key=lambda item: (item.strength, item.task_id))
        for source_key in sorted(grouped)
    }
    return [task for source in ordered.values() for task in source], ordered


def system_public_tokens(inputs: Inputs) -> list[str]:
    """Every identity/runtime token that must not appear in a reviewer packet."""
    tokens: set[str] = set()
    for artifact in inputs.tasks_by_file.values():
        tokens.add(artifact.path.name)
        tokens.add(str(artifact.path))
    for system in inputs.systems:
        tokens.update(
            {system.system_id, system.label, system.result_path.name, str(system.result_path)}
        )
        if system.revision:
            tokens.add(system.revision)
        for key in ("model", "runtime"):
            value = system.metadata.get(key)
            if isinstance(value, str) and value:
                tokens.add(value)
        decoding = system.metadata.get("decoding")
        if isinstance(decoding, Mapping):
            tokens.update(
                str(value) for value in decoding.values() if isinstance(value, str) and value
            )
    return sorted(token for token in tokens if len(token) >= 4)


def build_preregistration(
    inputs: Inputs,
    comparisons: Sequence[Comparison],
    *,
    seed: str,
    depths: Sequence[int] = DEFAULT_DEPTHS,
    rater_ids: Sequence[str] = DEFAULT_RATERS,
    author_expectation_mode: str = "not_used",
    evaluation_id: str = "ws-human-eval",
) -> dict[str, Any]:
    """Deterministic, hash-bound preregistration manifest.

    Finalist identities are deliberately absent: the preregistration records the
    result digests and the count, while the names live only in the separately
    hashed private mapping built alongside it.
    """
    policies = default_policies(depths)
    allowed_modes = policies["authorExpectationPolicy"]["allowedModes"]
    if author_expectation_mode not in allowed_modes:
        raise HumanEvalContractError(
            f"author expectation mode {author_expectation_mode!r} is not preregistered; "
            f"allowed: {allowed_modes}"
        )

    strength_tasks, strength_groups = build_strength_tasks(inputs, seed)
    body: dict[str, Any] = {
        "schemaVersion": PREREGISTRATION_SCHEMA_VERSION,
        "evaluationId": evaluation_id,
        "protocol": {
            "document": PROTOCOL_RELATIVE_PATH,
            "sha256": inputs.protocol_sha256,
            "rubricVersion": RUBRIC["rubricVersion"],
            "rubricSha256": inputs.rubric_sha256,
        },
        "usableCandidateContract": {
            "module": "word_studio_output_parser.py",
            "sha256": inputs.parser_sha256,
            "parserVersion": inputs.parser_version,
        },
        "taskArtifacts": [
            {
                "taskFileSha256": artifact.sha256,
                "suite": artifact.suite,
                "taskCount": len(artifact.rows),
                "orderedTaskIdSha256": sha256_object([row["id"] for row in artifact.rows]),
            }
            for artifact in sorted(inputs.tasks_by_file.values(), key=lambda item: item.sha256)
        ],
        "resultArtifacts": sorted(
            (
                {
                    "resultSha256": system.result_sha256,
                    "taskFileSha256": system.task_file_sha256,
                    "revision": system.revision,
                }
                for system in inputs.systems
            ),
            key=lambda item: item["resultSha256"],
        ),
        "finalistCount": len(inputs.systems),
        "finalistIdentityPolicy": {
            "identitiesLiveIn": "private mapping artifact only",
            "countFrozenHere": True,
            "preregistrationStoresResultDigestsOnly": True,
        },
        "taskIds": sorted(inputs.task_index),
        "routes": sorted({comparison.route for comparison in comparisons}),
        "semanticModes": sorted({comparison.semantic_mode for comparison in comparisons}),
        "criteria": {criterion: CRITERIA[criterion]["wording"] for criterion in sorted(CRITERIA)},
        "criteriaSelection": {
            criterion: sorted(CRITERIA[criterion]["appliesToSemanticModes"])
            for criterion in sorted(CRITERIA)
        },
        "compressionSeparation": {
            "semanticMode": SEMANTIC_MODE_COMPRESSION,
            "replacesCriterion": CRITERION_MEANING,
            "criterion": CRITERION_COMPRESSION,
            "rule": CRITERIA[CRITERION_COMPRESSION]["decisionRule"],
        },
        "policies": policies,
        "randomization": {
            "seed": seed,
            "derivation": "HMAC-SHA256(seed, label path) -> independent deterministic streams",
            "sideAssignment": policies["pairGenerationPolicy"]["sideAssignment"],
            "itemOrder": policies["pairGenerationPolicy"]["itemOrder"],
        },
        "raters": {
            "anonymousIds": sorted(set(rater_ids)),
            "count": len(set(rater_ids)),
            "personallyIdentifyingInfoRequired": False,
        },
        "authorExpectationPolicy": {
            "mode": author_expectation_mode,
            "reviewerChecklistTaskCount": 0,
            "reviewerChecklistSha256": None,
            "rule": policies["authorExpectationPolicy"]["reviewerChecklist"],
            "neverModelInput": True,
            "neverValidatedGold": True,
        },
        "strengthSlider": {
            "levels": list(STRENGTH_LEVELS),
            "sourceGroupCount": len(strength_groups),
            "trajectoryTaskCount": len(strength_tasks),
            "repeatedMeasures": True,
            "analysisRules": [
                "change diagnostics rise with requested strength per source",
                "human usefulness and semantic/register stability do not collapse as strength rises",
                "15/40/60/90 stay perceptibly distinct enough to justify the control",
                "higher strength does not mean stronger opinion or claim intensity",
                "per-source trajectories are preserved; non-monotonic sources are reported",
            ],
            "editDistanceAloneIsNotQuality": True,
        },
        "comparisonCount": len(comparisons),
        "evidenceStatus": (
            "pipeline_frozen_no_ratings_yet; author expectations remain "
            "synthetic/unvalidated; human raters have not run"
        ),
    }
    body["preregistrationSha256"] = sha256_object(body)
    return body


# ---------------------------------------------------------------------------
# Blinding and randomization


def scan_for_leaks(payload: Any, forbidden_tokens: Sequence[str]) -> list[str]:
    """Return every identity/runtime/expectation leak found in a reviewer payload."""
    blob = canonical_json(payload).lower()
    leaks: list[str] = []

    def walk(node: Any, path: str = "$") -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in FORBIDDEN_PACKET_KEYS:
                    leaks.append(f"forbidden key {path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(payload)
    leaks.extend(
        f"identity/runtime token {token!r}" for token in forbidden_tokens if token and token.lower() in blob
    )
    words = set(_WORD_RE.findall(blob.replace("-", "_").replace(".", "_")))
    for needle in FORBIDDEN_PACKET_TOKENS:
        if needle.replace("-", "_").replace(".", "_") in words:
            leaks.append(f"runtime token {needle!r}")
    return sorted(set(leaks))


def build_packets(
    inputs: Inputs,
    comparisons: Sequence[Comparison],
    preregistration: Mapping[str, Any],
    *,
    depth: int,
    reviewer_checklist: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Build per-rater blinded packets and the separately hashed private mapping."""
    seed = preregistration["randomization"]["seed"]
    evaluation_id = preregistration["evaluationId"]
    mode = preregistration["authorExpectationPolicy"]["mode"]
    checklist_payload = {
        str(task_id): [str(item) for item in items]
        for task_id, items in sorted((reviewer_checklist or {}).items())
        if mode == "reviewer_checklist"
    }

    candidate_cache: dict[tuple[str, str], CandidateSet] = {}
    for system in inputs.systems:
        for task_id in sorted(inputs.task_index):
            candidate_cache[(task_id, system.system_id)] = candidates_for_task(
                inputs.task_index[task_id], system, depth=depth
            )

    pair_public_id = {
        comparison.internal_id: _opaque_id("pair", seed, evaluation_id, "pair", comparison.internal_id)
        for comparison in comparisons
    }
    system_key = {
        system.system_id: _opaque_id("sys", seed, evaluation_id, "system", system.system_id)
        for system in inputs.systems
    }
    _, strength_groups = build_strength_tasks(inputs, seed)

    packets: dict[str, Any] = {}
    forbidden = system_public_tokens(inputs)

    for rater_id in sorted(preregistration["raters"]["anonymousIds"]):
        order_rng = _rng(seed, "item-order", rater_id)
        side_rng = _rng(seed, "side-balance", rater_id)

        ordered = list(comparisons)
        order_rng.shuffle(ordered)
        # Balanced first, then shuffled: side counts differ by at most one per
        # system while the assignment stays unpredictable from input order.
        count = len(ordered)
        left_on_a = [True] * (count // 2) + [False] * (count - count // 2)
        side_rng.shuffle(left_on_a)

        items: list[dict[str, Any]] = []
        for comparison, left_on_a in zip(ordered, left_on_a):
            internal_a, internal_b = (
                (comparison.system_a, comparison.system_b)
                if left_on_a
                else (comparison.system_b, comparison.system_a)
            )
            items.append(
                _build_pair_item(
                    inputs,
                    comparison,
                    pair_public_id[comparison.internal_id],
                    candidate_cache[(comparison.task_id, internal_a)],
                    candidate_cache[(comparison.task_id, internal_b)],
                    checklist_payload=checklist_payload,
                )
            )

        for source_key in sorted(strength_groups):
            items.append(
                _build_strength_item(
                    inputs,
                    strength_groups[source_key],
                    candidate_cache,
                    system_id=min(system_key),
                )
            )

        body = {
            "schemaVersion": PACKET_SCHEMA_VERSION,
            "packetId": _opaque_id("pkt", seed, evaluation_id, "packet", rater_id),
            "raterId": rater_id,
            "evaluationId": evaluation_id,
            "preregistrationSha256": preregistration["preregistrationSha256"],
            "rubricSha256": preregistration["protocol"]["rubricSha256"],
            "protocolSha256": preregistration["protocol"]["sha256"],
            "randomizationSeed": seed,
            "instructions": _reviewer_instructions(preregistration),
            "items": items,
        }
        body["packetSha256"] = sha256_object(body)
        leaks = scan_for_leaks(body, forbidden)
        if leaks:
            raise HumanEvalContractError(
                f"packet for rater {rater_id} leaks reviewer-invisible metadata: {leaks}"
            )
        packets[rater_id] = body

    private_mapping = {
        "schemaVersion": MAPPING_SCHEMA_VERSION,
        "evaluationId": evaluation_id,
        "preregistrationSha256": preregistration["preregistrationSha256"],
        "visibility": "private; reveal only in the final analysis step",
        "systems": [
            {
                "systemKey": system_key[system.system_id],
                "systemId": system.system_id,
                "label": system.label,
                "revision": system.revision,
                "resultSha256": system.result_sha256,
                "taskFileSha256": system.task_file_sha256,
            }
            for system in sorted(inputs.systems, key=lambda item: item.system_id)
        ],
        "pairs": [
            {
                "pairId": pair_public_id[comparison.internal_id],
                "taskId": comparison.task_id,
                "systemKeyA": system_key[comparison.system_a],
                "systemKeyB": system_key[comparison.system_b],
            }
            for comparison in comparisons
        ],
    }
    private_mapping["mappingSha256"] = sha256_object(private_mapping)
    return {
        "packets": packets,
        "privateMapping": private_mapping,
        "pairPublicIds": dict(sorted(pair_public_id.items())),
        "systemKeys": dict(sorted(system_key.items())),
    }


def _build_pair_item(
    inputs: Inputs,
    comparison: Comparison,
    pair_id: str,
    set_a: CandidateSet,
    set_b: CandidateSet,
    *,
    checklist_payload: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    task = inputs.task_index[comparison.task_id]
    item: dict[str, Any] = {
        "kind": "pair_comparison",
        "pairId": pair_id,
        "taskId": comparison.task_id,
        "sourceText": task.get("sourceText"),
        "selectedText": task.get("selectedText"),
        "operation": _operation_label(task),
        "requestedStrength": task.get("strength"),
        "semanticMode": comparison.semantic_mode,
        "route": comparison.route,
        "criteria": [
            {
                "criterion": criterion,
                "wording": CRITERIA[criterion]["wording"],
                "decisionRule": CRITERIA[criterion]["decisionRule"],
                "labels": list(PAIRWISE_LABELS),
            }
            for criterion in comparison.criteria
        ],
        "sides": {"A": _side_payload(set_a), "B": _side_payload(set_b)},
    }
    checklist = checklist_payload.get(comparison.task_id)
    if checklist:
        item["reviewerChecklist"] = {
            "status": "author-written checklist, not human-validated gold",
            "items": list(checklist),
        }
    return item


def _operation_label(task: Mapping[str, Any]) -> str:
    for key in ("operationInstruction", "instruction", "operation", "task"):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "word-studio edit"


def _side_payload(candidate_set: CandidateSet) -> dict[str, Any]:
    return {
        "candidates": [
            {"candidateId": f"{index}", "text": text}
            for index, text in enumerate(candidate_set.candidates, start=1)
        ]
    }


def _build_strength_item(
    inputs: Inputs,
    variants: Sequence[StrengthTask],
    candidate_cache: Mapping[tuple[str, str], CandidateSet],
    *,
    system_id: str,
) -> dict[str, Any]:
    task = inputs.task_index[variants[0].task_id]
    source_text = str(task.get("sourceText") or "")
    rows = []
    for variant in variants:
        candidates = candidate_cache[(variant.task_id, system_id)].candidates
        lead = candidates[0] if candidates else ""
        diagnostics = change_diagnostics(source_text, lead) if lead else None
        rows.append(
            {
                "variantId": f"v{variant.strength}",
                "requestedStrength": variant.strength,
                "leadCandidate": lead,
                "leadCandidateCount": len(candidates),
                "changeDiagnostics": (
                    {
                        "charSimilarity": diagnostics.char_similarity,
                        "lengthRatio": diagnostics.length_ratio,
                        "tokenDelta": diagnostics.token_delta,
                    }
                    if diagnostics
                    else None
                ),
            }
        )
    return {
        "kind": "strength_trajectory",
        "sourceGroupId": variants[0].source_group_id,
        "taskIds": [variant.task_id for variant in variants],
        "strengths": list(STRENGTH_LEVELS),
        "variants": rows,
        "questions": [
            {
                "field": "edit_usefulness",
                "wording": "This variant is a genuinely usable edit for the requested strength.",
                "labels": list(CANDIDATE_LABELS),
            },
            {
                "field": "semantic_register_stable",
                "wording": "Meaning and register hold as the requested strength rises.",
                "labels": list(STRENGTH_BOOLEAN_LABELS),
            },
            {
                "field": "intensity_increased",
                "wording": (
                    "This variant makes the claim or opinion stronger than the source. A "
                    "strength slider must not do this."
                ),
                "labels": list(STRENGTH_BOOLEAN_LABELS),
            },
        ],
        "note": (
            "Strength levels keep their identity and order; the four variants of one "
            "source are repeated measures, not four unrelated examples. Change "
            "diagnostics are deterministic and are not quality scores."
        ),
    }


def _reviewer_instructions(preregistration: Mapping[str, Any]) -> dict[str, Any]:
    depth = preregistration["policies"]["candidateDepthPolicy"]["maxDepthShown"]
    return {
        "purpose": "Compare two anonymous rewrites of the same source under each criterion.",
        "blinding": (
            "Sides A and B are anonymous and their assignment is randomized per "
            "comparison. No model, runtime, latency or size information is present."
        ),
        "pairwiseLabels": list(PAIRWISE_LABELS),
        "pairwiseLabelMeanings": {
            "A": "Side A is better on this criterion.",
            "B": "Side B is better on this criterion.",
            "tie": "Tied or equally acceptable; a tie is a real answer.",
            "both_unacceptable": (
                "Neither side is usable on this criterion. Say so rather than "
                "inventing a winner."
            ),
        },
        "candidateLabels": list(CANDIDATE_LABELS),
        "candidateLabelMeanings": {
            "usable": "A genuinely usable alternative, not a duplicate or filler.",
            "not_usable": "Duplicate, filler, broken, or not a usable alternative.",
            "unclear": "You cannot decide; unclear is not usable.",
        },
        "candidatesShownPerSide": depth,
        "usefulDepthRule": (
            "Mark candidates usable only from what is shown. A leading run of usable "
            "candidates reconstructs top-k coverage."
        ),
        "criteriaSeparated": "Judge each criterion independently; there is no overall score.",
        "compressionNote": (
            "Intentional-compression items are judged on compression_quality. Detail "
            "loss is intended and is not paraphrase loss."
        ),
        "disagreementNote": "Genuine disagreement is data. Do not force a winner.",
    }


# ---------------------------------------------------------------------------
# Rating schema and validation


def rating_schema() -> dict[str, Any]:
    """Strict JSON Schema for one rater's submission."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://pari.local/schemas/word-studio-human-eval-rating-schema.json",
        "title": "Pari Word Studio blinded human-evaluation rating document",
        "description": (
            "Schema v1. Closed at every level. Reviewer identity is an anonymous rater "
            "id only; no personally identifying information is permitted."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "packetId",
            "packetSha256",
            "preregistrationSha256",
            "rubricSha256",
            "raterId",
            "pairRatings",
            "candidateRatings",
            "strengthRatings",
        ],
        "properties": {
            "schemaVersion": {"const": RATING_SCHEMA_VERSION},
            "packetId": {"type": "string", "minLength": 1},
            "packetSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "preregistrationSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "rubricSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "raterId": {"type": "string", "pattern": "^r-[A-Za-z0-9_-]{1,64}$"},
            "pairRatings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["pairId", "criterion", "label"],
                    "properties": {
                        "pairId": {"type": "string", "minLength": 1},
                        "criterion": {"type": "string", "enum": sorted(CRITERIA)},
                        "label": {"type": "string", "enum": list(PAIRWISE_LABELS)},
                        "note": {"type": ["string", "null"]},
                    },
                },
            },
            "candidateRatings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["pairId", "side", "candidateId", "label"],
                    "properties": {
                        "pairId": {"type": "string", "minLength": 1},
                        "side": {"type": "string", "enum": ["A", "B"]},
                        "candidateId": {"type": "string", "pattern": "^[0-9]+$"},
                        "label": {"type": "string", "enum": list(CANDIDATE_LABELS)},
                        "note": {"type": ["string", "null"]},
                    },
                },
            },
            "strengthRatings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "sourceGroupId",
                        "requestedStrength",
                        "edit_usefulness",
                        "semantic_register_stable",
                        "intensity_increased",
                    ],
                    "properties": {
                        "sourceGroupId": {"type": "string", "minLength": 1},
                        "requestedStrength": {"type": "integer", "enum": list(STRENGTH_LEVELS)},
                        "edit_usefulness": {"type": "string", "enum": list(CANDIDATE_LABELS)},
                        "semantic_register_stable": {
                            "type": "string",
                            "enum": list(STRENGTH_BOOLEAN_LABELS),
                        },
                        "intensity_increased": {
                            "type": "string",
                            "enum": list(STRENGTH_BOOLEAN_LABELS),
                        },
                        "note": {"type": ["string", "null"]},
                    },
                },
            },
        },
    }


_ALLOWED_RATING_KEYS = frozenset(
    {
        "schemaVersion",
        "packetId",
        "packetSha256",
        "preregistrationSha256",
        "rubricSha256",
        "raterId",
        "pairRatings",
        "candidateRatings",
        "strengthRatings",
    }
)


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized: dict[str, Any] = field(default_factory=dict)

    def raise_for_errors(self) -> dict[str, Any]:
        if not self.ok:
            raise HumanEvalContractError(
                "rating document failed validation:\n"
                + "\n".join(f"  - {error}" for error in self.errors)
            )
        return self.normalized


def _mapping_tokens(private_mapping: Mapping[str, Any] | None) -> list[str]:
    tokens: list[str] = []
    if not private_mapping:
        return tokens
    for entry in private_mapping.get("systems", []) or []:
        tokens.extend(
            str(entry[key])
            for key in ("systemKey", "systemId", "label", "revision")
            if isinstance(entry.get(key), str) and entry.get(key)
        )
    for entry in private_mapping.get("pairs", []) or []:
        tokens.extend(
            str(entry[key]) for key in ("systemKeyA", "systemKeyB") if isinstance(entry.get(key), str)
        )
    digest = private_mapping.get("mappingSha256")
    if isinstance(digest, str):
        tokens.append(digest)
    return [token for token in tokens if len(token) >= 4]


def validate_rating_document(
    document: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    private_mapping: Mapping[str, Any] | None = None,
) -> ValidationReport:
    """Strict structural + semantic validation of one rater's submission."""
    errors: list[str] = []
    warnings: list[str] = []

    unknown_keys = sorted(set(document) - _ALLOWED_RATING_KEYS)
    if unknown_keys:
        errors.append(f"unknown top-level fields: {unknown_keys}")

    if document.get("schemaVersion") != RATING_SCHEMA_VERSION:
        errors.append(
            f"schemaVersion must be {RATING_SCHEMA_VERSION}, got {document.get('schemaVersion')!r}"
        )
    if document.get("raterId") != packet.get("raterId"):
        errors.append(
            f"raterId {document.get('raterId')!r} does not match packet rater "
            f"{packet.get('raterId')!r}"
        )
    if document.get("packetId") != packet.get("packetId"):
        errors.append("packetId does not match the frozen packet")

    expected_packet_sha = packet.get("packetSha256")
    if document.get("packetSha256") != expected_packet_sha:
        errors.append(
            f"packetSha256 {document.get('packetSha256')!r} is not the frozen packet digest "
            f"{expected_packet_sha!r}; the packet is outdated"
        )
    if document.get("preregistrationSha256") != preregistration.get("preregistrationSha256"):
        errors.append("preregistrationSha256 does not match the frozen preregistration")
    if document.get("rubricSha256") != preregistration["protocol"]["rubricSha256"]:
        errors.append("rubricSha256 does not match the frozen rubric")

    # Reviewer data must never carry the private mapping.
    leaks = scan_for_leaks(document, _mapping_tokens(private_mapping))
    if leaks:
        errors.append(f"reviewer data exposes private mapping content: {leaks}")

    pair_items = {
        item["pairId"]: item
        for item in packet.get("items", [])
        if item.get("kind") == "pair_comparison"
    }
    strength_groups = {
        item["sourceGroupId"]: item
        for item in packet.get("items", [])
        if item.get("kind") == "strength_trajectory"
    }

    seen_pairs: set[tuple[str, str]] = set()
    submitted_by_pair: dict[str, set[str]] = {pair_id: set() for pair_id in pair_items}
    normalized_pairs: list[dict[str, Any]] = []
    for index, row in enumerate(document.get("pairRatings", []) or []):
        where = f"pairRatings[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{where} must be an object")
            continue
        extra = sorted(set(row) - {"pairId", "criterion", "label", "note"})
        if extra:
            errors.append(f"{where} has unknown fields {extra}")
        pair_id, criterion, label = row.get("pairId"), row.get("criterion"), row.get("label")
        if pair_id not in pair_items:
            errors.append(f"{where} references unknown pairId {pair_id!r}")
            continue
        if criterion not in CRITERIA:
            errors.append(f"{where} uses unknown criterion {criterion!r}")
            continue
        if label not in PAIRWISE_LABELS:
            errors.append(
                f"{where} uses impossible label {label!r}; allowed {list(PAIRWISE_LABELS)}"
            )
            continue
        item = pair_items[pair_id]
        if criterion not in {entry["criterion"] for entry in item.get("criteria", [])}:
            errors.append(f"{where} criterion {criterion!r} is not requested for {pair_id}")
            continue
        key = (str(pair_id), str(criterion))
        if key in seen_pairs:
            errors.append(f"{where} duplicates an existing rating for ({pair_id}, {criterion})")
            continue
        seen_pairs.add(key)
        submitted_by_pair[str(pair_id)].add(str(criterion))
        normalized_pairs.append(
            {
                "pairId": pair_id,
                "criterion": criterion,
                "label": label,
                "note": row.get("note"),
                "semanticMode": item.get("semanticMode"),
                "route": item.get("route"),
                "taskId": item.get("taskId"),
            }
        )

    for pair_id, item in sorted(pair_items.items()):
        missing = sorted(
            {entry["criterion"] for entry in item.get("criteria", [])} - submitted_by_pair[pair_id]
        )
        if missing:
            errors.append(f"missing required criteria for {pair_id}: {missing}")

    seen_candidates: set[tuple[str, str]] = set()
    normalized_candidates: list[dict[str, Any]] = []
    for index, row in enumerate(document.get("candidateRatings", []) or []):
        where = f"candidateRatings[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{where} must be an object")
            continue
        extra = sorted(set(row) - {"pairId", "side", "candidateId", "label", "note"})
        if extra:
            errors.append(f"{where} has unknown fields {extra}")
        pair_id = row.get("pairId")
        side = row.get("side")
        candidate_id = row.get("candidateId")
        label = row.get("label")
        if pair_id not in pair_items:
            errors.append(f"{where} references unknown pairId {pair_id!r}")
            continue
        if side not in ("A", "B"):
            errors.append(f"{where} side must be 'A' or 'B', got {side!r}")
            continue
        if label not in CANDIDATE_LABELS:
            errors.append(f"{where} uses impossible label {label!r}")
            continue
        known_ids = {
            str(candidate["candidateId"])
            for candidate in pair_items[pair_id].get("sides", {}).get(side, {}).get("candidates", [])
        }
        if str(candidate_id) not in known_ids:
            errors.append(
                f"{where} references unknown candidate {candidate_id!r} on side {side} of {pair_id}"
            )
            continue
        key = (str(pair_id), str(side), str(candidate_id))
        if key in seen_candidates:
            errors.append(f"{where} duplicates an existing candidate rating for {key}")
            continue
        seen_candidates.add(key)
        normalized_candidates.append(
            {
                "pairId": pair_id,
                "side": side,
                "candidateId": str(candidate_id),
                "label": label,
            }
        )

    normalized_strength: list[dict[str, Any]] = []
    seen_strength: set[tuple[str, int]] = set()
    for index, row in enumerate(document.get("strengthRatings", []) or []):
        where = f"strengthRatings[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{where} must be an object")
            continue
        extra = sorted(
            set(row)
            - {
                "sourceGroupId",
                "requestedStrength",
                "edit_usefulness",
                "semantic_register_stable",
                "intensity_increased",
                "note",
            }
        )
        if extra:
            errors.append(f"{where} has unknown fields {extra}")
        group, strength = row.get("sourceGroupId"), row.get("requestedStrength")
        if group not in strength_groups:
            errors.append(f"{where} references unknown sourceGroupId {group!r}")
            continue
        available = {
            int(variant["requestedStrength"]) for variant in strength_groups[group]["variants"]
        }
        if strength not in available:
            errors.append(f"{where} requestedStrength {strength!r} is not part of group {group}")
            continue
        invalid = False
        for field_name, allowed in (
            ("edit_usefulness", CANDIDATE_LABELS),
            ("semantic_register_stable", STRENGTH_BOOLEAN_LABELS),
            ("intensity_increased", STRENGTH_BOOLEAN_LABELS),
        ):
            if row.get(field_name) not in allowed:
                errors.append(
                    f"{where} {field_name}={row.get(field_name)!r} is impossible; "
                    f"allowed {list(allowed)}"
                )
                invalid = True
        key = (str(group), int(str(strength)))
        if key in seen_strength:
            errors.append(f"{where} duplicates an existing rating for {key}")
            continue
        seen_strength.add(key)
        if invalid:
            continue
        normalized_strength.append(
            {
                "sourceGroupId": group,
                "requestedStrength": int(str(strength)),
                "edit_usefulness": row.get("edit_usefulness"),
                "semantic_register_stable": row.get("semantic_register_stable"),
                "intensity_increased": row.get("intensity_increased"),
            }
        )

    normalized = {
        "raterId": document.get("raterId"),
        "packetId": document.get("packetId"),
        "packetSha256": document.get("packetSha256"),
        "preregistrationSha256": document.get("preregistrationSha256"),
        "rubricSha256": document.get("rubricSha256"),
        "pairRatings": normalized_pairs,
        "candidateRatings": normalized_candidates,
        "strengthRatings": normalized_strength,
    }
    if not normalized_pairs and not normalized_candidates and not normalized_strength:
        errors.append("rating document contains no ratings")
    if not normalized_pairs and pair_items:
        warnings.append("no pairwise criterion ratings submitted")

    return ValidationReport(ok=not errors, errors=errors, warnings=warnings, normalized=normalized)


# ---------------------------------------------------------------------------
# Analysis


def directional_score(label: str) -> float | None:
    """``None`` means both-unacceptable: counted, never averaged into a winner."""
    if label == "A":
        return 1.0
    if label == "B":
        return -1.0
    if label == "tie":
        return 0.0
    return None


def percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return float(sorted_values[low] * (1 - weight) + sorted_values[high] * weight)


def bootstrap_interval(
    values: Sequence[float], *, seed: str, label: str, resamples: int = 2000
) -> dict[str, Any]:
    """Deterministic percentile bootstrap over annotation-level paired scores."""
    if not values:
        return {
            "mean": None,
            "ciLow": None,
            "ciHigh": None,
            "n": 0,
            "resamples": 0,
            "assumptions": "no directional annotations; interval undefined",
        }
    if len(values) == 1:
        return {
            "mean": round(values[0], 6),
            "ciLow": round(values[0], 6),
            "ciHigh": round(values[0], 6),
            "n": 1,
            "resamples": 0,
            "assumptions": "single annotation; interval is degenerate",
        }
    rng = _rng(seed, "bootstrap", label)
    size = len(values)
    means: list[float] = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(size):
            total += values[rng.randrange(size)]
        means.append(total / size)
    means.sort()
    return {
        "mean": round(statistics.fmean(values), 6),
        "ciLow": round(percentile(means, 0.025), 6),
        "ciHigh": round(percentile(means, 0.975), 6),
        "n": size,
        "resamples": resamples,
        "assumptions": (
            "annotations treated as exchangeable draws from this packet's rater pool; "
            "descriptive interval, not a significance test"
        ),
    }


def fleiss_kappa(rows: Sequence[Sequence[str]], labels: Sequence[str]) -> dict[str, Any]:
    """Fleiss' kappa on a nominal label set, with its assumptions stated."""
    usable = [list(row) for row in rows if row]
    if len(usable) < 2:
        return {
            "kappa": None,
            "items": len(usable),
            "assumptions": "fewer than two items; kappa undefined",
        }
    label_set = list(labels)
    counts: list[list[int]] = []
    for row in usable:
        tally = [0] * len(label_set)
        for value in row:
            if value in label_set:
                tally[label_set.index(value)] += 1
        counts.append(tally)
    n_items = len(counts)
    n_raters = statistics.fmean([sum(row) for row in counts])
    if n_raters < 2:
        return {
            "kappa": None,
            "items": n_items,
            "assumptions": "fewer than two raters; kappa undefined",
        }
    p_i = [
        (sum(value * value for value in row) - n_raters) / (n_raters * (n_raters - 1))
        for row in counts
    ]
    p_bar = statistics.fmean(p_i)
    column_totals = [0.0] * len(label_set)
    for row in counts:
        for index, value in enumerate(row):
            column_totals[index] += value
    p_e = sum((total / (n_items * n_raters)) ** 2 for total in column_totals)
    if abs(1.0 - p_e) < 1e-12:
        return {
            "kappa": None,
            "items": n_items,
            "assumptions": (
                "every annotation used one label, so chance agreement is 1.0 and kappa "
                "is undefined; report percent agreement only"
            ),
        }
    return {
        "kappa": round((p_bar - p_e) / (1.0 - p_e), 6),
        "items": n_items,
        "assumptions": (
            "nominal scale; raters assumed exchangeable and independent; missing raters "
            "are treated as absent, not as disagreeing"
        ),
    }


def useful_depth(candidate_labels: Sequence[str], k: int) -> int:
    """Leading run of usable candidates, capped at ``k``. ``unclear`` breaks the run."""
    depth = 0
    for label in candidate_labels[:k]:
        if label != "usable":
            break
        depth += 1
    return depth


def analyze(
    preregistration: Mapping[str, Any],
    private_mapping: Mapping[str, Any],
    validated_ratings: Sequence[Mapping[str, Any]],
    *,
    seed: str,
    reveal_mapping: bool = True,
    bootstrap_resamples: int = 2000,
) -> dict[str, Any]:
    """Criterion-specific paired analysis; mapping is revealed only as the last step."""
    if not validated_ratings:
        raise HumanEvalContractError("analysis requires at least one validated rating document")

    shared_binding = {
        (doc["preregistrationSha256"], doc["rubricSha256"]) for doc in validated_ratings
    }
    if len(shared_binding) > 1:
        raise HumanEvalContractError(
            "refusing to pair ratings across different preregistration/rubric bindings: "
            f"{sorted(shared_binding)}"
        )
    frozen_prereg = preregistration["preregistrationSha256"]
    frozen_rubric = preregistration["protocol"]["rubricSha256"]
    mismatched = [
        doc["raterId"]
        for doc in validated_ratings
        if doc["preregistrationSha256"] != frozen_prereg or doc["rubricSha256"] != frozen_rubric
    ]
    if mismatched:
        raise HumanEvalContractError(
            f"ratings from {sorted(mismatched)} do not carry the frozen preregistration/rubric "
            "binding"
        )
    if private_mapping.get("preregistrationSha256") != frozen_prereg:
        raise HumanEvalContractError("private mapping does not belong to this preregistration")
    mapping_body = {key: value for key, value in private_mapping.items() if key != "mappingSha256"}
    if sha256_object(mapping_body) != private_mapping.get("mappingSha256"):
        raise HumanEvalContractError("private mapping digest does not match its contents")

    pair_lookup = {entry["pairId"]: entry for entry in private_mapping.get("pairs", [])}
    system_key_to_system = {
        entry["systemKey"]: entry for entry in private_mapping.get("systems", [])
    }
    depths = preregistration["policies"]["candidateDepthPolicy"]["depthsShown"]
    max_depth = preregistration["policies"]["candidateDepthPolicy"]["maxDepthShown"]

    exclusions, kept = _apply_exclusions(preregistration, validated_ratings)

    per_criterion: dict[str, Any] = {}
    by_criterion: dict[str, list[dict[str, Any]]] = {}
    route_views: dict[str, dict[str, dict[str, int]]] = {}
    mode_views: dict[str, dict[str, dict[str, int]]] = {}
    for doc in kept:
        for row in doc["pairRatings"]:
            by_criterion.setdefault(row["criterion"], []).append(
                {**row, "raterId": doc["raterId"]}
            )
            for bucket, key in ((route_views, row["route"]), (mode_views, row["semanticMode"])):
                bucket.setdefault(str(key), {}).setdefault(
                    row["criterion"], {label: 0 for label in PAIRWISE_LABELS}
                )
                bucket[str(key)][row["criterion"]][row["label"]] += 1

    for criterion in sorted(by_criterion):
        rows = by_criterion[criterion]
        counts = {label: 0 for label in PAIRWISE_LABELS}
        for row in rows:
            counts[row["label"]] += 1
        directional = [
            score for score in (directional_score(row["label"]) for row in rows) if score is not None
        ]
        raters = sorted({row["raterId"] for row in rows})
        per_criterion[criterion] = {
            "criterion": criterion,
            "wording": CRITERIA[criterion]["wording"],
            "rawCounts": counts,
            "annotationCount": len(rows),
            "raterCount": len(raters),
            "raterIds": raters,
            "directionalAnnotations": len(directional),
            "bothUnacceptableAnnotations": counts["both_unacceptable"],
            "bothUnacceptableNote": (
                "both-unacceptable rows are counted here and excluded from the "
                "directional mean; they are never converted into a winner"
            ),
            "directionalMean": round(statistics.fmean(directional), 6) if directional else None,
            "uncertainty": bootstrap_interval(
                directional,
                seed=seed,
                label=f"criterion:{criterion}",
                resamples=bootstrap_resamples,
            ),
        }

    coverage = _useful_coverage(kept, depths, max_depth, pair_lookup)
    disagreement_rows, reliability = _disagreement_and_reliability(kept)
    disagreeing = [row for row in disagreement_rows if row["disagreement"]]
    total_observations = len(disagreement_rows)

    revealed = None
    if reveal_mapping:
        revealed = {
            "revealedAt": "final analysis step only",
            "mappingSha256": private_mapping["mappingSha256"],
            "systems": {
                key: {"systemId": entry["systemId"], "revision": entry["revision"]}
                for key, entry in sorted(system_key_to_system.items())
            },
            "pairs": [
                {
                    "pairId": entry["pairId"],
                    "systemA": entry["systemKeyA"],
                    "systemB": entry["systemKeyB"],
                }
                for entry in private_mapping.get("pairs", [])
            ],
        }

    return {
        "schemaVersion": ANALYSIS_SCHEMA_VERSION,
        "evaluationId": preregistration["evaluationId"],
        "preregistrationSha256": frozen_prereg,
        "rubricSha256": frozen_rubric,
        "packetBindings": sorted(
            [{"raterId": doc["raterId"], "packetSha256": doc["packetSha256"]} for doc in validated_ratings],
            key=lambda item: item["raterId"],
        ),
        "evidenceStatus": (
            "analysis over schema-validated human ratings; no ratings have been collected "
            "in this repository yet"
        ),
        "raterCount": len({doc["raterId"] for doc in validated_ratings}),
        "analysedRaterCount": len(kept),
        "raterPolicy": preregistration["policies"]["raterEligibilityPolicy"],
        "perCriterion": [per_criterion[key] for key in sorted(per_criterion)],
        "perRoute": {route: route_views[route] for route in sorted(route_views)},
        "perSemanticMode": {mode: mode_views[mode] for mode in sorted(mode_views)},
        "usefulCandidateCoverage": [coverage[str(k)] for k in sorted(coverage, key=int)],
        "disagreement": {
            "itemCriterionObservations": total_observations,
            "disagreeingObservations": len(disagreeing),
            "disagreementRate": (
                round(len(disagreeing) / total_observations, 6) if total_observations else None
            ),
            "highDisagreementExamples": sorted(
                disagreeing,
                key=lambda row: (
                    -len(row["distinctLabels"]),
                    -row["raterCount"],
                    row["pairId"],
                    row["criterion"],
                ),
            )[:20],
            "note": (
                "disagreement is reported, never adjudicated into a single score; items "
                "are named by opaque pair ID only"
            ),
        },
        "reliability": reliability,
        "strengthTrajectories": _analyze_strength(kept),
        "exclusions": exclusions,
        "collapsedScalar": None,
        "collapsedScalarNote": (
            "intentionally absent: no universal winner and no opaque product scalar; "
            "route-specific Pareto evidence is the deliverable"
        ),
        "blindingReveal": revealed,
    }


def _apply_exclusions(
    preregistration: Mapping[str, Any], validated_ratings: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[Mapping[str, Any]]]:
    """Preregistered exclusions are applied; everything else is surfaced as exploratory."""
    preregistered_rule_ids = {
        rule["id"]
        for rule in preregistration["policies"]["raterEligibilityPolicy"]["preregisteredExclusionRules"]
    }
    exclusions: list[dict[str, Any]] = []
    kept: list[Mapping[str, Any]] = []
    for doc in validated_ratings:
        submitted = {row["pairId"] for row in doc["pairRatings"]}
        if not submitted:
            matched = [rule for rule in ("incomplete",) if rule in preregistered_rule_ids]
            exclusions.append(
                {
                    "raterId": doc["raterId"],
                    "reasons": ["incomplete"],
                    "ruleIds": matched,
                    "status": "preregistered" if matched else "exploratory",
                    "note": (
                        "an exclusion without a preregistered rule is reported as "
                        "exploratory, never silently accepted"
                    ),
                }
            )
            continue
        kept.append(doc)
    return exclusions, kept


def _useful_coverage(
    kept: Sequence[Mapping[str, Any]],
    depths: Sequence[int],
    max_depth: int,
    pair_lookup: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Reconstruct top-k useful-candidate coverage per blinded system."""
    per_k: dict[str, Any] = {}
    for k in sorted(depths, reverse=True):
        per_system: dict[str, dict[str, Any]] = {}
        observations = 0
        at_least_k = 0
        for doc in kept:
            prefixes: dict[tuple[str, str], list[str]] = {}
            for row in doc["candidateRatings"]:
                side_key = (row["pairId"], row["side"])
                prefix = prefixes.get(side_key)
                if prefix is None:
                    ordered = sorted(
                        (
                            r
                            for r in doc["candidateRatings"]
                            if r["pairId"] == row["pairId"] and r["side"] == row["side"]
                        ),
                        key=lambda r: int(r["candidateId"]),
                    )
                    prefix = [str(entry["label"]) for entry in ordered]
                    prefixes[side_key] = prefix
                entry = pair_lookup.get(row["pairId"])
                if not entry:
                    continue
                # Attribute each displayed side to the blinded finalist that the
                # private mapping says produced it. This happens only here, in
                # analysis, after the reveal is authorised.
                system_key = entry["systemKeyA"] if row["side"] == "A" else entry["systemKeyB"]
                depth_value = useful_depth(prefix, k)
                bucket = per_system.setdefault(
                    system_key, {"taskObservations": 0, "atLeastK": 0, "depths": []}
                )
                bucket["depths"].append(depth_value)
                bucket["taskObservations"] += 1
                observations += 1
                if depth_value >= k:
                    bucket["atLeastK"] += 1
                    at_least_k += 1
        for bucket in per_system.values():
            values = bucket.pop("depths")
            bucket["meanUsefulDepth"] = round(statistics.fmean(values), 6) if values else None
            bucket["coverageRate"] = (
                round(bucket["atLeastK"] / bucket["taskObservations"], 6)
                if bucket["taskObservations"]
                else None
            )
        per_k[str(k)] = {
            "depth": k,
            "observations": observations,
            "atLeastK": at_least_k,
            "overallCoverageRate": round(at_least_k / observations, 6) if observations else None,
            "perSystem": dict(sorted(per_system.items())),
            "candidatesShownPerSide": max_depth,
        }
    return per_k


def _disagreement_and_reliability(
    kept: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labels_by_item: dict[tuple[str, str], dict[str, str]] = {}
    for doc in kept:
        for row in doc["pairRatings"]:
            labels_by_item.setdefault((row["pairId"], row["criterion"]), {})[doc["raterId"]] = row[
                "label"
            ]
    rows = [
        {
            "pairId": pair_id,
            "criterion": criterion,
            "raterCount": len(labels),
            "distinctLabels": sorted(set(labels.values())),
            "disagreement": len(set(labels.values())) > 1,
        }
        for (pair_id, criterion), labels in sorted(labels_by_item.items())
    ]

    reliability: dict[str, Any] = {}
    for criterion in sorted({criterion for _, criterion in labels_by_item}):
        raters = sorted(
            {
                rater
                for (pair_id, item_criterion), labels in labels_by_item.items()
                if item_criterion == criterion
                for rater in labels
            }
        )
        table: list[list[str]] = []
        for pair_id, item_criterion in sorted(labels_by_item):
            if item_criterion != criterion:
                continue
            labels = labels_by_item[(pair_id, item_criterion)]
            table.append([labels.get(rater, "__absent__") for rater in raters])
        comparable = [row for row in table if all(value != "__absent__" for value in row)]
        reliability[criterion] = {
            "percentAgreement": (
                round(
                    statistics.fmean(
                        [
                            max(row.count(label) for label in PAIRWISE_LABELS) / len(row)
                            for row in comparable
                        ]
                    ),
                    6,
                )
                if comparable
                else None
            ),
            "fleissKappa": fleiss_kappa(table, list(PAIRWISE_LABELS)),
            "raterCount": len(raters),
            "itemCount": sum(1 for _, item_criterion in labels_by_item if item_criterion == criterion),
        }
    return rows, reliability


def _analyze_strength(kept: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per-source trajectories: never average a non-monotonic failure away."""
    grouped: dict[str, dict[int, list[Mapping[str, Any]]]] = {}
    for doc in kept:
        for row in doc.get("strengthRatings", []):
            grouped.setdefault(row["sourceGroupId"], {}).setdefault(
                int(row["requestedStrength"]), []
            ).append(row)
    trajectories: list[dict[str, Any]] = []
    for group_id in sorted(grouped):
        steps: list[dict[str, Any]] = []
        for strength in STRENGTH_LEVELS:
            rows = grouped[group_id].get(strength, [])
            if not rows:
                continue
            useful = [row["edit_usefulness"] for row in rows]
            stable = [row["semantic_register_stable"] for row in rows]
            inflated = [row["intensity_increased"] for row in rows]
            steps.append(
                {
                    "requestedStrength": strength,
                    "annotationCount": len(rows),
                    "usefulRate": round(useful.count("usable") / len(useful), 6),
                    "notUsefulRate": round(useful.count("not_usable") / len(useful), 6),
                    "unclearRate": round(useful.count("unclear") / len(useful), 6),
                    "semanticRegisterStableRate": round(stable.count("yes") / len(stable), 6),
                    "intensityIncreasedRate": round(inflated.count("yes") / len(inflated), 6),
                }
            )
        usefulness = [step["usefulRate"] for step in steps]
        stability = [step["semanticRegisterStableRate"] for step in steps]
        intensity = [step["intensityIncreasedRate"] for step in steps]
        trajectories.append(
            {
                "sourceGroupId": group_id,
                "steps": steps,
                "usefulRateNonMonotonic": usefulness != sorted(usefulness, reverse=True),
                "stabilityDropsWithStrength": any(
                    later < earlier for earlier, later in zip(stability, stability[1:])
                ),
                "intensityRisesWithStrength": any(
                    later > earlier for earlier, later in zip(intensity, intensity[1:])
                ),
                "note": (
                    "the trajectory is kept per source; a failing source is reported, not "
                    "smoothed into an average"
                ),
            }
        )
    return {
        "levels": list(STRENGTH_LEVELS),
        "sourceGroupCount": len(trajectories),
        "trajectories": trajectories,
        "changeDiagnosticsNote": (
            "deterministic change diagnostics are combined with human usefulness and "
            "semantic judgments; edit distance alone is never treated as quality"
        ),
    }


__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "CRITERIA",
    "HumanEvalContractError",
    "MAPPING_SCHEMA_VERSION",
    "PACKET_SCHEMA_VERSION",
    "PREREGISTRATION_SCHEMA_VERSION",
    "RATING_SCHEMA_VERSION",
    "RUBRIC",
    "ValidationReport",
    "analyze",
    "atomic_write",
    "bootstrap_interval",
    "build_comparisons",
    "build_packets",
    "build_preregistration",
    "build_strength_tasks",
    "candidates_for_task",
    "canonical_bytes",
    "canonical_json",
    "change_diagnostics",
    "criteria_for_task",
    "directional_score",
    "document_bytes",
    "fleiss_kappa",
    "load_inputs",
    "rating_schema",
    "scan_for_leaks",
    "semantic_mode_of",
    "sha256_bytes",
    "sha256_file",
    "sha256_object",
    "system_public_tokens",
    "useful_depth",
    "validate_rating_document",
]
