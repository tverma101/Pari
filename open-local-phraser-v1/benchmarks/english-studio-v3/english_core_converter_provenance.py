"""Content-addressed provenance for Pari's score-affecting conversion layer.

The official SWORDS/JFLEG/SemanticQA evaluators are pinned and delegated to, but
the *Pari-owned conversion step* that builds their input is itself score-affecting.
Issue #66 therefore requires every promotion-comparable official anchor to record an
immutable chain:

    raw model result -> converter implementation + config -> converted artifact
    -> pinned official evaluator + data -> evaluator interpreter -> archived metric

This module is the single place that defines that chain so the three converters and
the three official-evaluator wrappers cannot drift apart. It deliberately has no
third-party dependencies and no side effects at import time.

Three identities are recorded, each answering a different tamper question:

``converterProtocol``
    Which *policy* ran, independent of file bytes. ``id`` + ``version`` name a
    registered contract; ``contractSha256`` is the hash of the canonical contract
    description stored in :data:`CONVERTER_PROTOCOLS`. Changing the registered
    description (a regex, a marker, a normalization rule) changes this hash.

``converterSource.sha256``
    Which *bytes* ran. This is the hash of the converter script file itself, so a
    one-byte edit that leaves the manifest untouched is detected.

``identity``
    Which *result* was produced: a hash over the benchmark name, protocol id,
    protocol version, contract hash, converter source hash, and the full
    conversion config. Two artifacts may only enter one headline comparison when
    their ``identity`` values are equal, so a ``--max-candidates`` or
    ``--lemmatized`` drift -- or a parser change -- cannot silently move one
    finalist's official score.

Provenance is fail-closed. If the benchmark Git identity cannot be resolved (for
example an exported source tree with no ``.git`` metadata), conversion still
produces artifacts for exploration, but every promotion read of that manifest
fails with ``benchmark_git_identity_unavailable`` until the chain is reconstructed
from preserved raw outputs.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

#: Format version of the provenance record emitted into conversion manifests.
CONTRACT_VERSION = 1

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


# ---------------------------------------------------------------------------
# Registered conversion protocols.
#
# Each entry freezes the Pari-owned policy that decides what the official
# evaluator actually receives. Adding a key here with a new version number is the
# supported way to change a parser: the new identity forces a replay of every
# compared candidate from preserved raw outputs instead of an in-place re-score.
# ---------------------------------------------------------------------------

SWORDS_PROTOCOL_ID = "pari-swords-candidate-parser"
JFLEG_PROTOCOL_ID = "pari-jfleg-one-line-normalizer"
SEMANTICQA_PROTOCOL_ID = "pari-semanticqa-lcc-postprocess"

CONVERTER_PROTOCOLS: dict[str, dict[str, dict[int, dict[str, Any]]]] = {
    "swords": {
        SWORDS_PROTOCOL_ID: {
            1: {
                "label": "Pari SWORDS candidate parser v1",
                "summary": (
                    "Splits raw model output into per-line candidate substitutes before "
                    "the official SWORDS evaluator scores them."
                ),
                "contract": {
                    "splitPolicy": "str(text or '').splitlines()",
                    "perLineTrim": "line.strip(); empty lines dropped",
                    "listPrefixPattern": r"^\s*(?:[-*•]+|\d+[.)]|[A-Za-z][.)])\s*",
                    "quoteStripChars": "`\"' ",
                    "filteredMetaPrefixes": [
                        "here are",
                        "substitutes:",
                        "alternatives:",
                        "the best",
                    ],
                    "filterMatch": "case-insensitive startswith on the post-strip line",
                    "dedupPolicy": "casefold() first-occurrence-wins",
                    "truncationPolicy": "retained order truncated to maxCandidates",
                    "rankScorePolicy": (
                        "float(n - index) descending from retained candidate count"
                    ),
                    "scoreProvenance": (
                        "scores encode model rank order only, never lexical quality"
                    ),
                },
                "configKeys": ["maxCandidates", "substitutesLemmatized"],
                "pinnedConfig": {},
                "coverageKeys": [
                    "targets",
                    "convertedTargets",
                    "missingOutputs",
                    "extraOutputs",
                    "emptyCandidateOutputs",
                    "truncatedTargets",
                ],
            }
        }
    },
    "jfleg": {
        JFLEG_PROTOCOL_ID: {
            1: {
                "label": "Pari JFLEG one-line normalizer v1",
                "summary": (
                    "Collapses each model hypothesis onto exactly one line so the official "
                    "JFLEG GLEU script reads one hypothesis per source line."
                ),
                "contract": {
                    "normalization": '" ".join(str(text or "").strip().split())',
                    "whitespaceClass": (
                        "Python str.split()/str.strip() semantics: every Unicode whitespace "
                        "character, including U+00A0, U+2028 and U+3000, is collapsed"
                    ),
                    "contentEdits": (
                        "none beyond leading/trailing and interior whitespace removal"
                    ),
                    "lineContract": (
                        "exactly one hypothesis line per prompt task, always emitted"
                    ),
                    "missingOutputPolicy": (
                        "emit an empty line and record the gap as a coverage error"
                    ),
                    "emptyOutputPolicy": (
                        "an empty model output stays an empty line: that is model behavior "
                        "and is scored as such, not silently dropped"
                    ),
                },
                # The normalizer takes no value-bearing CLI input, so the only
                # conversion-affecting input is the protocol identity itself.
                "configKeys": ["normalizerProtocol"],
                "pinnedConfig": {"normalizerProtocol": "pari-jfleg-one-line-normalizer@1"},
                "coverageKeys": [
                    "cases",
                    "hypotheses",
                    "missingOutputs",
                    "extraOutputs",
                    "emptyOutputs",
                    "normalizedChangedRows",
                ],
            }
        }
    },
    "semanticqa_lcc": {
        SEMANTICQA_PROTOCOL_ID: {
            1: {
                "label": "Pari SemanticQA LCC postprocess v1",
                "summary": (
                    "Applies the pinned official SemanticQA collocation-categorization "
                    "postprocessor to raw model output before the official LCC evaluator "
                    "compares prediction to label by exact equality."
                ),
                "contract": {
                    "whitespaceNormalization": '" ".join(str(text or "").split())',
                    "markerOrder": ["is: ", "Output:"],
                    "markerMatch": "substring test on the whitespace-normalized string",
                    "markerSelection": "s.split(marker)[-1].strip() (last occurrence wins)",
                    "branchSemantics": (
                        "if/elif: an 'is: ' match short-circuits the 'Output:' branch"
                    ),
                    "caseSensitive": True,
                    "furtherEdits": (
                        "none; no quote stripping, bullets, trimming beyond the marker "
                        "split, or case folding"
                    ),
                    "officialComparison": (
                        "exact string equality against the gold label in semantic_qa/eval.py"
                    ),
                },
                "configKeys": [
                    "postprocessorSource",
                    "postprocessorCommit",
                    "postprocessorModuleSha256",
                ],
                "pinnedConfig": {},
                "coverageKeys": [
                    "cases",
                    "convertedRows",
                    "missingOutputs",
                    "extraOutputs",
                    "emptyOutputs",
                    "postprocessChangedOutputs",
                    "isMarkerRows",
                    "outputMarkerRows",
                ],
            }
        }
    },
}


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic JSON encoding used for every content address in this module."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_canonical(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def is_sha256(value: object) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "").strip()))


def is_git_sha(value: object) -> bool:
    return bool(GIT_SHA_RE.fullmatch(str(value or "").strip()))


# ---------------------------------------------------------------------------
# Protocol registry
# ---------------------------------------------------------------------------


def registered_protocol(
    benchmark: str, protocol_id: object, version: object
) -> dict[str, Any] | None:
    """Return the registered contract entry, or ``None`` when unknown."""
    entry = CONVERTER_PROTOCOLS.get(str(benchmark), {}).get(str(protocol_id or ""))
    if entry is None:
        return None
    return entry.get(int(version)) if isinstance(version, int) else None


def protocol_contract_sha256(benchmark: str, protocol_id: str, version: int) -> str:
    """Hash the registered contract *description*, not the converter's bytes."""
    entry = registered_protocol(benchmark, protocol_id, version)
    if entry is None:
        raise KeyError(
            f"unregistered converter protocol: {benchmark}/{protocol_id}@{version}"
        )
    return sha256_canonical(
        {
            "benchmark": benchmark,
            "protocolId": protocol_id,
            "protocolVersion": version,
            "contract": entry["contract"],
            "configKeys": entry["configKeys"],
            "pinnedConfig": entry["pinnedConfig"],
        }
    )


# ---------------------------------------------------------------------------
# Benchmark Git identity (issue #40 chain)
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), *args],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    return out.strip() or None


def find_repo_root(start: Path) -> Path | None:
    """Walk upwards for a ``.git`` entry; returns ``None`` for an archive export."""
    current = Path(start).expanduser().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def benchmark_git_identity(start: Path | None = None) -> dict[str, Any]:
    """Resolve the Pari benchmark revision/tree that defines the conversion policy.

    Returns a record with ``available: False`` rather than raising, so callers can
    record honest ``unknown`` provenance and let the promotion gate fail closed.
    """
    origin = Path(start) if start is not None else Path(__file__).resolve().parent
    repo = find_repo_root(origin)
    if repo is None:
        return {
            "available": False,
            "reason": "benchmark_git_identity_unavailable",
            "repositoryRoot": None,
            "commit": None,
            "tree": None,
            "branch": None,
            "dirty": None,
        }
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(repo, "status", "--porcelain")
    resolved = bool(is_git_sha(commit) and is_git_sha(tree))
    return {
        "available": resolved,
        "reason": None if resolved else "benchmark_git_identity_unavailable",
        "repositoryRoot": str(repo),
        "commit": commit,
        "tree": tree,
        "branch": branch,
        "dirty": bool(status) if status is not None else None,
    }


# ---------------------------------------------------------------------------
# Conversion identity
# ---------------------------------------------------------------------------


def conversion_identity(
    *,
    benchmark: str,
    protocol_id: str,
    protocol_version: int,
    contract_sha256: str,
    converter_source_sha256: str,
    conversion_config: dict[str, Any],
) -> str:
    """Content address for one converted artifact's full conversion chain."""
    return sha256_canonical(
        {
            "benchmark": benchmark,
            "contractSha256": contract_sha256,
            "conversionConfig": conversion_config,
            "converterSourceSha256": converter_source_sha256,
            "protocolId": protocol_id,
            "protocolVersion": protocol_version,
        }
    )


def build_converter_provenance(
    *,
    benchmark: str,
    protocol_id: str,
    protocol_version: int,
    converter_path: Path,
    conversion_config: dict[str, Any],
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Assemble the ``converterProvenance`` block for a conversion manifest."""
    converter_path = Path(converter_path).resolve()
    source_sha = sha256_file(converter_path)
    contract_sha = protocol_contract_sha256(benchmark, protocol_id, protocol_version)
    git_identity = benchmark_git_identity(repo_root or converter_path.parent)
    return {
        "contractVersion": CONTRACT_VERSION,
        "benchmark": benchmark,
        "protocol": {
            "id": protocol_id,
            "version": protocol_version,
            "label": (registered_protocol(benchmark, protocol_id, protocol_version) or {}).get(
                "label"
            ),
            "contractSha256": contract_sha,
        },
        "converterSource": {
            "path": converter_path.name,
            "sha256": source_sha,
            "bytes": converter_path.stat().st_size,
        },
        "benchmarkGit": git_identity,
        "conversionConfig": conversion_config,
        "identity": conversion_identity(
            benchmark=benchmark,
            protocol_id=protocol_id,
            protocol_version=protocol_version,
            contract_sha256=contract_sha,
            converter_source_sha256=source_sha,
            conversion_config=conversion_config,
        ),
    }


# ---------------------------------------------------------------------------
# Verification (used by the official-evaluator wrappers)
# ---------------------------------------------------------------------------


def verify_converter_provenance(
    manifest: dict[str, Any],
    *,
    benchmark: str,
    converter_path: Path | None = None,
    require_git_identity: bool = True,
) -> list[str]:
    """Fail-closed validation of one conversion manifest's converter identity.

    Returns a list of human-readable error codes; an empty list means the manifest
    binds a registered protocol whose recorded bytes and config still reproduce the
    recorded ``identity``.

    ``converter_path`` re-hashes the converter actually on disk. When omitted the
    sibling script named in ``converterSource.path`` is used, so a one-byte edit to
    the converter is caught even if the caller forgets to pass the path.
    """
    errors: list[str] = []
    provenance = manifest.get("converterProvenance")
    if not isinstance(provenance, dict):
        return ["converter_provenance_missing"]

    protocol = provenance.get("protocol")
    if not isinstance(protocol, dict):
        return ["converter_protocol_identity_missing"]
    protocol_id = protocol.get("id")
    protocol_version = protocol.get("version")

    entry = registered_protocol(benchmark, protocol_id, protocol_version)
    if entry is None:
        errors.append(
            f"converter_protocol_not_registered:{benchmark}/{protocol_id}@{protocol_version}"
        )
        return errors

    expected_contract = protocol_contract_sha256(
        benchmark, str(protocol_id), int(protocol_version)
    )
    if protocol.get("contractSha256") != expected_contract:
        errors.append("converter_contract_sha256_does_not_match_registered_protocol")

    source = provenance.get("converterSource")
    if not isinstance(source, dict):
        errors.append("converter_source_identity_missing")
    else:
        resolved = Path(converter_path) if converter_path else None
        if resolved is None and source.get("path"):
            resolved = Path(__file__).resolve().parent / str(source["path"])
        if resolved is not None and Path(resolved).is_file():
            if source.get("sha256") != sha256_file(Path(resolved)):
                errors.append("converter_source_sha256_does_not_match_converter_file")
        elif not is_sha256(source.get("sha256")):
            errors.append("converter_source_sha256_missing_or_malformed")

    config = provenance.get("conversionConfig")
    if not isinstance(config, dict):
        errors.append("conversion_config_missing")
        config = {}
    else:
        unexpected = sorted(set(config) - set(entry["configKeys"]))
        if unexpected:
            errors.append(
                "conversion_config_has_unregistered_keys:" + ",".join(unexpected)
            )
        for key, pinned in entry["pinnedConfig"].items():
            if config.get(key) != pinned:
                errors.append(f"conversion_config_drift:{key}")

    git_identity = provenance.get("benchmarkGit")
    if not isinstance(git_identity, dict) or git_identity.get("available") is not True:
        errors.append("benchmark_git_identity_unavailable")
    elif require_git_identity:
        if not is_git_sha(git_identity.get("commit")):
            errors.append("benchmark_git_commit_not_full_sha")
        if not is_git_sha(git_identity.get("tree")):
            errors.append("benchmark_git_tree_not_full_sha")

    recomputed = conversion_identity(
        benchmark=benchmark,
        protocol_id=str(protocol_id),
        protocol_version=int(protocol_version),
        contract_sha256=str(protocol.get("contractSha256")),
        converter_source_sha256=str((source or {}).get("sha256")),
        conversion_config=config,
    )
    if provenance.get("identity") != recomputed:
        errors.append("conversion_identity_does_not_match_recorded_chain")

    return errors


def compare_conversion_identities(manifests: list[dict[str, Any]]) -> list[str]:
    """Refuse to pool artifacts whose conversion chain differs.

    Issue #66 requires that a converter change "must not silently change only one
    finalist's official score". Callers use this before building one headline, so
    the error appears when the batch contains more than one distinct identity --
    including a malformed or missing one.
    """
    identities: dict[str, list[int]] = {}
    for index, manifest in enumerate(manifests):
        provenance = manifest.get("converterProvenance")
        identity = provenance.get("identity") if isinstance(provenance, dict) else None
        key = identity if is_sha256(identity) else "<missing-or-malformed>"
        identities.setdefault(key, []).append(index)
    missing = identities.get("<missing-or-malformed>")
    if missing:
        return [
            "conversion_identity_missing_for_artifacts:"
            + ",".join(str(i) for i in missing)
        ]
    if len(identities) <= 1:
        return []
    errors: list[str] = []
    rendered = ",".join(
        f"{identity}[{','.join(str(i) for i in members)}]" for identity, members in identities.items()
    )
    errors.append(f"mixed_conversion_identity:{rendered}")
    return errors


__all__ = [
    "CONTRACT_VERSION",
    "CONVERTER_PROTOCOLS",
    "JFLEG_PROTOCOL_ID",
    "SEMANTICQA_PROTOCOL_ID",
    "SWORDS_PROTOCOL_ID",
    "benchmark_git_identity",
    "build_converter_provenance",
    "canonical_json_bytes",
    "compare_conversion_identities",
    "conversion_identity",
    "find_repo_root",
    "is_git_sha",
    "is_sha256",
    "protocol_contract_sha256",
    "registered_protocol",
    "sha256_bytes",
    "sha256_canonical",
    "sha256_file",
    "verify_converter_provenance",
]
