#!/usr/bin/env python3
"""Canonical stage to frozen task identity contract (Issue #48).

One machine-readable register binds every canonical stage to the exact task
artifact bytes it is allowed to consume. Wrappers resolve their task file
through this module, so a `--tasks` path can never silently make an edited or
swapped suite promotion-valid: an unregistered path resolves to a distinct
exploratory identity that carries an explicit non-promotion marker.

Resolution outcome for one stage request:

* `canonical` - the registered artifact, bound to the stage's frozen count;
* `exploratory` - an unregistered override, explicitly non-promotion and
  non-comparable, still carrying its own hash so evidence stays auditable;
* a raised contract error for a registered path whose bytes drifted.

This module also carries the frozen batch policy (Issue #47) so a product
stage can never walk the generation ladder.

Generated stages are frozen by :mod:`prepare-kaggle-benchmark.py` instead of
being committed. After deterministic preparation it records the screen's
artifact SHA-256, task count, ordered task-ID SHA-256, and the registered Q3
prefix ordered-ID SHA-256 in ``receipt.preparedStageRegister``. Resolution for
such a stage accepts that prepared register and nothing else, so an edited,
swapped, or rebuilt screen cannot become promotion-valid by path alone.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kaggle_run_checkpoint as K

HERE = Path(__file__).resolve().parent

#: The one canonical register lives in kaggle-stage-manifest.json (Issue #48/#49).
#: It is data, not code, so wrappers, validators and the candidate matrix all read
#: the same frozen hashes, counts and subset rules without restating them.
REGISTER_PATH = HERE / "kaggle-stage-manifest.json"

#: Preparation receipt that carries the prepared stage register for generated
#: artifacts, and binds it to the bundled register file. Preparation writes it
#: to this path by default, and both the roster and the candidate wrapper default
#: ``--preparation-receipt`` to it, so the freeze is discovered without restating
#: it per wrapper.
DEFAULT_PREPARATION_RECEIPT = Path("/kaggle/working/results/benchmark-preparation.json")

#: Environment override so an operator can point resolution at the exact
#: preparation receipt whose freeze should be honoured.
PREPARATION_RECEIPT_ENV = "PARI_KAGGLE_PREPARATION_RECEIPT"

#: Receipt key holding the prepared-register binding block.
PREPARED_REGISTER_KEY = "preparedStageRegister"

#: The prepared stage register itself: a top-level bundled file written by
#: prepare-kaggle-benchmark.py after the deterministic build. It sits next to the
#: checked-in stage manifest, so the candidate bundle copy drops it straight into
#: the cloned benchmark directory where this module resolves a generated stage.
#: Preparation also writes a copy beside the receipt; whichever copy is used, a
#: bundled copy is only honoured when the preparation receipt binds its digest.
PREPARED_REGISTER_FILENAME = "kaggle-stage-manifest.prepared.json"
PREPARED_REGISTER_PATH = HERE / PREPARED_REGISTER_FILENAME

def _load_register() -> dict[str, Any]:
    if not REGISTER_PATH.is_file():
        raise K.CheckpointError(f"canonical stage manifest is missing: {REGISTER_PATH}")
    payload = json.loads(REGISTER_PATH.read_text(encoding="utf-8"))
    if int(payload.get("manifestVersion") or 0) < 2:
        raise K.CheckpointError(
            f"canonical stage manifest version {payload.get('manifestVersion')!r} is too old; "
            "the qualification ladder requires manifestVersion >= 2"
        )
    if not isinstance(payload.get("stages"), dict) or not payload["stages"]:
        raise K.CheckpointError("canonical stage manifest declares no stages")
    if not isinstance(payload.get("qualificationLadder"), list) or not payload["qualificationLadder"]:
        raise K.CheckpointError("canonical stage manifest declares no qualification ladder")
    return payload


def stage_manifest_sha256() -> str:
    """Digest of the register file itself, bound into every candidate summary."""
    return K.sha256_file(REGISTER_PATH)


def preparation_receipt_path() -> Path:
    """The preparation receipt whose prepared stage register is authoritative.

    Resolution never guesses between two freezes: an explicit path or the
    environment override wins outright, and otherwise the single canonical
    preparation receipt path is used. A receipt that does not exist simply means
    preparation has not run, which fails closed for generated stages.
    """
    override = os.environ.get(PREPARATION_RECEIPT_ENV)
    return Path(override) if override else DEFAULT_PREPARATION_RECEIPT


def uses_prepared_identity(stage: str) -> bool:
    """Whether this stage's identity comes from the prepared register.

    A generated stage is one whose bytes cannot be committed (the 1,943-case
    screen is assembled from upstream dataset pulls at preparation time), so
    its frozen identity is the prepared register rather than the checked-in
    register's still-null hash fields.
    """
    return stage_entry(stage).get("identitySource") == "prepared-register"


def _read_json(path: Path, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise K.CheckpointError(f"{what} {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise K.CheckpointError(f"{what} {path} is not a JSON object")
    return payload


def load_prepared_register(
    receipt: Path | str | None = None,
) -> tuple[dict[str, Any] | None, Path | None]:
    """Load the prepared stage register bound to this exact stage manifest.

    The register file is the resolution source, never a task path: a generated
    stage resolves only when preparation froze it. The candidate bundle copies
    the register next to the checked-in stage manifest, so the bundled copy in
    the cloned benchmark directory is the usual source; preparation also writes a
    copy beside the receipt. A copy found inside the benchmark tree is honoured
    only when a preparation receipt binds its exact digest, so an unvetted file
    dropped into the tree cannot freeze a stage.

    Returns ``(register, receipt_path)``; ``register`` is ``None`` only when
    preparation has not run. A register that exists but disagrees with the
    checked-in manifest or the receipt is a contract failure, not a cache miss.
    """
    receipt_path = Path(receipt) if receipt is not None else preparation_receipt_path()
    receipt_payload: dict[str, Any] | None = None
    if receipt_path.is_file():
        receipt_payload = _read_json(receipt_path, "preparation receipt")

    path: Path | None = None
    bundled = PREPARED_REGISTER_PATH.is_file()
    for candidate in (PREPARED_REGISTER_PATH, receipt_path.parent / PREPARED_REGISTER_FILENAME):
        if candidate.is_file():
            path = candidate
            break
    if path is None:
        return None, receipt_path

    register = _read_json(path, "prepared stage register")
    if not isinstance(register.get("stages"), dict) or not register["stages"]:
        raise K.CheckpointError(
            f"prepared stage register {path} declares no stages; "
            "a generated stage cannot be resolved from it"
        )
    bound_manifest = register.get("stageManifestSha256")
    if bound_manifest != stage_manifest_sha256():
        raise K.CheckpointError(
            f"prepared stage register {path.name} is bound to stage manifest "
            f"{bound_manifest!r}, not the checked-in "
            f"{stage_manifest_sha256()!r}; re-run benchmark preparation against "
            "this exact stage manifest"
        )
    if receipt_payload is not None:
        _verify_receipt_binding(register, receipt_payload, receipt_path, path, bundled)
    elif bundled:
        raise K.CheckpointError(
            f"prepared stage register {path.name} sits in the benchmark tree but no "
            f"preparation receipt at {receipt_path} binds it; an unvetted register "
            "cannot freeze a generated stage. Pass --preparation-receipt."
        )
    return register, receipt_path


def _verify_receipt_binding(
    register: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    register_path: Path,
    from_benchmark_tree: bool,
) -> None:
    """Require the preparation receipt to agree with the prepared register."""
    binding = receipt.get(PREPARED_REGISTER_KEY)
    if not isinstance(binding, dict):
        raise K.CheckpointError(
            f"preparation receipt {receipt_path} has no {PREPARED_REGISTER_KEY} block, "
            "so it cannot vouch for a generated stage's frozen identity"
        )
    if from_benchmark_tree:
        recorded = binding.get("fileSha256")
        actual = K.sha256_file(register_path)
        if not recorded or recorded != actual:
            raise K.CheckpointError(
                f"prepared stage register {register_path.name} has digest {actual!r}, "
                f"but preparation receipt {receipt_path} froze {recorded!r}; the bundled "
                "register does not match the freeze"
            )
    if binding.get("stageManifestSha256") != register.get("stageManifestSha256"):
        raise K.CheckpointError(
            f"preparation receipt {receipt_path} binds the prepared register to stage "
            f"manifest {binding.get('stageManifestSha256')!r}, but the register itself "
            f"claims {register.get('stageManifestSha256')!r}"
        )
    if binding.get("benchmarkRevision") != receipt.get("benchmarkRevision"):
        raise K.CheckpointError(
            f"prepared register in receipt {receipt_path} was frozen for benchmark "
            f"revision {binding.get('benchmarkRevision')!r} but the receipt records "
            f"{receipt.get('benchmarkRevision')!r}"
        )
    frozen_stages = binding.get("stages")
    if not isinstance(frozen_stages, dict):
        raise K.CheckpointError(
            f"preparation receipt {receipt_path} {PREPARED_REGISTER_KEY} carries no "
            "per-stage freeze"
        )
    if frozen_stages != register.get("stages"):
        raise K.CheckpointError(
            f"prepared stage register {register_path.name} does not match the per-stage "
            f"freeze recorded in {receipt_path}"
        )


def prepared_stage_entry(
    stage: str, receipt: Path | str | None = None
) -> tuple[dict[str, Any] | None, Path | None]:
    """The prepared identity record for one generated stage, if one was frozen."""
    register, path = load_prepared_register(receipt)
    if register is None:
        return None, path
    stages = register["stages"]
    if stage not in stages:
        return None, path
    entry = stages[stage]
    if not isinstance(entry, dict):
        raise K.CheckpointError(
            f"prepared stage register in {path} has a non-object entry for stage {stage!r}"
        )
    entry_stage = stage_entry(stage)
    if entry.get("path") != entry_stage["path"]:
        raise K.CheckpointError(
            f"prepared stage register in {path} freezes stage {stage!r} at "
            f"{entry.get('path')!r}, but the checked-in register declares "
            f"{entry_stage['path']!r}"
        )
    if int(entry.get("subsetPrefixCount") or 0) != int(
        entry_stage.get("subsetPrefixCount") or 0
    ):
        raise K.CheckpointError(
            f"prepared stage register in {path} freezes a {entry.get('subsetPrefixCount')!r}-"
            f"case prefix for stage {stage!r}, but the checked-in register declares "
            f"{entry_stage.get('subsetPrefixCount')!r}"
        )
    return entry, path


def _require_prepared_digest(
    value: Any, stage: str, field: str, receipt_path: Path | None
) -> str:
    """Read one frozen digest out of the prepared register, failing closed."""
    digest = value if isinstance(value, str) else None
    if not digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise K.CheckpointError(
            f"prepared stage register for stage {stage!r} is missing a valid "
            f"{field} ({receipt_path}); a generated stage cannot be promotion-valid "
            "without its frozen identity"
        )
    return digest


#: Canonical stage identity, loaded from the single register file.
STAGE_MANIFEST: dict[str, dict[str, Any]] = {
    stage: {**entry, "stage": stage}
    for stage, entry in _load_register()["stages"].items()
}

#: Ordered qualification ladder (Issue #49). Each gate names its receipt key, the
#: stage it runs, and the earlier gates it requires, so Q4 cannot start before a
#: completed Q1->Q3 chain and the matrix can report the exact gate reached.
QUALIFICATION_LADDER: list[dict[str, Any]] = _load_register()["qualificationLadder"]

#: Stage -> qualification gate, derived from the same register.
STAGE_GATE_MAP: dict[str, str] = {
    stage: str(entry["gate"]) for stage, entry in STAGE_MANIFEST.items()
}

#: Product stages are pinned to a single frozen batch size and never walk the
#: generation ladder (Issue #47).
PRODUCT_STAGES = frozenset({"word-studio", "transform"})

#: Frozen generation-ladder order for canonical English stages (Issue #47).
GENERATION_LADDER = (64, 32, 16, 8, 4, 1)


@dataclass(frozen=True)
class TaskIdentity:
    """Resolved task identity for one stage request."""

    stage: str
    path: str
    kind: str
    promotion_eligible: bool
    comparable: bool
    sha256: str | None
    expected_count: int | None
    ids_sha256: str | None
    parser_contract: str
    batch_policy: str
    subset_rule: str | None
    reason: str
    subset_of: str | None = None
    subset_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "taskPath": self.path,
            "identityKind": self.kind,
            "promotionEligible": self.promotion_eligible,
            "comparable": self.comparable,
            "taskSha256": self.sha256,
            "expectedTaskCount": self.expected_count,
            "orderedTaskIdsSha256": self.ids_sha256,
            "parserContract": self.parser_contract,
            "batchPolicy": self.batch_policy,
            "subsetRule": self.subset_rule,
            "subsetOf": self.subset_of,
            "subsetTaskCount": self.subset_count,
            "reason": self.reason,
        }


def stage_entry(stage: str) -> dict[str, Any]:
    if stage not in STAGE_MANIFEST:
        raise K.CheckpointError(
            f"unknown stage {stage!r}; registered stages: {sorted(STAGE_MANIFEST)}"
        )
    return STAGE_MANIFEST[stage]


def canonical_path(stage: str) -> Path:
    return HERE / stage_entry(stage)["path"]


def ordered_ids_sha256(ids: list[str] | tuple[str, ...]) -> str:
    """Stable digest of the ordered task-ID list.

    Reordering the same IDs changes this digest, so an out-of-order suite can
    never satisfy the canonical contract.
    """
    return K.sha256_json({"orderedTaskIds": list(ids)})


def frozen_subset_ids(stage: str) -> list[str] | None:
    """The registered ordered task IDs a subset stage consumes.

    A subset is defined by an explicit frozen prefix rule recorded in the
    register, so its identity is hashable and cannot drift with whatever the
    current artifact's "first N" happens to be.
    """
    entry = stage_entry(stage)
    if not entry.get("subsetOf"):
        return None
    parent = canonical_path(str(entry["subsetOf"]))
    prefix_count = int(entry["subsetPrefixCount"])
    if not parent.is_file():
        return None
    ids = list(K.load_task_manifest(parent, str(entry["subsetOf"])).ids)
    if len(ids) < prefix_count:
        raise K.CheckpointError(
            f"subset stage {stage!r} needs the first {prefix_count} IDs of "
            f"{parent.name} but that artifact only has {len(ids)}"
        )
    return ids[:prefix_count]


def frozen_subset_ids_sha256(stage: str) -> str | None:
    """Digest of a subset stage's frozen ordered ID list."""
    ids = frozen_subset_ids(stage)
    return None if ids is None else ordered_ids_sha256(ids)


def frozen_hash_register() -> dict[str, Any]:
    """Registered artifact identity, computed from the files on disk.

    Wrappers, checkpoints, and matrix validation all consume this one source of
    truth, so no script has to restate the constants.
    """
    register: dict[str, Any] = {"version": 1, "stages": {}}
    for stage, entry in STAGE_MANIFEST.items():
        path = canonical_path(stage)
        record: dict[str, Any] = {
            "stage": stage,
            "gate": entry["gate"],
            "path": entry["path"],
            "expectedCount": entry["expectedCount"],
            "subsetRule": entry["subsetRule"],
            "subsetOf": entry.get("subsetOf"),
            "subsetPrefixCount": entry.get("subsetPrefixCount"),
            "parserContract": entry["parserContract"],
            "batchPolicy": entry["batchPolicy"],
            "registeredArtifactSha256": entry.get("artifactSha256"),
            "artifactSha256": K.sha256_file(path),
            "artifactPresent": path.is_file(),
        }
        if path.is_file():
            manifest = K.load_task_manifest(path, entry["path"])
            record["actualCount"] = len(manifest.ids)
            record["orderedTaskIdsSha256"] = ordered_ids_sha256(manifest.ids)
            record["artifactIdentityMatches"] = (
                record["artifactSha256"] == entry.get("artifactSha256")
                if entry.get("artifactSha256")
                else None
            )
        if entry.get("identitySource") == "prepared-register":
            # A generated stage's frozen identity is the prepared register, so
            # report whether preparation has frozen these exact bytes rather than
            # reporting the still-null checked-in hashes as an unexplained gap.
            record["identitySource"] = "prepared-register"
            frozen, receipt_path = prepared_stage_entry(stage)
            record["preparedFreezePresent"] = frozen is not None
            record["preparationReceipt"] = str(receipt_path) if receipt_path else None
            if frozen is not None:
                record["preparedArtifactSha256"] = frozen.get("artifactSha256")
                record["preparedTaskCount"] = frozen.get("taskCount")
                record["preparedOrderedTaskIdsSha256"] = frozen.get("orderedTaskIdsSha256")
                if frozen.get("subsetOrderedTaskIdsSha256"):
                    record["preparedSubsetIdsSha256"] = frozen.get("subsetOrderedTaskIdsSha256")
                record["artifactIdentityMatches"] = (
                    record["artifactSha256"] == frozen.get("artifactSha256")
                    if path.is_file()
                    else None
                )
        if entry.get("subsetOf"):
            record["frozenSubsetIdsSha256"] = frozen_subset_ids_sha256(stage)
        register["stages"][stage] = record
    register["registerSha256"] = K.sha256_json(register["stages"])
    return register


def register_sha256() -> str:
    """Digest of the whole stage register; bind this into every summary."""
    return str(frozen_hash_register()["registerSha256"])


def resolve_stage_tasks(
    stage: str,
    override: Path | str | None = None,
    *,
    promotion_run: bool = True,
    preparation_receipt: Path | str | None = None,
) -> TaskIdentity:
    """Resolve the task artifact identity a stage request is allowed to use.

    A registered path whose bytes drifted is a hard contract failure. An
    unregistered override is allowed only as an explicitly non-promotion,
    non-comparable exploratory identity. A generated stage additionally
    requires the freeze preparation recorded for the exact artifact bytes,
    count, and ordered task IDs, so it is promotion-valid only as prepared.
    """
    entry = stage_entry(stage)
    registered = canonical_path(stage)
    parser_contract = str(entry["parserContract"])
    batch_policy = str(entry["batchPolicy"])
    subset_rule = entry["subsetRule"]
    subset_of = entry.get("subsetOf")
    subset_count = entry.get("subsetPrefixCount")
    prepared_entry: dict[str, Any] | None = None
    receipt_path: Path | None = None
    if uses_prepared_identity(stage):
        prepared_entry, receipt_path = prepared_stage_entry(stage, preparation_receipt)

    if override is None or Path(override) == registered:
        if not registered.is_file():
            raise K.CheckpointError(
                f"canonical task artifact for stage {stage!r} is missing: {registered}"
            )
        actual = K.load_task_manifest(registered, entry["path"])
        if subset_of:
            # A registered frozen subset: identity is the frozen ordered-ID
            # prefix, not the parent artifact's full count.
            frozen = frozen_subset_ids(stage)
            if frozen is None:
                raise K.CheckpointError(
                    f"subset stage {stage!r} cannot resolve its frozen prefix from "
                    f"{registered}; refusing an incidental subset"
                )
            expected_ids_sha = frozen_subset_ids_sha256(stage)
            frozen_count = int(subset_count or len(frozen))
            prefix_sha = None
            if prepared_entry is not None:
                prefix_sha = _require_prepared_digest(
                    prepared_entry.get("subsetOrderedTaskIdsSha256"),
                    stage,
                    "subsetOrderedTaskIdsSha256",
                    receipt_path,
                )
                if int(prepared_entry.get("subsetPrefixCount") or 0) != frozen_count:
                    raise K.CheckpointError(
                        f"prepared freeze for stage {stage!r} registers a "
                        f"{prepared_entry.get('subsetPrefixCount')!r}-case prefix but the "
                        f"checked-in register declares {frozen_count}"
                    )
                if prefix_sha != expected_ids_sha:
                    raise K.CheckpointError(
                        f"prepared Q3 prefix for stage {stage!r} does not match the "
                        f"registered ordered IDs: prepared {prefix_sha} != on-disk "
                        f"{expected_ids_sha}"
                    )
            return TaskIdentity(
                stage=stage,
                path=str(registered),
                kind="canonical-subset-prepared" if prepared_entry is not None else "canonical-subset",
                promotion_eligible=True,
                comparable=True,
                sha256=actual.sha256,
                expected_count=len(frozen),
                ids_sha256=expected_ids_sha,
                parser_contract=parser_contract,
                batch_policy=batch_policy,
                subset_rule=subset_rule,
                reason=(
                    f"prepared frozen subset: first {len(frozen)} ordered IDs of "
                    f"{registered.name}"
                    if prepared_entry is not None
                    else f"registered frozen subset: first {len(frozen)} ordered IDs of "
                    f"{registered.name}"
                ),
                subset_of=str(subset_of),
                subset_count=frozen_count,
            )
        expected_count = int(entry["expectedCount"])
        frozen_count = int(prepared_entry.get("taskCount") or 0) if prepared_entry is not None else None
        effective_count = frozen_count if frozen_count is not None else expected_count
        if len(actual.ids) != effective_count:
            raise K.CheckpointError(
                f"canonical task artifact for stage {stage!r} has {len(actual.ids)} "
                f"tasks, expected {effective_count}"
            )
        actual_ids_sha = ordered_ids_sha256(actual.ids)
        registered_sha = entry.get("artifactSha256")
        registered_ids_sha = entry.get("orderedTaskIdsSha256")
        if prepared_entry is not None:
            registered_sha = _require_prepared_digest(
                prepared_entry.get("artifactSha256"), stage, "artifactSha256", receipt_path
            )
            registered_ids_sha = _require_prepared_digest(
                prepared_entry.get("orderedTaskIdsSha256"),
                stage,
                "orderedTaskIdsSha256",
                receipt_path,
            )
        if registered_sha and actual.sha256 != registered_sha:
            raise K.CheckpointError(
                f"canonical task artifact for stage {stage!r} drifted from the frozen "
                f"register: on-disk {actual.sha256} != registered {registered_sha}"
            )
        if registered_ids_sha and actual_ids_sha != registered_ids_sha:
            raise K.CheckpointError(
                f"canonical task ID order for stage {stage!r} drifted from the frozen "
                f"register: {actual_ids_sha} != {registered_ids_sha}"
            )
        return TaskIdentity(
            stage=stage,
            path=str(registered),
            kind="canonical-prepared" if prepared_entry is not None else "canonical",
            promotion_eligible=True,
            comparable=True,
            sha256=actual.sha256,
            expected_count=effective_count,
            ids_sha256=actual_ids_sha,
            parser_contract=parser_contract,
            batch_policy=batch_policy,
            subset_rule=subset_rule,
            reason=(
                f"prepared canonical task artifact, frozen by preparation against "
                f"stage register {stage_manifest_sha256()}"
                if prepared_entry is not None
                else "registered canonical task artifact"
            ),
            subset_of=str(subset_of) if subset_of else None,
            subset_count=int(subset_count) if subset_of else None,
        )

    override_path = Path(override)
    if not override_path.is_file():
        raise K.CheckpointError(f"task override does not exist: {override_path}")
    if not promotion_run:
        return _exploratory(
            stage, override_path, parser_contract, batch_policy, subset_rule,
            "explicit non-promotion exploratory run",
        )
    raise K.CheckpointError(
        f"unregistered task override for stage {stage!r}: {override_path} is not the "
        f"canonical artifact {registered}; an arbitrary path cannot become "
        "promotion-valid. Re-run as an explicitly exploratory (non-promotion) unit "
        "or register a predeclared alternate identity."
    )


def require_prepared_stage(stage: str, receipt: Path | str | None = None) -> dict[str, Any]:
    """The frozen identity preparation recorded for a generated stage.

    Callers that only want to assert the freeze exists -- a matrix validator, a
    preparation verifier, or a runbook self-check -- use this instead of
    duplicating the receipt lookup and its fail-closed rules.
    """
    if not uses_prepared_identity(stage):
        raise K.CheckpointError(
            f"stage {stage!r} is not a generated stage; it is frozen by the "
            "checked-in register, not by benchmark preparation"
        )
    entry, receipt_path = prepared_stage_entry(stage, receipt)
    if entry is None:
        raise K.CheckpointError(
            f"stage {stage!r} has no prepared freeze; benchmark preparation must run "
            f"before this stage, and its register is read from {PREPARED_REGISTER_PATH.name} "
            f"or beside the preparation receipt ({preparation_receipt_path()})"
        )
    return entry


def _exploratory(
    stage: str,
    path: Path,
    parser_contract: str,
    batch_policy: str,
    subset_rule: str | None,
    reason: str,
) -> TaskIdentity:
    manifest = K.load_task_manifest(path, "exploratory")
    return TaskIdentity(
        stage=stage,
        path=str(path),
        kind="exploratory",
        promotion_eligible=False,
        comparable=False,
        sha256=manifest.sha256,
        expected_count=None,
        ids_sha256=ordered_ids_sha256(manifest.ids),
        parser_contract=f"{parser_contract}+exploratory",
        batch_policy=batch_policy,
        subset_rule=subset_rule,
        reason=reason,
    )


def canonical_batch_policy(stage: str) -> str:
    """Frozen batch policy for a stage (Issue #47)."""
    entry = stage_entry(stage)
    return (
        "single-batch-1" if entry["batchPolicy"] == "single-batch" else "generation-ladder"
    )


# ---------------------------------------------------------------------------
# Qualification ladder (Issue #49)


def gate_for_stage(stage: str) -> str:
    """The qualification gate a stage satisfies, e.g. `smoke` -> `q2`."""
    return str(stage_entry(stage)["gate"])


def gate_spec(gate: str) -> dict[str, Any]:
    for entry in QUALIFICATION_LADDER:
        if entry["gate"] == gate:
            return entry
    raise K.CheckpointError(
        f"unknown qualification gate {gate!r}; registered gates: "
        f"{[e['gate'] for e in QUALIFICATION_LADDER]}"
    )


def gate_order(gate: str) -> int:
    for index, entry in enumerate(QUALIFICATION_LADDER):
        if entry["gate"] == gate:
            return index
    raise K.CheckpointError(f"unknown qualification gate {gate!r}")


def required_prior_gates(gate: str) -> list[str]:
    """Every gate that must already hold before `gate` may be attempted."""
    spec = gate_spec(gate)
    return list(spec["requires"])


def gate_satisfied(gate: str, completed_gates: set[str]) -> tuple[bool, list[str]]:
    """Whether `gate`'s prerequisites are met, plus the missing gate list."""
    missing = [prior for prior in required_prior_gates(gate) if prior not in completed_gates]
    return (not missing), missing


def highest_gate_reached(
    stage_receipts: dict[str, Any],
) -> dict[str, Any]:
    """Report the exact highest qualification gate the evidence actually reaches.

    `stage_receipts` maps receipt key -> receipt status. The matrix uses this so a
    single ambiguous `smoke` cell cannot hide a Q1-only or Q3-only result.
    """
    reached: list[str] = []
    for entry in QUALIFICATION_LADDER:
        receipt = stage_receipts.get(entry["receiptKey"])
        status = receipt.get("status") if isinstance(receipt, dict) else receipt
        if status == "completed":
            reached.append(str(entry["gate"]))
    highest = reached[-1] if reached else None
    return {
        "gatesCompleted": reached,
        "highestGateReached": highest,
        "gatesNotCompleted": [
            str(entry["gate"])
            for entry in QUALIFICATION_LADDER
            if str(entry["gate"]) not in reached
        ],
        "receiptKeys": {str(e["gate"]): e["receiptKey"] for e in QUALIFICATION_LADDER},
    }


def q4_is_gated(receipts: dict[str, Any]) -> tuple[bool, list[str]]:
    """Q4 full screen may only launch with a completed Q1 -> Q2 -> Q3 chain."""
    spec = gate_spec("q4")
    needed = set(spec["requires"]) | {"q1"}
    completed = {
        gate
        for gate in needed
        if (receipts.get(gate_spec(gate)["receiptKey"]) or {}).get("status") == "completed"
        if isinstance(receipts.get(gate_spec(gate)["receiptKey"]), dict)
    }
    completed |= {
        gate
        for gate in needed
        if receipts.get(gate_spec(gate)["receiptKey"]) == "completed"
    }
    missing = sorted(needed - completed, key=gate_order)
    return (not missing), missing


def classify_oom(categories: list[str]) -> str | None:
    """Distinguish load-time OOM from generation-time OOM (Issue #47).

    A load-time OOM is not recoverable by re-running inference at a smaller
    batch size, so the batch ladder must not reload the model for it.
    """
    if "cuda_oom_load" in categories:
        return "load"
    if "cuda_oom_generate" in categories:
        return "generate"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print-register", action="store_true")
    ap.add_argument("--stage", choices=sorted(STAGE_MANIFEST))
    ap.add_argument("--tasks", type=Path, default=None)
    ap.add_argument("--exploratory", action="store_true")
    ap.add_argument(
        "--print-ladder",
        action="store_true",
        help="print the qualification ladder and which gates are unmet given receipts",
    )
    ap.add_argument(
        "--receipts",
        type=Path,
        default=None,
        help="JSON object of receiptKey -> {status} used with --print-ladder",
    )
    ap.add_argument(
        "--preparation-receipt",
        type=Path,
        default=None,
        help=(
            "preparation receipt carrying the prepared stage register; defaults to "
            f"${PREPARATION_RECEIPT_ENV} or {DEFAULT_PREPARATION_RECEIPT}"
        ),
    )
    args = ap.parse_args()

    if args.print_register or not args.stage:
        print(json.dumps(frozen_hash_register(), indent=2))
        return
    if args.print_ladder:
        receipts = (
            json.loads(args.receipts.read_text(encoding="utf-8"))
            if args.receipts
            else {}
        )
        payload = {
            "ladder": QUALIFICATION_LADDER,
            "registerSha256": stage_manifest_sha256(),
            "progress": highest_gate_reached(receipts),
            "q4Gate": dict(
                zip(("allowed", "missingGates"), q4_is_gated(receipts))
            ),
        }
        print(json.dumps(payload, indent=2))
        return
    identity = resolve_stage_tasks(
        args.stage,
        args.tasks,
        promotion_run=not args.exploratory,
        preparation_receipt=args.preparation_receipt,
    )
    print(json.dumps(identity.to_dict(), indent=2))


if __name__ == "__main__":
    main()
