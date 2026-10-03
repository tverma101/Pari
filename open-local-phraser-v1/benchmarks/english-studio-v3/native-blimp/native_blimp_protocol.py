#!/usr/bin/env python3
"""Frozen native BLiMP likelihood contract (Issue #68).

This module is the single place that decides whether a native BLiMP run may
exist, and whether its outputs may be called native BLiMP evidence. Every
other file in this directory is a thin CLI over it.

The lane is deliberately separate from Pari's prompted BLiMP public-fast
screen. Prompted A/B acceptability and minimal-pair causal likelihood are
different constructs; their scores are reported side by side and never
averaged.

Rules enforced here, none of them negotiable:

* one pinned ``lm-evaluation-harness`` commit, one pinned BLiMP task group, one
  pinned dataset revision, one pinned backend file per lane;
* no chat template, ever -- an instruction-tuned finalist is scored as raw
  causal text, because the construct is "which sentence does the model find
  more likely", not "which sentence does the model agree with";
* a reduced run is debug output, never evidence, so ``--limit``/``--samples``
  cannot produce a promotable receipt;
* missing logprobs, a log truncation warning, a dataset revision drift, or a
  backend runtime error is a failed run. None of them may be laundered into a
  grammar accuracy, least of all a 0.0 one.

No network access, no model, no GPU. The only I/O is reading pinned files and
whatever harness checkout and server the caller names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "native-blimp-protocol.json"
CONFIG_SCHEMA_PATH = HERE / "native-blimp-config.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "native-blimp-receipt.schema.json"

LANE_ID = "native-blimp"
CONFIG_SCHEMA_ID = "native-blimp-config-1"
RECEIPT_SCHEMA_ID = "native-blimp-receipt-1"
PARITY_SCHEMA_ID = "native-blimp-parity-1"

#: Benchmark directory that owns the shared roster and runbooks this lane cites.
BENCH_DIR = HERE.parent


class ProtocolError(RuntimeError):
    """A native-BLiMP contract violation. Always fatal; never a warning."""

    def __init__(self, gate: str, code: str, detail: str) -> None:
        super().__init__(f"{gate}/{code}: {detail}")
        self.gate = gate
        self.code = code
        self.detail = detail

    def as_record(self) -> dict[str, str]:
        return {"gate": self.gate, "code": self.code, "detail": self.detail}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    text = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return (text + "\n").encode("utf-8")


_PROTOCOL_CACHE: dict[str, Any] | None = None


def load_protocol() -> dict[str, Any]:
    """Load the frozen pin manifest. Its own sha256 lands in every receipt."""
    global _PROTOCOL_CACHE
    if _PROTOCOL_CACHE is None:
        protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        if protocol.get("schema") != "native-blimp-protocol-1":
            raise ProtocolError(
                "harness_identity",
                "protocol_schema_mismatch",
                f"unexpected protocol schema {protocol.get('schema')!r}",
            )
        if protocol.get("laneId") != LANE_ID:
            raise ProtocolError(
                "harness_identity",
                "protocol_lane_mismatch",
                f"protocol laneId {protocol.get('laneId')!r} != {LANE_ID!r}",
            )
        _PROTOCOL_CACHE = protocol
    return _PROTOCOL_CACHE


def protocol_identity() -> dict[str, str]:
    protocol = load_protocol()
    return {
        "path": str(PROTOCOL_PATH),
        "sha256": sha256_file(PROTOCOL_PATH),
        "harnessCommit": protocol["harness"]["pinnedCommit"],
        "packageVersion": protocol["harness"]["packageVersion"],
        "taskGroup": protocol["task"]["group"],
        "datasetPinnedRevision": protocol["task"]["pinnedDatasetRevision"],
    }


def pinned_subtasks() -> list[str]:
    """The 67 pinned BLiMP subtask names."""
    protocol = load_protocol()
    tasks = protocol["task"]["expectedSubtasks"]
    if len(tasks) != protocol["task"]["subtaskCount"]:
        raise ProtocolError(
            "task_identity",
            "pin_inconsistent",
            f"expectedSubtasks has {len(tasks)} entries but subtaskCount says "
            f"{protocol['task']['subtaskCount']}",
        )
    return list(tasks)


def subtask_set() -> set[str]:
    return set(pinned_subtasks())


# --------------------------------------------------------------------------
# Minimal JSON-Schema subset validation
# --------------------------------------------------------------------------

_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}


def validate_against_schema(
    instance: Any,
    schema: dict[str, Any],
    root: dict[str, Any] | None = None,
) -> list[str]:
    """Validate against the draft-2020-12 subset these schemas actually use.

    Supported: type, const, enum, required, properties, additionalProperties,
    items, minItems, minLength, pattern, minimum, maximum, exclusiveMinimum,
    and ``$ref`` into ``$defs``. Anything else is documentation; this function
    raises rather than silently skipping, so a schema cannot grow a rule that
    is never enforced.
    """
    root = root if root is not None else schema
    errors: list[str] = []

    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        ref = node.get("$ref")
        if not ref:
            return node
        if not ref.startswith("#/$defs/"):
            raise ProtocolError(
                "config", "schema_ref_unsupported", f"unsupported $ref {ref!r}"
            )
        return root["$defs"][ref[len("#/$defs/"):]]

    def type_ok(value: Any, name: str) -> bool:
        if isinstance(value, bool) and name != "boolean":
            return False
        if name == "integer":
            return isinstance(value, int) or (
                isinstance(value, float) and value.is_integer()
            )
        return isinstance(value, _TYPES[name])

    def check(value: Any, node: dict[str, Any], path: str) -> None:
        node = resolve(node)

        declared = node.get("type")
        if declared is not None:
            allowed = declared if isinstance(declared, list) else [declared]
            if not any(type_ok(value, name) for name in allowed):
                errors.append(
                    f"{path}: expected type {allowed}, got {type(value).__name__}"
                )
                return

        if "const" in node and value != node["const"]:
            errors.append(f"{path}: expected const {node['const']!r}, got {value!r}")
        if "enum" in node and value not in node["enum"]:
            errors.append(f"{path}: {value!r} is not one of {node['enum']!r}")

        if isinstance(value, str):
            if "minLength" in node and len(value) < node["minLength"]:
                errors.append(
                    f"{path}: shorter than minLength {node['minLength']}"
                )
            pattern = node.get("pattern")
            if pattern and not re.search(pattern, value):
                errors.append(f"{path}: {value!r} does not match {pattern!r}")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in node and value < node["minimum"]:
                errors.append(f"{path}: {value} < minimum {node['minimum']}")
            if "maximum" in node and value > node["maximum"]:
                errors.append(f"{path}: {value} > maximum {node['maximum']}")
            lower = node.get("exclusiveMinimum")
            if lower is not None and value <= lower:
                errors.append(f"{path}: {value} <= exclusiveMinimum {lower}")

        if isinstance(value, list):
            if "minItems" in node and len(value) < node["minItems"]:
                errors.append(f"{path}: fewer than minItems {node['minItems']}")
            item_schema = node.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    check(item, item_schema, f"{path}[{index}]")

        if isinstance(value, dict):
            for name in node.get("required", []):
                if name not in value:
                    errors.append(f"{path}: missing required property {name!r}")
            props = node.get("properties", {})
            extra = node.get("additionalProperties")
            for name, item in value.items():
                if name in props:
                    check(item, props[name], f"{path}.{name}")
                elif extra is False:
                    errors.append(f"{path}: unexpected property {name!r}")
                elif isinstance(extra, dict):
                    check(item, extra, f"{path}.{name}")

    check(instance, schema, "$")
    return errors


def validate_config_document(config: dict[str, Any]) -> None:
    schema = json.loads(CONFIG_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = validate_against_schema(config, schema)
    if errors:
        raise ProtocolError(
            "config", "config_schema_violation", "; ".join(errors)
        )


def validate_receipt_document(receipt: dict[str, Any]) -> list[str]:
    schema = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    return validate_against_schema(receipt, schema)


# --------------------------------------------------------------------------
# Frozen config -> harness argv
# --------------------------------------------------------------------------


def forbidden_flags() -> tuple[list[str], dict[str, str]]:
    spec = load_protocol()["forbiddenHarnessFlags"]
    return list(spec["flags"]), dict(spec["reasons"])


def render_model_args(model_args: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in model_args.items():
        if isinstance(value, bool):
            parts.append(f"{key}={str(value).lower()}")
        elif value is None:
            parts.append(f"{key}=None")
        else:
            parts.append(f"{key}={value}")
    return ",".join(parts)


def validate_backend_model_args(backend: str, model_args: dict[str, Any]) -> None:
    """Check the model_args key set against the pinned backend contract."""
    spec = load_protocol()["backends"].get(backend)
    if spec is None:
        raise ProtocolError(
            "config", "unknown_backend",
            f"no pinned backend contract for {backend!r}",
        )

    missing = [k for k in spec["requiredModelArgs"] if k not in model_args]
    if missing:
        raise ProtocolError(
            "config", "backend_arg_missing",
            f"the pinned {backend} backend records no default this lane is "
            f"willing to inherit, so model_args {missing} must be explicit",
        )

    for group in spec.get("oneOfRequiredModelArgs", []):
        present = [name for name in group if name in model_args]
        if not present:
            raise ProtocolError(
                "no_truncation", "context_length_unbound",
                f"the pinned {backend} backend needs an explicit context length; "
                f"supply exactly one of {group}. Without one it resolves the "
                f"limit from the model config, and the no-hidden-truncation "
                f"guarantee is unbound.",
            )

    ignored = [k for k in spec.get("ignoredModelArgs", []) if k in model_args]
    if ignored:
        raise ProtocolError(
            "config", "backend_arg_ignored",
            f"the pinned {backend} backend accepts but never reads {ignored}; "
            f"passing it would look like a frozen control while changing nothing",
        )

    known = set(spec["requiredModelArgs"]) | set(spec.get("recordedModelArgs", []))
    unknown = sorted(set(model_args) - known)
    if unknown:
        raise ProtocolError(
            "config", "backend_arg_unknown",
            f"the pinned {backend} backend does not record {unknown} as required "
            f"or recorded execution state (known: {sorted(known)}); an unrecorded "
            f"argument is unproven state that the receipt would not capture",
        )

    if backend == "vllm":
        for pair in spec["mutuallyExclusive"]:
            present = [name for name in pair if name in model_args]
            if len(present) > 1:
                raise ProtocolError(
                    "config", "backend_arg_conflict",
                    f"the pinned vllm backend forbids passing more than one of {pair}",
                )
        if model_args.get("enable_thinking"):
            raise ProtocolError(
                "chat_template_off", "enable_thinking_set",
                "enable_thinking is a chat-generation adaptation and is not part "
                "of the native BLiMP protocol",
            )

    if backend == "gguf":
        base_url = str(model_args.get("base_url", ""))
        if not base_url.startswith(("http://", "https://")):
            raise ProtocolError(
                "config", "backend_arg_invalid",
                f"gguf base_url {base_url!r} is not an http(s) URL",
            )
        if "chat/completions" in base_url:
            raise ProtocolError(
                "logprobs_present", "chat_route_forbidden",
                f"gguf base_url {base_url!r} points at a chat route; the pinned "
                f"backend scores through /v1/completions plus /tokenize",
            )


@dataclass(frozen=True)
class Invocation:
    argv: list[str]
    smoke: bool
    limit: int | None


def build_invocation(
    config: dict[str, Any],
    harness_checkout: Path,
    python: str | None = None,
) -> Invocation:
    """Build the exact ``python -m lm_eval`` argv for a frozen config.

    ``--limit`` appears only on a declared smoke run, and the config must
    already say ``promotable=false`` before that argv is allowed to exist.
    """
    validate_config_document(config)

    if config["promotable"] and config["mode"] != "full":
        raise ProtocolError(
            "no_subset", "smoke_marked_promotable",
            "a smoke run is debug-only and can never be promotable",
        )
    if config["mode"] == "smoke" and "smokeLimit" not in config:
        raise ProtocolError(
            "config", "smoke_limit_missing",
            "mode=smoke requires an explicit smokeLimit so the debug scope is "
            "recorded in the receipt",
        )
    if config["mode"] == "full" and "smokeLimit" in config:
        raise ProtocolError(
            "config", "smoke_limit_on_full_run",
            "mode=full must not carry a smokeLimit",
        )

    backend = config["backend"]
    spec = load_protocol()["backends"][backend]
    model_args = config["runtime"]["modelArgs"]
    validate_backend_model_args(backend, model_args)

    argv = [python or sys.executable, "-m", "lm_eval"]
    argv += ["--model", spec["harnessModelArg"]]
    argv += ["--model_args", render_model_args(model_args)]
    # The group name, never a per-subtask list: a 67-name list would still let
    # a promoted --limit shrink it silently. Coverage is verified from output.
    argv += ["--tasks", load_protocol()["task"]["group"]]
    argv += ["--output_path", str(config["outputs"]["resultsDir"])]
    argv += ["--seed", str(model_args.get("seed", 0))]
    metadata = {
        "native_blimp_lane": LANE_ID,
        "harness_pinned_commit": load_protocol()["harness"]["pinnedCommit"],
        "dataset_pinned_revision": load_protocol()["task"]["pinnedDatasetRevision"],
        "candidate_id": config["candidateId"],
        "benchmark_revision": config["benchmarkRevision"],
    }
    argv += ["--metadata", json.dumps(metadata, sort_keys=True)]
    if config["outputs"].get("logSamples", True):
        argv.append("--log_samples")
    if config["mode"] == "smoke":
        argv += ["--limit", str(config["smokeLimit"])]

    # Defense in depth: the argv just built must not contain a forbidden flag,
    # even if the config schema later grows a passthrough field.
    flags, reasons = forbidden_flags()
    joined = " ".join(argv)
    for flag in flags:
        allowed = flag == "--limit" and config["mode"] == "smoke"
        if flag in joined and not allowed:
            raise ProtocolError(
                "chat_template_off" if "chat" in flag else "no_subset",
                "forbidden_flag_present",
                f"the built argv would pass {flag}: "
                f"{reasons.get(flag, 'forbidden by the frozen native protocol')}",
            )
    if not str(harness_checkout):
        raise ProtocolError(
            "harness_identity", "checkout_missing",
            "a harness checkout path is required",
        )
    return Invocation(
        argv=argv,
        smoke=config["mode"] == "smoke",
        limit=config.get("smokeLimit"),
    )


# --------------------------------------------------------------------------
# Harness identity verification
# --------------------------------------------------------------------------


def subtask_tree_hash(directory: Path) -> str:
    """sha256 over sorted (name, NUL, file-sha256, LF) for non-underscore YAMLs."""
    digest = hashlib.sha256()
    names = sorted(
        p.name for p in directory.glob("*.yaml") if not p.name.startswith("_")
    )
    for name in names:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(directory / name).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def dir_tree_hash(directory: Path) -> str:
    """sha256 over sorted (name, NUL, file-sha256, LF) for every file in a dir."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.iterdir() if p.is_file()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def git_head(checkout: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.decode().strip() or None


AGGREGATED_PIN_KEYS = {
    "lm_eval/tasks/blimp/subtask-set/aggregated",
    "lm_eval/tasks/blimp/dir/all-files",
}


@dataclass
class HarnessIdentity:
    checkout: str
    head_commit: str | None
    commit_matches: bool
    file_sha256: dict[str, str] = field(default_factory=dict)
    missing_files: list[str] = field(default_factory=list)
    mismatched_files: list[str] = field(default_factory=list)
    file_hashes_match: bool = False
    tree_hashes: dict[str, str] = field(default_factory=dict)
    subtask_count: int | None = None
    tree_hashes_match: bool = False
    all_identities_match: bool = False

    def as_receipt_block(self) -> dict[str, Any]:
        return {
            "checkout": self.checkout,
            "headCommit": self.head_commit,
            "commitMatches": self.commit_matches,
            "fileSha256": self.file_sha256,
            "fileHashesMatch": self.file_hashes_match,
            "treeHashes": self.tree_hashes,
            "treeHashesMatch": self.tree_hashes_match,
            "allIdentitiesMatch": self.all_identities_match,
        }

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.commit_matches:
            out.append(
                f"harness HEAD is {self.head_commit!r}, pinned commit is "
                f"{load_protocol()['harness']['pinnedCommit']!r}"
            )
        if self.missing_files:
            out.append(f"harness checkout is missing pinned files {self.missing_files}")
        if self.mismatched_files:
            out.append(
                f"pinned harness files changed: {sorted(self.mismatched_files)}"
            )
        if not self.tree_hashes_match:
            out.append(
                "the pinned BLiMP task directory does not reproduce: observed "
                f"{self.tree_hashes} "
                f"(subtask count {self.subtask_count})"
            )
        return out


def verify_harness_identity(checkout: Path) -> HarnessIdentity:
    """Verify the checkout is byte-identical to the pinned harness commit."""
    protocol = load_protocol()
    pinned_files: dict[str, str] = protocol["harness"]["pinnedFileSha256"]

    identity = HarnessIdentity(
        checkout=str(checkout),
        head_commit=git_head(checkout),
        commit_matches=False,
    )
    identity.commit_matches = (
        identity.head_commit == protocol["harness"]["pinnedCommit"]
    )

    file_hashes_match = True
    for rel, expected in pinned_files.items():
        if rel in AGGREGATED_PIN_KEYS:
            continue  # verified against the whole blimp directory below
        path = checkout / rel
        if not path.is_file():
            identity.missing_files.append(rel)
            file_hashes_match = False
            continue
        observed = sha256_file(path)
        identity.file_sha256[rel] = observed
        if observed != expected:
            identity.mismatched_files.append(rel)
            file_hashes_match = False
    identity.file_hashes_match = file_hashes_match and not identity.missing_files

    blimp_dir = checkout / "lm_eval/tasks/blimp"
    tree_match = False
    if blimp_dir.is_dir():
        subtask_hash = subtask_tree_hash(blimp_dir)
        all_hash = dir_tree_hash(blimp_dir)
        identity.tree_hashes = {
            "lm_eval/tasks/blimp/subtask-set/aggregated": subtask_hash,
            "lm_eval/tasks/blimp/dir/all-files": all_hash,
        }
        identity.subtask_count = len(
            [p for p in blimp_dir.glob("*.yaml") if not p.name.startswith("_")]
        )
        tree_match = (
            subtask_hash == pinned_files["lm_eval/tasks/blimp/subtask-set/aggregated"]
            and all_hash == pinned_files["lm_eval/tasks/blimp/dir/all-files"]
            and identity.subtask_count == protocol["task"]["subtaskCount"]
        )
    else:
        identity.missing_files.append("lm_eval/tasks/blimp/")
    identity.tree_hashes_match = tree_match
    identity.all_identities_match = (
        identity.commit_matches and identity.file_hashes_match and tree_match
    )
    return identity


# --------------------------------------------------------------------------
# Dataset identity
# --------------------------------------------------------------------------


def resolve_dataset_revision(
    dataset_path: str,
    hf_hub: str = "https://huggingface.co",
    timeout: int = 30,
    opener=None,
) -> str | None:
    """Resolve a Hugging Face dataset repo to its current commit sha.

    ``None`` means unresolvable, and every caller treats that as a mismatch,
    never as a pass.
    """
    url = f"{hf_hub.rstrip('/')}/api/datasets/{dataset_path}"
    try:
        if opener is not None:
            payload = opener(url)
        else:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        # Unresolvable is not a pass. The caller records revisionMatches=false
        # and no promotable receipt can be produced.
        return None
    sha = payload.get("sha") if isinstance(payload, dict) else None
    return str(sha) if sha else None


def dataset_identity_block(
    observed_revision: str | None,
    card_sha256: str | None = None,
) -> dict[str, Any]:
    protocol = load_protocol()
    pinned = protocol["task"]["pinnedDatasetRevision"]
    pinned_card = protocol["task"]["datasetCardSha256"]
    return {
        "datasetPath": protocol["task"]["datasetPath"],
        "pinnedRevision": pinned,
        "resolvedRevision": observed_revision,
        "revisionMatches": observed_revision == pinned,
        "cardsSha256": card_sha256,
        "cardsMatch": (
            card_sha256 == pinned_card if card_sha256 is not None else False
        ),
    }


# --------------------------------------------------------------------------
# GGUF server capability probe
# --------------------------------------------------------------------------


@dataclass
class CapabilityProbe:
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


def server_root_from_base_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    for suffix in ("/v1/completions", "/completions", "/v1"):
        if root.endswith(suffix):
            return root[: -len(suffix)]
    return root


def _default_json_opener(timeout: int):
    def opener(url: str, payload: Any = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    return opener


def probe_gguf_server(
    base_url: str,
    model: str | None = None,
    timeout: int = 20,
    opener=None,
) -> CapabilityProbe:
    """Prove the owned llama-server can serve the native likelihood protocol.

    Checks the three things the pinned gguf backend actually depends on:
    ``/props`` slot discovery, ``/tokenize`` with ``add_special``, and a
    ``/v1/completions`` forced-token round trip that returns
    ``logprobs.content`` with ``top_logprobs``. A server that answers but
    returns no usable logprobs is a failure, not an invitation to fall back to
    generation or prompted accuracy.
    """
    root = server_root_from_base_url(base_url)
    call = opener if opener is not None else _default_json_opener(timeout)

    detail: dict[str, Any] = {
        "serverRoot": root,
        "endpoints": {},
        "totalSlots": None,
        "forcedTokenRoundTrip": False,
        "logprobsShape": None,
    }
    failures: list[str] = []

    # 1. /props -- the backend auto-detects total_slots here; absence is
    #    tolerated, so it is recorded but never fatal.
    try:
        props = call(f"{root}/props", None if model is None else {"model": model})
        detail["endpoints"]["props"] = "ok"
        slots = (props or {}).get("total_slots")
        if isinstance(slots, int) and slots > 0:
            detail["totalSlots"] = slots
    except Exception as exc:  # noqa: BLE001 - any transport failure is a failure
        detail["endpoints"]["props"] = f"error: {type(exc).__name__}"

    # 2. /tokenize with add_special -- mandatory; the pinned backend has no
    #    fallback tokenizer and always sends add_special=True.
    payload: dict[str, Any] = {"content": "The", "add_special": True}
    if model is not None:
        payload["model"] = model
    try:
        tokenized = call(f"{root}/tokenize", payload)
        tokens = (tokenized or {}).get("tokens")
        if not isinstance(tokens, list) or not tokens:
            raise ValueError("server returned no tokens")
        detail["endpoints"]["tokenize"] = "ok"
        detail["tokenizeAddSpecial"] = True
    except Exception as exc:  # noqa: BLE001
        detail["endpoints"]["tokenize"] = f"error: {type(exc).__name__}"
        failures.append(
            "/tokenize with add_special is required by the pinned gguf backend "
            f"and failed: {exc}"
        )
        return CapabilityProbe(ok=False, detail=detail, failures=failures)

    target_id = int(tokens[0])

    # 3. forced-token round trip through /v1/completions.
    request_body: dict[str, Any] = {
        "prompt": list(tokens),
        "temperature": 0,
        "max_tokens": 1,
        "logprobs": 2,
        "logit_bias": [[target_id, 100]],
    }
    if model is not None:
        request_body["model"] = model
    try:
        completion = call(f"{root}/v1/completions", request_body)
    except Exception as exc:  # noqa: BLE001
        detail["endpoints"]["v1/completions"] = f"error: {type(exc).__name__}"
        failures.append(
            f"/v1/completions rejected the forced-token request: {exc}"
        )
        return CapabilityProbe(ok=False, detail=detail, failures=failures)

    detail["endpoints"]["v1/completions"] = "ok"
    choices = (completion or {}).get("choices") or []
    if not choices:
        failures.append(
            "/v1/completions returned no choices, so no logprob exists; native "
            "likelihood is unavailable on this runtime"
        )
        return CapabilityProbe(ok=False, detail=detail, failures=failures)

    content = (choices[0].get("logprobs") or {}).get("content") or []
    if not content:
        detail["logprobsShape"] = "missing"
        failures.append(
            "the server answered /v1/completions without logprobs.content; the "
            "pinned gguf backend cannot score likelihoods and this lane refuses "
            "to fall back to generation or prompted accuracy"
        )
        return CapabilityProbe(ok=False, detail=detail, failures=failures)

    entry = content[0]
    if entry.get("id") != target_id:
        detail["logprobsShape"] = "forced-token-mismatch"
        failures.append(
            f"the server sampled token {entry.get('id')!r} instead of the forced "
            f"{target_id}, so the returned logprob is not the teacher-forced value"
        )
        return CapabilityProbe(ok=False, detail=detail, failures=failures)

    top = entry.get("top_logprobs") or []
    if not top:
        detail["logprobsShape"] = "no-top-logprobs"
        failures.append(
            "the logprobs.content entry carried no top_logprobs, so is_greedy "
            "cannot be derived and the native decision is undefined"
        )
        return CapabilityProbe(ok=False, detail=detail, failures=failures)

    detail["logprobsShape"] = "modern-openai-content"
    detail["forcedTokenRoundTrip"] = True
    detail["forcedTokenLogprob"] = entry.get("logprob")
    return CapabilityProbe(ok=True, detail=detail, failures=failures)


# --------------------------------------------------------------------------
# Run-output scanning: fail closed on runtime errors and hidden truncation
# --------------------------------------------------------------------------


#: Log patterns that must never appear in a promotable native run. The kind
#: names are stable strings so a test can assert on them.
RUN_ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"Missing logprobs in scoring response", "missing_logprobs"),
    (r"Invalid scoring response", "invalid_scoring_response"),
    (r"Server did not sample the forced token id", "forced_token_mismatch"),
    (r"Failed to get a valid response after \d+ retries", "server_retries_exhausted"),
    (r"loglikelihood_rolling not yet supported", "unsupported_request_type"),
    (r"CUDA out of memory", "cuda_oom"),
    (r"Traceback \(most recent call last\)", "python_traceback"),
    (r"exceeds max length", "context_over_max_length"),
]


def scan_run_output(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """Return ``(runtime_errors, contract_errors)`` for captured harness output."""
    runtime: list[dict[str, str]] = []
    contract: list[str] = []
    for pattern, kind in RUN_ERROR_PATTERNS:
        if not re.search(pattern, text):
            continue
        line = next(
            (
                stripped
                for stripped in (raw.strip() for raw in text.splitlines())
                if re.search(pattern, stripped)
            ),
            pattern,
        )
        if kind == "context_over_max_length":
            contract.append(
                "the harness reported a sequence longer than the configured max "
                "length; the pinned vllm backend silently left-truncates and only "
                "warns, so native BLiMP cannot run with hidden truncation"
            )
        else:
            runtime.append({"kind": kind, "message": line[:600]})
    return runtime, contract


# --------------------------------------------------------------------------
# Result validation (the promotion gate)
# --------------------------------------------------------------------------


def _require(results: dict[str, Any], key: str, gate: str, code: str) -> Any:
    if key not in results:
        raise ProtocolError(
            gate, code, f"the harness result JSON is missing {key!r}"
        )
    return results[key]


def validate_aggregate(
    results: dict[str, Any],
    expect_full: bool,
) -> dict[str, Any]:
    """Independently recompute the harness group aggregate.

    The pinned ``_blimp.yaml`` sets ``aggregate_metric_list`` to
    ``acc / mean / weight_by_size: False``, so the group number must equal the
    plain unweighted mean of the per-subtask acc values. A mismatch means the
    aggregate was computed over a different set than the one in front of us,
    which is exactly how a subset gets presented as full evidence.
    """
    protocol = load_protocol()
    agg_spec = protocol["task"]["groupAggregate"]
    per_task = results.get("results") or {}
    accs = [
        float(value["acc"])
        for name, value in per_task.items()
        if name in subtask_set()
        and isinstance(value, dict)
        and isinstance(value.get("acc"), (int, float))
        and not isinstance(value.get("acc"), bool)
    ]
    recomputed = (sum(accs) / len(accs)) if accs else None

    group = (results.get("groups") or {}).get(protocol["task"]["group"]) or {}
    raw = group.get("acc")
    harness_acc = (
        float(raw)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool)
        else None
    )
    difference = (
        abs(harness_acc - recomputed)
        if harness_acc is not None and recomputed is not None
        else None
    )
    matches = difference is not None and difference <= 1e-9

    block = {
        "harnessGroupAcc": harness_acc,
        "recomputedUnweightedMeanAcc": recomputed,
        "absoluteDifference": difference,
        "matches": matches,
        "aggregation": agg_spec["aggregation"],
        "weightBySize": agg_spec["weightBySize"],
    }

    if expect_full:
        if len(accs) != protocol["task"]["subtaskCount"]:
            raise ProtocolError(
                "aggregate_recomputed", "aggregate_input_incomplete",
                f"only {len(accs)} of {protocol['task']['subtaskCount']} subtasks "
                f"carried an acc value, so the group aggregate cannot be reproduced",
            )
        if harness_acc is None:
            raise ProtocolError(
                "aggregate_recomputed", "group_aggregate_missing",
                f"the harness output has no groups.{protocol['task']['group']}.acc",
            )
        if not matches:
            raise ProtocolError(
                "aggregate_recomputed", "aggregate_mismatch",
                f"harness groups.{protocol['task']['group']}.acc={harness_acc!r} but "
                f"the unweighted mean of {len(accs)} subtask accuracies is "
                f"{recomputed!r} (difference {difference!r})",
            )
    return block


def validate_harness_results(
    results: dict[str, Any],
    expect_full: bool,
    expected_tasks: set[str] | None = None,
) -> dict[str, Any]:
    """Validate harness output against the frozen protocol.

    Returns a coverage/aggregate summary. Raises :class:`ProtocolError` on the
    first promotion-blocking violation. ``expect_full=False`` is only ever
    used for a declared debug smoke.
    """
    protocol = load_protocol()
    task_spec = protocol["task"]
    expected = expected_tasks if expected_tasks is not None else subtask_set()

    per_task = dict(
        _require(results, "results", "task_identity", "results_missing")
    )
    observed = {name for name in per_task if name in expected}
    missing = sorted(expected - observed)
    unexpected = sorted({name for name in per_task if name not in expected})

    summary: dict[str, Any] = {
        "expectedSubtasks": len(expected),
        "observedSubtasks": len(observed),
        "missing": missing,
        "unexpected": unexpected,
        "complete": not missing and not unexpected,
        "rowsPerSubtask": {},
        "reducedEffectiveCountTasks": [],
    }

    if expect_full:
        if missing:
            raise ProtocolError(
                "task_identity", "coverage_incomplete",
                f"{len(missing)} pinned BLiMP subtasks are missing from the harness "
                f"output: {missing[:5]}",
            )
        if unexpected:
            raise ProtocolError(
                "task_identity", "coverage_unexpected",
                f"the harness output carries {len(unexpected)} task names outside "
                f"the pinned 67-subtask set: {unexpected[:5]}",
            )

    n_samples = results.get("n-samples") or {}
    rows: dict[str, int] = {}
    reduced: list[str] = []
    for task in sorted(observed):
        entry = n_samples.get(task) or {}
        original = entry.get("original")
        effective = entry.get("effective")
        rows[task] = effective if isinstance(effective, int) else -1
        if expect_full and (
            original != task_spec["rowsPerConfig"]
            or effective != task_spec["rowsPerConfig"]
        ):
            reduced.append(task)
    summary["rowsPerSubtask"] = rows
    summary["reducedEffectiveCountTasks"] = reduced

    if expect_full and reduced:
        raise ProtocolError(
            "no_subset", "subset_reported_as_full",
            f"{len(reduced)} subtasks did not evaluate all "
            f"{task_spec['rowsPerConfig']} documents (e.g. {reduced[:5]}); a reduced "
            f"run is debug output and cannot be full native evidence",
        )

    for task in sorted(observed):
        metrics = per_task[task]
        if not isinstance(metrics, dict) or "acc" not in metrics:
            raise ProtocolError(
                "task_identity", "acc_missing",
                f"subtask {task} produced no acc metric",
            )

    n_shot = results.get("n-shot") or {}
    if expect_full:
        for task in sorted(observed):
            if n_shot.get(task) != 0:
                raise ProtocolError(
                    "task_identity", "fewshot_drift",
                    f"subtask {task} ran with n-shot {n_shot.get(task)!r}; the "
                    f"pinned BLiMP template is num_fewshot 0",
                )

    configs = results.get("configs") or {}
    if expect_full and configs:
        sample_task = sorted(observed)[0]
        cfg = configs.get(sample_task) or {}
        for key, want in (
            ("dataset_path", task_spec["datasetPath"]),
            ("validation_split", task_spec["validationSplit"]),
            ("output_type", task_spec["outputType"]),
            ("doc_to_target", task_spec["docToTarget"]),
            ("doc_to_choice", task_spec["docToChoice"]),
        ):
            if key in cfg and cfg[key] != want:
                raise ProtocolError(
                    "task_identity", "task_definition_drift",
                    f"subtask {sample_task} reports {key}={cfg[key]!r}, pinned "
                    f"protocol says {want!r}",
                )

    config = results.get("config") or {}
    if expect_full:
        for key, code in (
            ("limit", "limit_in_harness_config"),
            ("samples", "samples_in_harness_config"),
            ("predict_only", "predict_only_in_config"),
        ):
            if config.get(key):
                raise ProtocolError(
                    "no_subset", code,
                    f"the harness recorded {key}={config.get(key)!r} on a "
                    f"promotable run",
                )
        if config.get("apply_chat_template"):
            raise ProtocolError(
                "chat_template_off", "apply_chat_template_in_config",
                "the harness recorded apply_chat_template on a native likelihood "
                "run; the construct would no longer be minimal-pair likelihood",
            )
        if config.get("fewshot_as_multiturn"):
            raise ProtocolError(
                "chat_template_off", "fewshot_as_multiturn_in_config",
                "the harness recorded fewshot_as_multiturn, which is a chat "
                "adaptation by another route",
            )
        model = config.get("model")
        if model not in protocol["backends"]:
            raise ProtocolError(
                "logprobs_present", "unexpected_backend",
                f"the harness ran with --model {model!r}, which is not one of the "
                f"pinned native backends {sorted(protocol['backends'])}",
            )

    reported_version = results.get("lm_eval_version")
    pinned_version = protocol["harness"]["packageVersion"]
    if expect_full and reported_version not in (None, pinned_version):
        raise ProtocolError(
            "harness_identity", "lm_eval_version_mismatch",
            f"the harness reported lm_eval_version {reported_version!r}, pinned "
            f"{pinned_version!r}",
        )

    summary["aggregate"] = validate_aggregate(results, expect_full=expect_full)
    summary["perSubtaskAcc"] = {
        task: float(metrics["acc"])
        for task, metrics in per_task.items()
        if task in expected
        and isinstance(metrics, dict)
        and isinstance(metrics.get("acc"), (int, float))
        and not isinstance(metrics.get("acc"), bool)
    }
    return summary


# --------------------------------------------------------------------------
# Cross-backend parity
# --------------------------------------------------------------------------


PARITY_REQUIRED_KEYS = (
    "modelArtifactSha256",
    "leftReceipt",
    "rightReceipt",
    "loglikelihoodTolerance",
    "decisionTolerance",
    "subtaskAccuracyTolerance",
)


def load_parity_fixture(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if fixture.get("laneId") != PARITY_SCHEMA_ID:
        raise ProtocolError(
            "parity", "fixture_lane_mismatch",
            f"a parity fixture laneId must be {PARITY_SCHEMA_ID!r}",
        )
    for name in PARITY_REQUIRED_KEYS:
        if name not in fixture:
            raise ProtocolError(
                "parity", "fixture_incomplete",
                f"the parity fixture is missing {name!r}",
            )
    return fixture


def compare_parity(
    left: dict[str, Any],
    right: dict[str, Any],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    """Compare two native receipts of the same model artifact.

    Checks item identity/order, preferred-sentence decision, per-item
    loglikelihood where the receipts expose it, and per-subtask accuracy.
    Numeric equality between quantized and unquantized artifacts is *not*
    expected: tolerances here are about evaluator semantics, not model
    evidence, so a comparison only means anything when both sides describe the
    same artifact hash.
    """
    if fixture.get("laneId") != PARITY_SCHEMA_ID:
        raise ProtocolError(
            "parity", "fixture_lane_mismatch",
            f"a parity fixture laneId must be {PARITY_SCHEMA_ID!r}",
        )
    for name in PARITY_REQUIRED_KEYS:
        if name not in fixture:
            raise ProtocolError(
                "parity", "fixture_incomplete",
                f"the parity fixture is missing {name!r}",
            )

    left_backend = fixture.get("leftBackend")
    right_backend = fixture.get("rightBackend")
    if left_backend == right_backend:
        raise ProtocolError(
            "parity", "not_cross_backend",
            f"both receipts use the {left_backend!r} backend, so this compares two "
            f"runs of one path rather than backend semantics",
        )

    findings: list[str] = []
    details: dict[str, Any] = {
        "leftBackend": left_backend,
        "rightBackend": right_backend,
        "modelArtifactSha256": fixture["modelArtifactSha256"],
    }

    for side, receipt in (("left", left), ("right", right)):
        observed = ((receipt.get("backend") or {}).get("name"))
        if observed not in (left_backend, right_backend):
            findings.append(
                f"the {side} receipt reports backend {observed!r}, which is "
                f"neither {left_backend!r} nor {right_backend!r}"
            )

    for side, receipt in (("left", left), ("right", right)):
        artifacts = (receipt.get("model") or {}).get("artifactSha256")
        if artifacts is not None and artifacts != fixture["modelArtifactSha256"]:
            findings.append(
                f"the {side} receipt was produced from model artifact "
                f"{artifacts!r}, not the fixture's {fixture['modelArtifactSha256']!r}; "
                f"quantized-vs-unquantized differences are model evidence, not "
                f"evaluator parity"
            )

    left_cov = left.get("coverage") or {}
    right_cov = right.get("coverage") or {}
    if left_cov.get("complete") is not True or right_cov.get("complete") is not True:
        findings.append(
            "cross-backend parity needs two complete 67-subtask runs; at least one "
            "side is incomplete"
        )

    if not findings:
        left_acc = left.get("perSubtaskAcc") or {}
        right_acc = right.get("perSubtaskAcc") or {}
        shared = sorted(set(left_acc) & set(right_acc))
        if len(shared) != len(subtask_set()):
            findings.append(
                f"per-subtask accuracies overlap on only {len(shared)} subtasks "
                f"instead of {len(subtask_set())}"
            )
        else:
            worst_task = None
            worst_delta = 0.0
            for task in shared:
                delta = abs(float(left_acc[task]) - float(right_acc[task]))
                if delta > worst_delta:
                    worst_task, worst_delta = task, delta
            details["worstSubtask"] = worst_task
            details["worstSubtaskAccuracyDelta"] = worst_delta
            tolerance = float(fixture["subtaskAccuracyTolerance"])
            if worst_delta > tolerance:
                findings.append(
                    f"subtask {worst_task} accuracy differs by {worst_delta:.6f}, "
                    f"above the {tolerance} parity tolerance; investigate backend "
                    f"BOS/EOS/tokenization semantics before ranking across formats"
                )

    left_items = left.get("perItemLoglikelihood") or {}
    right_items = right.get("perItemLoglikelihood") or {}
    if left_items and right_items:
        shared_ids = sorted(set(left_items) & set(right_items))
        union = set(left_items) | set(right_items)
        if len(shared_ids) != len(union):
            missing_ids = sorted(union - set(shared_ids))[:5]
            findings.append(
                f"per-item loglikelihood ids do not match across backends; "
                f"{len(union) - len(shared_ids)} ids are unmatched (e.g. "
                f"{missing_ids})"
            )
        ll_tolerance = float(fixture["loglikelihoodTolerance"])
        decision_tolerance = float(fixture["decisionTolerance"])
        worst_ll = 0.0
        flips = 0
        for item_id in shared_ids:
            a = left_items[item_id]
            b = right_items[item_id]
            worst_ll = max(
                worst_ll,
                abs(float(a["loglikelihood"]) - float(b["loglikelihood"])),
            )
            if a.get("preferred") != b.get("preferred"):
                flips += 1
        total = len(shared_ids) or 1
        details["itemsCompared"] = len(shared_ids)
        details["worstLoglikelihoodDelta"] = worst_ll
        details["decisionFlips"] = flips
        details["decisionFlipRate"] = flips / total
        if worst_ll > ll_tolerance:
            findings.append(
                f"per-item loglikelihood differs by up to {worst_ll:.6f}, above the "
                f"{ll_tolerance} parity tolerance"
            )
        if flips / total > decision_tolerance:
            findings.append(
                f"{flips}/{len(shared_ids)} preferred-sentence decisions differ, "
                f"above the {decision_tolerance} flip tolerance; systematic "
                f"decision differences require investigation before cross-backend "
                f"ranking"
            )
    else:
        details["perItemComparison"] = (
            "skipped: neither receipt exposed per-item loglikelihoods"
        )

    return {
        "laneId": PARITY_SCHEMA_ID,
        "ok": not findings,
        "findings": findings,
        "details": details,
    }


# --------------------------------------------------------------------------
# Receipt construction
# --------------------------------------------------------------------------


def build_receipt(
    config: dict[str, Any],
    config_path: Path,
    *,
    outcome: str,
    promotable: bool,
    harness: dict[str, Any],
    dataset: dict[str, Any],
    backend: dict[str, Any] | None,
    argv: list[str],
    adaptation: dict[str, Any],
    outputs: dict[str, Any],
    coverage: dict[str, Any],
    aggregate: dict[str, Any] | None,
    per_subtask_acc: dict[str, float],
    gate_results: dict[str, dict[str, str]],
    runtime_errors: list[dict[str, str]],
    errors: list[dict[str, str]],
    notes: list[str],
    failure_reason: str | None = None,
    parity: dict[str, Any] | None = None,
    per_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA_ID,
        "laneId": LANE_ID,
        "promotable": promotable,
        "outcome": outcome,
        "failureReason": failure_reason,
        "config": config,
        "configSha256": sha256_file(config_path),
        "protocol": protocol_identity(),
        "harnessObserved": harness,
        "datasetObserved": dataset,
        "argv": argv,
        "adaptation": adaptation,
        "outputs": outputs,
        "coverage": coverage,
        "perSubtaskAcc": per_subtask_acc,
        "gateResults": gate_results,
        "runtimeErrors": runtime_errors,
        "errors": errors,
        "notes": notes,
    }
    if backend is not None:
        receipt["backend"] = backend
    if aggregate is not None:
        receipt["aggregate"] = aggregate
    if parity is not None:
        receipt["parity"] = parity
    if per_item:
        receipt["perItemLoglikelihood"] = per_item
    if outcome == "fail" or errors or runtime_errors:
        receipt["promotable"] = False
    return receipt


# --------------------------------------------------------------------------
# Small IO helpers
# --------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(canonical_json_bytes(payload))
    tmp.replace(path)


def collect_output_files(results_dir: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if not results_dir.is_dir():
        return files
    for path in sorted(results_dir.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "name": str(path.relative_to(results_dir)),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
    return files


def find_harness_results_file(results_dir: Path) -> Path | None:
    candidates = sorted(results_dir.glob("results_*.json"))
    if candidates:
        return candidates[-1]
    flat = results_dir / "results.json"
    return flat if flat.is_file() else None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the frozen native BLiMP protocol contract.",
    )
    parser.add_argument(
        "command",
        choices=(
            "show",
            "check-harness",
            "check-dataset",
            "build-plan",
            "probe-gguf",
        ),
    )
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "show":
        print(json.dumps(load_protocol(), indent=2, sort_keys=True))
        return 0

    if args.command == "check-harness":
        if args.checkout is None:
            parser.error("check-harness requires --checkout")
        identity = verify_harness_identity(args.checkout)
        payload = identity.as_receipt_block()
        payload["problems"] = identity.problems()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if identity.all_identities_match else 1

    if args.command == "check-dataset":
        protocol = load_protocol()
        revision = resolve_dataset_revision(protocol["task"]["datasetPath"])
        block = dataset_identity_block(revision)
        print(json.dumps(block, indent=2, sort_keys=True))
        return 0 if block["revisionMatches"] else 1

    if args.command == "build-plan":
        if args.config is None:
            parser.error("build-plan requires --config")
        config = read_json(args.config)
        harness = args.checkout or Path(
            config.get("harness", {}).get("checkout", str(HERE))
        )
        invocation = build_invocation(config, harness)
        print(
            json.dumps(
                {"argv": invocation.argv, "smoke": invocation.smoke},
                indent=2,
            )
        )
        return 0

    if args.command == "probe-gguf":
        if not args.base_url:
            parser.error("probe-gguf requires --base-url")
        probe = probe_gguf_server(
            args.base_url, model=args.model, timeout=args.timeout
        )
        print(
            json.dumps(
                {"ok": probe.ok, "detail": probe.detail, "failures": probe.failures},
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if probe.ok else 1

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
