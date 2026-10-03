"""Canonical public Hub source identities and fail-closed revision resolution.

Issue #67. The balanced public-fast screen and the full-distribution prompted
WiC / CoLA / PAWS finalist lane must be able to claim they read the same
validation distribution. They can only do that if one module owns the canonical
Hub repository ID, config, and split for each source, and if a requested branch
or tag is resolved exactly once to a full 40-hex Hub commit before any
`load_dataset` call happens.

This module deliberately imports neither `datasets` nor `huggingface_hub` at
module scope. The locked data-preparation environment supplies those, and the
synthetic regression tests for the mutable-ref, wrong-repo, drift, and
reproducibility contract must run on a bare interpreter.

Grounding (verified against the Hub API and the datasets-server row counts):
- https://huggingface.co/docs/datasets/package_reference/loading_methods
  documents that `load_dataset(revision=...)` accepts "main", tags, and commits.
- https://huggingface.co/docs/huggingface_hub/package_reference/hf_api documents
  `dataset_info(repo_id, revision=...) -> DatasetInfo`, whose `.sha` is the
  repository commit that ref currently names.
- https://huggingface.co/api/datasets/paws answers HTTP 307 to
  `google-research-datasets/paws`, so the bare `paws` name is a redirect and not
  an independent identity. Only the canonical ID is loadable here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent

FULL_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_REQUESTED_REVISION = "main"

#: A request that names a moving ref is never promotion-valid on its own, even
#: when the build resolves it to a commit and records that commit.
MUTABLE_REQUESTS = frozenset(
    {
        "",
        "main",
        "master",
        "head",
        "latest",
        "default",
        "unknown",
        "mutable_default_not_pinned",
    }
)

#: Version of the source-identity contract. Bumped whenever the canonical
#: identities, the gate's required fields, or the receipt shape change, so a
#: scorer can refuse a manifest built under a contract it does not understand.
SOURCE_CONTRACT_VERSION = 1
SOURCE_MANIFEST_SCHEMA = "pari.english-core.public-full-source-manifest"
SOURCE_MANIFEST_FILENAME = "english-core-public-full-sources.json"

#: Every full-distribution build must record this exact one-shot resolution
#: policy in its manifest, so a scorer can tell a resolved build from a manifest
#: that merely copied a user-provided revision string.
REVISION_RESOLUTION_POLICY = "hf-api-dataset-info-sha-once"

#: This lane is separate from the balanced 1,943-case common screen. Nothing here
#: may be used to add full-distribution rows to that screen.
FINALIST_LANE_ID = "public-full-classification"
COMMON_SCREEN_LANE_ID = "public-fast"


@dataclass(frozen=True)
class SourceIdentity:
    """One canonical Hub source identity for a Pari public lane."""

    name: str
    repo_id: str
    config: str | None
    split: str
    cli_flag: str
    headline_metric: str
    role: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "dataset": self.repo_id,
            "config": self.config,
            "split": self.split,
            "headlineMetric": self.headline_metric,
            "role": self.role,
        }


#: Canonical identities. `aps/super_glue` / `wic` and `nyu-mll/glue` / `cola` are
#: the identities both public lanes already load. PAWS is pinned here to the
#: canonical `google-research-datasets/paws`; the bare `paws` identifier is an
#: HTTP 307 redirect to it, so it is recorded as an alias, never loaded.
PUBLIC_SOURCE_IDENTITIES: dict[str, SourceIdentity] = {
    "BLiMP": SourceIdentity(
        name="BLiMP",
        repo_id="nyu-mll/blimp",
        config=None,
        split="train",
        cli_flag="--blimp-revision",
        headline_metric="accuracy",
        role="balanced-fast-screen grammar minimal pairs",
    ),
    "WiC": SourceIdentity(
        name="WiC",
        repo_id="aps/super_glue",
        config="wic",
        split="validation",
        cli_flag="--super-glue-revision",
        headline_metric="accuracy",
        role="full-distribution context-sensitive word sense",
    ),
    "CoLA": SourceIdentity(
        name="CoLA",
        repo_id="nyu-mll/glue",
        config="cola",
        split="validation",
        cli_flag="--glue-revision",
        headline_metric="Matthews correlation coefficient",
        role="full-distribution grammatical acceptability",
    ),
    "PAWS": SourceIdentity(
        name="PAWS",
        repo_id="google-research-datasets/paws",
        config="labeled_final",
        split="validation",
        cli_flag="--paws-revision",
        headline_metric="accuracy",
        role="full-distribution high-overlap adversarial paraphrase",
    ),
}

#: Ordered so manifests, receipts, and gate reports are byte-stable.
FULL_DISTRIBUTION_SOURCE_NAMES: tuple[str, ...] = ("WiC", "CoLA", "PAWS")

#: Retired identifiers that must never be loaded directly. `paws` redirects to
#: the canonical repo, so a manifest that names it has ambiguous provenance.
RETIRED_SOURCE_ALIASES: dict[str, str] = {"paws": "google-research-datasets/paws"}


class SourceIdentityError(RuntimeError):
    """Raised when a source identity cannot be trusted for promotion evidence."""


def source_identity(name: str) -> SourceIdentity:
    try:
        return PUBLIC_SOURCE_IDENTITIES[name]
    except KeyError:
        raise SourceIdentityError(f"unknown public source name {name!r}") from None


def is_full_commit_sha(value: object) -> bool:
    return isinstance(value, str) and bool(FULL_COMMIT_SHA_RE.match(value))


def is_mutable_request(value: object) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in MUTABLE_REQUESTS


def requested_ref(value: object) -> str:
    """Normalize an omitted revision into the Hub's own default ref name."""
    text = "" if value is None else str(value).strip()
    return text or DEFAULT_REQUESTED_REVISION


def has_fingerprint(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value) and all(has_fingerprint(inner) for inner in value.values())
    return False


def resolve_source_commit(api, identity: SourceIdentity, requested: object) -> dict[str, str]:
    """Resolve one requested ref to a full immutable commit, exactly once.

    `api` is a `huggingface_hub.HfApi`. It is injected so the contract can be
    tested without network access, and so the resolution call site stays a
    single auditable line. A commit that the named repository does not contain
    raises: a SHA is only meaningful together with the repo it belongs to.
    """
    requested_revision = requested_ref(requested)
    info = api.dataset_info(identity.repo_id, revision=requested_revision)
    resolved = str(getattr(info, "sha", "") or "")
    if not is_full_commit_sha(resolved):
        raise SourceIdentityError(
            f"could not resolve {identity.repo_id}@{requested_revision} to a full "
            f"40-hex Hub commit SHA: {resolved!r}"
        )
    # The Hub resolves some legacy names (for example bare `paws`) to a canonical
    # repo. Callers always pass the canonical ID, so a mismatch means the caller
    # asked about a repository the canonical identity does not name.
    returned_id = str(getattr(info, "id", "") or "")
    if returned_id and returned_id != identity.repo_id:
        raise SourceIdentityError(
            f"{identity.repo_id}@{requested_revision} resolved to repository "
            f"{returned_id!r}, not the canonical repository"
        )
    return {
        "source": identity.name,
        "dataset": identity.repo_id,
        "config": identity.config,
        "split": identity.split,
        "requestedRevision": requested_revision,
        "resolvedRevision": resolved,
    }


def assert_commit_in_repository(api, repo_id: str, commit: object) -> str:
    """Prove `commit` exists in `repo_id` itself. Raises otherwise.

    This is what makes a commit SHA from the wrong dataset repository a hard
    failure instead of a silent reinterpretation: the Hub only answers for
    commits the repository actually contains.
    """
    if not is_full_commit_sha(commit):
        raise SourceIdentityError(f"{repo_id}: {commit!r} is not a full 40-hex Hub commit SHA")
    try:
        info = api.dataset_info(repo_id, revision=str(commit))
    except Exception as exc:  # any Hub refusal is a rejection
        raise SourceIdentityError(
            f"{repo_id} does not contain commit {commit}; refusing to reinterpret "
            f"another repository's commit ({type(exc).__name__}: {exc})"
        ) from exc
    resolved = str(getattr(info, "sha", "") or "")
    if resolved != str(commit):
        raise SourceIdentityError(
            f"{repo_id} resolved commit {commit} to {resolved!r}; refusing a "
            "repository that does not echo the requested commit"
        )
    return resolved


def resolve_full_distribution_sources(
    api,
    requested: dict[str, object],
    *,
    names: tuple[str, ...] = FULL_DISTRIBUTION_SOURCE_NAMES,
) -> dict[str, dict[str, str]]:
    """Resolve every full-distribution source once, in a stable order."""
    resolved: dict[str, dict[str, str]] = {}
    for name in names:
        identity = source_identity(name)
        record = resolve_source_commit(api, identity, requested.get(name))
        # Membership proof for the resolved commit, so a resolved value can never
        # be a commit belonging to a different repository.
        assert_commit_in_repository(api, identity.repo_id, record["resolvedRevision"])
        resolved[name] = record
    return resolved


# --------------------------------------------------------------------------- #
# Frozen versioned source manifest
# --------------------------------------------------------------------------- #


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_source_table() -> dict[str, dict[str, object]]:
    return {name: identity.as_dict() for name, identity in PUBLIC_SOURCE_IDENTITIES.items()}


def load_frozen_source_manifest(path: Path) -> dict:
    """Read and structurally validate the versioned frozen source manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SourceIdentityError(f"frozen source manifest is missing: {path}") from None
    except json.JSONDecodeError as exc:
        raise SourceIdentityError(f"frozen source manifest is not valid JSON: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise SourceIdentityError(f"frozen source manifest must be a JSON object: {path}")
    if payload.get("schema") != SOURCE_MANIFEST_SCHEMA:
        raise SourceIdentityError(
            f"frozen source manifest schema must be {SOURCE_MANIFEST_SCHEMA!r}, "
            f"got {payload.get('schema')!r}"
        )
    version = payload.get("sourceContractVersion")
    if version != SOURCE_CONTRACT_VERSION:
        raise SourceIdentityError(
            f"frozen source manifest declares sourceContractVersion {version!r}; "
            f"this builder understands {SOURCE_CONTRACT_VERSION}"
        )
    sources = payload.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise SourceIdentityError("frozen source manifest declares no sources")
    missing = [name for name in FULL_DISTRIBUTION_SOURCE_NAMES if name not in sources]
    if missing:
        raise SourceIdentityError(
            f"frozen source manifest is missing full-distribution sources: {missing}"
        )
    return payload


def frozen_source_commits(payload: dict) -> dict[str, str]:
    commits: dict[str, str] = {}
    for name in FULL_DISTRIBUTION_SOURCE_NAMES:
        entry = payload["sources"][name]
        commit = entry.get("resolvedRevision") if isinstance(entry, dict) else None
        if not is_full_commit_sha(commit):
            raise SourceIdentityError(
                f"frozen source manifest pins {name} to {commit!r}, which is not a "
                "full 40-hex Hub commit SHA"
            )
        recorded_repo = entry.get("dataset") if isinstance(entry, dict) else None
        canonical = source_identity(name).repo_id
        if recorded_repo != canonical:
            raise SourceIdentityError(
                f"frozen source manifest names {name} repository {recorded_repo!r}, "
                f"but the canonical repository is {canonical!r}"
            )
        commits[name] = str(commit)
    return commits


def protocol_overrides(payload: dict) -> dict[str, dict]:
    """Reviewed non-canonical repository allowances, if the manifest declares any."""
    raw = payload.get("protocolOverrides")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SourceIdentityError("frozen source manifest protocolOverrides must be an object")
    for name, entry in raw.items():
        if name not in PUBLIC_SOURCE_IDENTITIES:
            raise SourceIdentityError(f"protocolOverrides names unknown source {name!r}")
        if not isinstance(entry, dict) or not entry.get("reviewedIn"):
            raise SourceIdentityError(
                f"protocolOverrides[{name!r}] must record a reviewedIn reference"
            )
    return raw


# --------------------------------------------------------------------------- #
# Promotion gate
# --------------------------------------------------------------------------- #


def source_manifest_gate_report(
    sources: object,
    fingerprints: object,
    *,
    promotion: bool,
    overrides: dict[str, dict] | None = None,
) -> tuple[list[str], list[str]]:
    """Check a builder manifest's source provenance, split by severity.

    Returns `(errors, warnings)`. A mutable requested revision or a missing
    fingerprint is only a warning when `promotion` is false, and an error when
    it is true, so an exploratory build still surfaces exactly why it is not
    promotion evidence instead of passing silently. Structural problems
    (non-canonical repo, retired alias, wrong config/split, unresolved or
    non-full commit, missing resolution policy) are errors in both modes.
    """
    overrides = overrides or {}
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(sources, dict) or not sources:
        return ["manifest declares no sources"], []
    missing = [name for name in FULL_DISTRIBUTION_SOURCE_NAMES if name not in sources]
    if missing:
        errors.append(f"manifest is missing full-distribution sources: {missing}")
    fingerprint_map = fingerprints if isinstance(fingerprints, dict) else {}

    for name in FULL_DISTRIBUTION_SOURCE_NAMES:
        entry = sources.get(name)
        if not isinstance(entry, dict):
            continue
        identity = source_identity(name)
        recorded_repo = entry.get("dataset")
        override = overrides.get(name)
        if recorded_repo != identity.repo_id:
            if override and override.get("dataset") == recorded_repo:
                warnings.append(
                    f"{name}: uses reviewed non-canonical repository {recorded_repo!r} "
                    f"(reviewed in {override.get('reviewedIn')})"
                )
            else:
                errors.append(
                    f"{name}: repository {recorded_repo!r} is not the canonical "
                    f"{identity.repo_id!r}"
                )
        if recorded_repo in RETIRED_SOURCE_ALIASES:
            errors.append(
                f"{name}: manifest names retired alias {recorded_repo!r}; it redirects "
                f"to {RETIRED_SOURCE_ALIASES[recorded_repo]!r} and has no independent identity"
            )
        for field, expected in (("config", identity.config), ("split", identity.split)):
            actual = entry.get(field)
            if actual != expected:
                errors.append(f"{name}: {field} is {actual!r}, expected {expected!r}")

        resolved = entry.get("resolvedRevision")
        if not is_full_commit_sha(resolved):
            errors.append(
                f"{name}: resolvedRevision {resolved!r} is not a full 40-hex Hub commit SHA"
            )
        requested_revision = entry.get("requestedRevision")
        if requested_revision is None:
            errors.append(f"{name}: manifest does not record the requested revision")
        elif is_mutable_request(requested_revision):
            message = f"{name}: requested revision {requested_revision!r} is a moving ref"
            (errors if promotion else warnings).append(message)
        if entry.get("revisionResolution") != REVISION_RESOLUTION_POLICY:
            errors.append(
                f"{name}: revisionResolution must be {REVISION_RESOLUTION_POLICY!r}, "
                f"got {entry.get('revisionResolution')!r}"
            )
        if not has_fingerprint(fingerprint_map.get(name)):
            message = f"{name}: resolved dataset fingerprint missing or empty"
            (errors if promotion else warnings).append(message)

    for name, entry in sources.items():
        if name in FULL_DISTRIBUTION_SOURCE_NAMES:
            continue
        if isinstance(entry, dict) and entry.get("dataset") in RETIRED_SOURCE_ALIASES:
            errors.append(f"{name}: retired dataset alias {entry.get('dataset')!r}")

    return errors, warnings


def source_manifest_gate_errors(
    sources: object,
    fingerprints: object,
    *,
    promotion: bool,
    overrides: dict[str, dict] | None = None,
) -> list[str]:
    """Promotion-acceptance view of the gate.

    An empty list means the recorded source identity is promotion-acceptable.
    Under `promotion=False` the mutable-ref and missing-fingerprint findings are
    still reported, because an exploratory build must never look clean.
    """
    errors, warnings = source_manifest_gate_report(
        sources, fingerprints, promotion=promotion, overrides=overrides
    )
    return errors + warnings if promotion else errors
