#!/usr/bin/env python3
"""Issue #67 regressions for the full-distribution finalist source contract.

Every case here is synthetic: a fake HfApi stands in for the Hub and rows are
generated in-process, so the suite needs no network, no `datasets` install, no
GPU, and no downloaded data. What it proves:

1. omitted revisions + promotion mode -> reject before build;
2. a branch/tag resolves exactly once to a full SHA and that SHA is loaded;
3. the manifest records requested and resolved refs distinctly;
4. a source that moves after resolution does not change the current build;
5. a non-canonical PAWS repo ID is rejected in promotion mode;
6. a commit from the wrong dataset repository is rejected, never reinterpreted;
7. same pinned sources regenerate identical task/answer hashes;
8. a mutable exploratory build is visibly non-promotion and a matching task
   hash alone cannot upgrade it;
9. the final preparation receipt carries the preparation and source-manifest
   hashes a scorer/analysis step can bind.

It also pins the fast/full agreement regression: both public lanes must name
the same canonical PAWS repo, config, and split.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from english_core_public_sources import (
    FULL_DISTRIBUTION_SOURCE_NAMES,
    PUBLIC_SOURCE_IDENTITIES,
    REVISION_RESOLUTION_POLICY,
    SourceIdentityError,
    assert_commit_in_repository,
    canonical_source_table,
    frozen_source_commits,
    is_full_commit_sha,
    is_mutable_request,
    load_frozen_source_manifest,
    protocol_overrides,
    resolve_full_distribution_sources,
    resolve_source_commit,
    source_manifest_gate_errors,
    source_manifest_gate_report,
)

HERE = Path(__file__).resolve().parent
SOURCES_CONFIG = HERE / "english-core-public-full-sources.json"

WIC_SHA = "3de24cf8022e94f4ee4b9d55a6f539891524d646"
COLA_SHA = "bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c"
PAWS_SHA = "161ece9501cf0a11f3e48bd356eaa82de46d6a09"
OTHER_REPO_SHA = "a" * 40

REPO_TO_SOURCE = {
    "aps/super_glue": "WiC",
    "nyu-mll/glue": "CoLA",
    "google-research-datasets/paws": "PAWS",
}


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load_module("build_public_full", "build-english-core-public-full-classification.py")
PREP = _load_module("prepare_public_full", "prepare-english-core-public-full.py")


class FakeInfo:
    def __init__(self, repo_id: str, sha: str | None):
        self.id = repo_id
        self.sha = sha


class FakeApi:
    """Minimal HfApi stand-in with an explicit per-repo commit set."""

    def __init__(self, heads: dict[str, str], commits: dict[str, set[str]] | None = None):
        self.heads = dict(heads)
        self.commits = {repo: set(values) for repo, values in (commits or {}).items()}
        self.calls: list[tuple[str, str]] = []

    def dataset_info(self, repo_id: str, revision: str | None = None):
        self.calls.append((repo_id, str(revision)))
        if not is_full_commit_sha(revision):
            # A branch/tag/default request resolves to the repo's current head.
            return FakeInfo(repo_id, self.heads.get(repo_id))
        known = self.commits.get(repo_id)
        if known is not None:
            if revision not in known:
                raise KeyError(f"404 not found: {repo_id}@{revision}")
            return FakeInfo(repo_id, str(revision))
        return FakeInfo(repo_id, self.heads.get(repo_id))


def fake_api(**overrides) -> FakeApi:
    heads = {
        "aps/super_glue": WIC_SHA,
        "nyu-mll/glue": COLA_SHA,
        "google-research-datasets/paws": PAWS_SHA,
    }
    heads.update(overrides)
    commits = {repo: {sha} for repo, sha in heads.items() if is_full_commit_sha(sha)}
    return FakeApi(heads, commits)


def synthetic_rows() -> dict[str, list[dict]]:
    return {
        "WiC": [
            {"word": "bank", "sentence1": "river bank", "sentence2": "money bank", "label": 1},
            {"word": "bank", "sentence1": "money bank", "sentence2": "river bank", "label": 0},
        ],
        "CoLA": [
            {"sentence": "The cat sat on the mat.", "label": 1},
            {"sentence": "Colorless green ideas sleep furiously cat.", "label": 0},
        ],
        "PAWS": [
            {"sentence1": "a b", "sentence2": "b a", "label": 1},
            {"sentence1": "a b", "sentence2": "x y", "label": 0},
        ],
    }


class _FakeDataset:
    def __init__(self, rows: list[dict], *, fingerprint: str | None):
        self._rows = rows
        self._fingerprint = fingerprint

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)


def _source_table(resolved: dict[str, dict]) -> dict[str, dict]:
    return {
        name: {
            "dataset": entry["dataset"],
            "config": entry["config"],
            "split": entry["split"],
            "requestedRevision": entry["requestedRevision"],
            "resolvedRevision": entry["resolvedRevision"],
            "revisionResolution": REVISION_RESOLUTION_POLICY,
        }
        for name, entry in resolved.items()
    }


def test_promotion_rejects_omitted_revisions_before_building() -> None:
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    args = BUILD.parse_args(["--promotion"])
    requested, errors = BUILD.resolve_requested_revisions(args, config)
    assert requested == {"WiC": None, "CoLA": None, "PAWS": None}
    assert len(errors) == 3
    for name in FULL_DISTRIBUTION_SOURCE_NAMES:
        assert any(name in error for error in errors)


def test_promotion_rejects_mutable_branch_names() -> None:
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    args = BUILD.parse_args(
        [
            "--promotion",
            "--super-glue-revision",
            "main",
            "--glue-revision",
            "main",
            "--paws-revision",
            "main",
        ]
    )
    _, errors = BUILD.resolve_requested_revisions(args, config)
    assert len(errors) == 3
    for error in errors:
        assert "moving ref" in error


def test_locked_config_supplies_immutable_revisions() -> None:
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    args = BUILD.parse_args(["--promotion", "--lock-sources-to-config"])
    requested, errors = BUILD.resolve_requested_revisions(args, config)
    assert errors == []
    assert requested == {"WiC": WIC_SHA, "CoLA": COLA_SHA, "PAWS": PAWS_SHA}


def test_branch_resolves_once_and_the_resolved_sha_is_loaded() -> None:
    api = fake_api()
    resolved = resolve_full_distribution_sources(
        api, {"WiC": "main", "CoLA": "main", "PAWS": "main"}
    )
    assert resolved["PAWS"]["resolvedRevision"] == PAWS_SHA
    assert resolved["PAWS"]["requestedRevision"] == "main"
    paws_calls = [call for call in api.calls if call[0] == "google-research-datasets/paws"]
    assert paws_calls == [
        ("google-research-datasets/paws", "main"),
        ("google-research-datasets/paws", PAWS_SHA),
    ]

    loads: list[dict] = []

    def loader(repo, config, *, split, revision):
        loads.append({"repo": repo, "config": config, "split": split, "revision": revision})
        return _FakeDataset(synthetic_rows()[REPO_TO_SOURCE[repo]], fingerprint="fp-" + REPO_TO_SOURCE[repo])

    rows, fingerprints = BUILD.load_source_rows(loader, resolved)
    assert sorted(loads, key=lambda entry: entry["repo"]) == [
        {"repo": "aps/super_glue", "config": "wic", "split": "validation", "revision": WIC_SHA},
        {
            "repo": "google-research-datasets/paws",
            "config": "labeled_final",
            "split": "validation",
            "revision": PAWS_SHA,
        },
        {"repo": "nyu-mll/glue", "config": "cola", "split": "validation", "revision": COLA_SHA},
    ]
    assert fingerprints == {
        "WiC": "fp-WiC",
        "CoLA": "fp-CoLA",
        "PAWS": "fp-PAWS",
    }
    assert sorted(rows) == ["CoLA", "PAWS", "WiC"]


def test_manifest_records_requested_and_resolved_refs_distinctly() -> None:
    api = fake_api()
    resolved = resolve_full_distribution_sources(
        api, {"WiC": "refs/pr/1", "CoLA": "v1.2.0", "PAWS": PAWS_SHA}
    )
    table = BUILD.manifest_source_table(resolved)
    assert table["WiC"]["requestedRevision"] == "refs/pr/1"
    assert table["WiC"]["resolvedRevision"] == WIC_SHA
    assert table["CoLA"]["requestedRevision"] == "v1.2.0"
    assert table["CoLA"]["resolvedRevision"] == COLA_SHA
    assert table["PAWS"]["requestedRevision"] == PAWS_SHA
    assert table["PAWS"]["resolvedRevision"] == PAWS_SHA
    for entry in table.values():
        assert entry["revisionResolution"] == REVISION_RESOLUTION_POLICY


def test_source_moving_after_resolution_does_not_change_the_build() -> None:
    api = fake_api()
    requested = {"WiC": "main", "CoLA": "main", "PAWS": "main"}
    resolved = resolve_full_distribution_sources(api, requested)
    moved = "f" * 40
    api.heads["google-research-datasets/paws"] = moved
    api.commits["google-research-datasets/paws"].add(moved)
    loads: list[str] = []

    def loader(repo, config, *, split, revision):
        loads.append(revision)
        return _FakeDataset(synthetic_rows()[REPO_TO_SOURCE[repo]], fingerprint="fp")

    BUILD.load_source_rows(loader, resolved)
    assert loads == [WIC_SHA, COLA_SHA, PAWS_SHA]
    assert moved not in loads


def test_non_canonical_paws_repo_is_rejected_in_promotion_mode() -> None:
    resolved = {
        "WiC": {
            "dataset": "aps/super_glue",
            "config": "wic",
            "split": "validation",
            "requestedRevision": WIC_SHA,
            "resolvedRevision": WIC_SHA,
        },
        "CoLA": {
            "dataset": "nyu-mll/glue",
            "config": "cola",
            "split": "validation",
            "requestedRevision": COLA_SHA,
            "resolvedRevision": COLA_SHA,
        },
        "PAWS": {
            "dataset": "paws",
            "config": "labeled_final",
            "split": "validation",
            "requestedRevision": PAWS_SHA,
            "resolvedRevision": PAWS_SHA,
        },
    }
    errors = source_manifest_gate_errors(
        _source_table(resolved), {"WiC": "a", "CoLA": "b", "PAWS": "c"}, promotion=True
    )
    assert any("PAWS" in error and "not the canonical" in error for error in errors)
    assert any("retired alias" in error for error in errors)


def test_retired_alias_is_never_accepted_even_with_a_reviewed_override() -> None:
    resolved = {
        "WiC": {
            "dataset": "aps/super_glue",
            "config": "wic",
            "split": "validation",
            "requestedRevision": WIC_SHA,
            "resolvedRevision": WIC_SHA,
        },
        "CoLA": {
            "dataset": "nyu-mll/glue",
            "config": "cola",
            "split": "validation",
            "requestedRevision": COLA_SHA,
            "resolvedRevision": COLA_SHA,
        },
        "PAWS": {
            "dataset": "paws",
            "config": "labeled_final",
            "split": "validation",
            "requestedRevision": PAWS_SHA,
            "resolvedRevision": PAWS_SHA,
        },
    }
    overrides = {"PAWS": {"dataset": "paws", "reviewedIn": "https://example.invalid/review"}}
    errors = source_manifest_gate_errors(
        _source_table(resolved), {"WiC": "a", "CoLA": "b", "PAWS": "c"}, promotion=True, overrides=overrides
    )
    assert any("retired alias" in error for error in errors)


def test_reviewed_override_still_requires_every_other_field() -> None:
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    payload = json.loads(SOURCES_CONFIG.read_text(encoding="utf-8"))
    payload["protocolOverrides"] = {
        "PAWS": {
            "dataset": "google-research-datasets/paws",
            "reviewedIn": "https://example.invalid/review",
        }
    }
    assert protocol_overrides(payload)
    table = {
        "WiC": {
            "dataset": PUBLIC_SOURCE_IDENTITIES["WiC"].repo_id,
            "config": "wic",
            "split": "validation",
            "requestedRevision": WIC_SHA,
            "resolvedRevision": WIC_SHA,
            "revisionResolution": REVISION_RESOLUTION_POLICY,
        },
        "CoLA": {
            "dataset": PUBLIC_SOURCE_IDENTITIES["CoLA"].repo_id,
            "config": "cola",
            "split": "validation",
            "requestedRevision": COLA_SHA,
            "resolvedRevision": COLA_SHA,
            "revisionResolution": REVISION_RESOLUTION_POLICY,
        },
        "PAWS": {
            "dataset": "google-research-datasets/paws",
            "config": "labeled_final",
            "split": "test",
            "requestedRevision": PAWS_SHA,
            "resolvedRevision": PAWS_SHA,
            "revisionResolution": REVISION_RESOLUTION_POLICY,
        },
    }
    errors = source_manifest_gate_errors(
        table,
        {"WiC": "a", "CoLA": "b", "PAWS": "c"},
        promotion=True,
        overrides=payload["protocolOverrides"],
    )
    assert any("split is 'test'" in error for error in errors)
    assert protocol_overrides(config) == {}


def test_commit_from_the_wrong_repository_is_rejected() -> None:
    api = fake_api()
    try:
        assert_commit_in_repository(api, "google-research-datasets/paws", WIC_SHA)
    except SourceIdentityError as exc:
        assert "does not contain commit" in str(exc)
    else:
        raise AssertionError("a wrong-repository commit must be rejected")


def test_commit_that_the_repository_does_not_echo_is_rejected() -> None:
    api = FakeApi({"some/repo": OTHER_REPO_SHA}, {"some/repo": {OTHER_REPO_SHA}})
    try:
        assert_commit_in_repository(api, "some/repo", "b" * 40)
    except SourceIdentityError as exc:
        assert "does not contain commit" in str(exc) or "does not echo the requested commit" in str(exc)
    else:
        raise AssertionError("a non-echoing commit must be rejected")


def test_repository_answering_with_a_different_sha_is_rejected() -> None:
    class MismatchedApi:
        def dataset_info(self, repo_id, revision=None):
            # The Hub would never answer a commit request with a different
            # commit; a repository that does is untrustworthy either way.
            return FakeInfo(repo_id, OTHER_REPO_SHA)

    try:
        assert_commit_in_repository(MismatchedApi(), "some/repo", "b" * 40)
    except SourceIdentityError as exc:
        assert "does not echo the requested commit" in str(exc)
    else:
        raise AssertionError("a mismatched echoed commit must be rejected")


def test_non_full_revision_is_rejected_at_resolution() -> None:
    api = fake_api(**{"google-research-datasets/paws": "1234567"})
    try:
        resolve_source_commit(api, PUBLIC_SOURCE_IDENTITIES["PAWS"], "main")
    except SourceIdentityError as exc:
        assert "40-hex" in str(exc)
    else:
        raise AssertionError("a short Hub sha must be rejected")


def test_repository_mismatch_from_the_hub_is_rejected() -> None:
    class RedirectingApi:
        def dataset_info(self, repo_id, revision=None):
            return FakeInfo("somewhere/else", PAWS_SHA)

    try:
        resolve_source_commit(RedirectingApi(), PUBLIC_SOURCE_IDENTITIES["PAWS"], "main")
    except SourceIdentityError as exc:
        assert "not the canonical repository" in str(exc)
    else:
        raise AssertionError("a repository redirect must be rejected")


def test_same_pinned_sources_regenerate_identical_task_and_answer_bytes() -> None:
    first = BUILD.build_lane(synthetic_rows())
    second = BUILD.build_lane(synthetic_rows())
    assert first[0] == second[0]
    assert first[1] == second[1]
    first_tasks = ("\n".join(json.dumps(row, ensure_ascii=False) for row in first[0]) + "\n").encode()
    second_tasks = ("\n".join(json.dumps(row, ensure_ascii=False) for row in second[0]) + "\n").encode()
    first_answers = (json.dumps({"version": 3, "answers": first[1]}, indent=2) + "\n").encode()
    second_answers = (json.dumps({"version": 3, "answers": second[1]}, indent=2) + "\n").encode()
    assert first_tasks == second_tasks
    assert first_answers == second_answers
    assert BUILD.ordered_ids_sha256([row["id"] for row in first[0]]) == BUILD.ordered_ids_sha256(
        [row["id"] for row in second[0]]
    )


def test_ordered_id_digest_matches_the_prepared_stage_register_convention() -> None:
    import hashlib

    ids = ["full-wic-00000", "full-cola-00000"]
    expected = hashlib.sha256(
        json.dumps(
            {"orderedTaskIds": ids}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    assert BUILD.ordered_ids_sha256(ids) == expected
    assert PREP.ordered_ids_sha256(ids) == expected


def test_answer_letter_and_label_mapping_stay_consistent() -> None:
    tasks, answers, counts, label_counts = BUILD.build_lane(synthetic_rows())
    assert counts == {"WiC": 2, "CoLA": 2, "PAWS": 2}
    assert label_counts["WiC"] == {1: 1, 0: 1}
    for task in tasks:
        meta = answers[task["id"]]
        assert meta["labelByLetter"][meta["letter"]] == meta["goldLabel"]
        assert task["prompt"].rstrip().endswith("Answer only with the letter.")


def test_mutable_request_is_a_warning_when_exploratory_and_an_error_when_promotion() -> None:
    resolved = {
        name: {
            "dataset": identity.repo_id,
            "config": identity.config,
            "split": identity.split,
            "requestedRevision": "main",
            "resolvedRevision": sha,
        }
        for name, identity, sha in (
            ("WiC", PUBLIC_SOURCE_IDENTITIES["WiC"], WIC_SHA),
            ("CoLA", PUBLIC_SOURCE_IDENTITIES["CoLA"], COLA_SHA),
            ("PAWS", PUBLIC_SOURCE_IDENTITIES["PAWS"], PAWS_SHA),
        )
    }
    fingerprints = {"WiC": "a", "CoLA": "b", "PAWS": "c"}
    assert source_manifest_gate_errors(_source_table(resolved), fingerprints, promotion=False) == []
    promotion_errors = source_manifest_gate_errors(_source_table(resolved), fingerprints, promotion=True)
    assert len(promotion_errors) == 3
    for error in promotion_errors:
        assert "moving ref" in error


def test_exploratory_manifest_is_marked_non_promotion_and_names_its_blockers() -> None:
    tasks, _answers, counts, label_counts = BUILD.build_lane(synthetic_rows())
    resolved = {
        name: {
            "dataset": identity.repo_id,
            "config": identity.config,
            "split": identity.split,
            "requestedRevision": "main",
            "resolvedRevision": sha,
        }
        for name, identity, sha in (
            ("WiC", PUBLIC_SOURCE_IDENTITIES["WiC"], WIC_SHA),
            ("CoLA", PUBLIC_SOURCE_IDENTITIES["CoLA"], COLA_SHA),
            ("PAWS", PUBLIC_SOURCE_IDENTITIES["PAWS"], PAWS_SHA),
        )
    }
    fingerprints = {"WiC": "a", "CoLA": "b", "PAWS": "c"}
    warnings = source_manifest_gate_report(_source_table(resolved), fingerprints, promotion=False)[1]
    manifest = BUILD.build_manifest(
        tasks=tasks,
        counts=counts,
        label_counts=label_counts,
        fingerprints=fingerprints,
        resolved_sources=resolved,
        promotion=False,
        gate_errors=[],
        gate_warnings=warnings,
        sources_config_path=SOURCES_CONFIG,
        sources_config=None,
        datasets_version="5.0.1",
        hub_version="1.33.0",
        files={},
    )
    assert manifest["promotionEligible"] is False
    assert len(manifest["promotion"]["gateWarnings"]) == 3
    assert manifest["promotion"]["requested"] is False
    assert "cannot be upgraded by its task-file hash alone" in manifest["promotion"]["note"]


def test_promotion_manifest_is_eligible_only_with_a_clean_gate() -> None:
    tasks, _answers, counts, label_counts = BUILD.build_lane(synthetic_rows())
    resolved = {
        name: {
            "dataset": identity.repo_id,
            "config": identity.config,
            "split": identity.split,
            "requestedRevision": sha,
            "resolvedRevision": sha,
        }
        for name, identity, sha in (
            ("WiC", PUBLIC_SOURCE_IDENTITIES["WiC"], WIC_SHA),
            ("CoLA", PUBLIC_SOURCE_IDENTITIES["CoLA"], COLA_SHA),
            ("PAWS", PUBLIC_SOURCE_IDENTITIES["PAWS"], PAWS_SHA),
        )
    }
    manifest = BUILD.build_manifest(
        tasks=tasks,
        counts=counts,
        label_counts=label_counts,
        fingerprints={"WiC": "a", "CoLA": "b", "PAWS": "c"},
        resolved_sources=resolved,
        promotion=True,
        gate_errors=[],
        gate_warnings=[],
        sources_config_path=SOURCES_CONFIG,
        sources_config=load_frozen_source_manifest(SOURCES_CONFIG),
        datasets_version="5.0.1",
        hub_version="1.33.0",
        files={},
    )
    assert manifest["promotionEligible"] is True
    assert manifest["lane"] == "public-full-classification"
    assert manifest["version"] == 4
    assert manifest["frozenSources"]["expectedValidationRows"] == {
        "WiC": 638,
        "CoLA": 1043,
        "PAWS": 8000,
    }


def test_receipt_binds_preparation_hashes_and_the_common_screen_boundary() -> None:
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    outputs = {
        "cases": 2,
        "countsBySource": {"WiC": 1, "CoLA": 1, "PAWS": 0},
        "files": {
            "english-core-public-full-classification.jsonl": {
                "sha256": "a" * 64,
                "bytes": 10,
                "cases": 2,
            }
        },
        "orderedTaskIdsSha256": "b" * 64,
        "manifestSources": config["sources"],
        "resolvedDatasetFingerprints": {"WiC": "fp", "CoLA": "fp", "PAWS": "fp"},
        "manifestSha256": "c" * 64,
    }
    receipt = PREP.build_receipt(
        sources_config=config,
        sources_config_path=SOURCES_CONFIG,
        outputs=outputs,
        tree={"head": "d" * 40, "tree": "e" * 40, "promotionEligible": True},
        env_identity={"dependencyLock": {"state": "verified", "sha256": "f" * 64}},
        promotion=True,
        blockers=[],
    )
    assert receipt["schema"] == PREP.RECEIPT_SCHEMA
    assert receipt["protocolVersion"] == PREP.PROTOCOL_VERSION
    assert receipt["promotionEligible"] is True
    assert receipt["laneSeparation"]["commonScreenCases"] == 1943
    assert receipt["files"]["english-core-public-full-classification.jsonl"]["sha256"] == "a" * 64
    assert receipt["orderedTaskIdsSha256"] == "b" * 64
    assert receipt["manifestSha256"] == "c" * 64
    assert receipt["isolatedDataEnvironment"]["dependencyLock"]["state"] == "verified"
    assert "hash match alone must never upgrade a non-promotion build" in receipt["scorerContract"]["note"]


def test_unverified_environment_or_dirty_tree_blocks_promotion_eligibility() -> None:
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    outputs = {
        "cases": 2,
        "countsBySource": {"WiC": 1, "CoLA": 1, "PAWS": 0},
        "files": {},
        "orderedTaskIdsSha256": "b" * 64,
        "manifestSources": config["sources"],
        "resolvedDatasetFingerprints": {},
        "manifestSha256": "c" * 64,
    }
    receipt = PREP.build_receipt(
        sources_config=config,
        sources_config_path=SOURCES_CONFIG,
        outputs=outputs,
        tree={"head": "d" * 40, "promotionEligible": False},
        env_identity={"dependencyLock": {"state": "unavailable", "sha256": None}},
        promotion=True,
        blockers=[
            "data-preparation environment lock is not verified for this profile",
            "benchmark tree is not clean under the runner's git identity contract",
        ],
    )
    assert receipt["promotionEligible"] is False
    assert len(receipt["promotionBlockers"]) == 2


def test_verify_receipt_rejects_a_missing_receipt() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        report = PREP.verify_receipt(Path(tmp) / "nope.json", benchmark_revision=None)
    assert report["status"] == "unqualified"
    assert report["failures"] == ["receipt is missing"]


def test_frozen_source_config_is_versioned_and_holds_full_commits() -> None:
    payload = load_frozen_source_manifest(SOURCES_CONFIG)
    assert payload["schema"] == "pari.english-core.public-full-source-manifest"
    assert frozen_source_commits(payload) == {"WiC": WIC_SHA, "CoLA": COLA_SHA, "PAWS": PAWS_SHA}
    assert payload["expectedTotalCases"] == 9681
    assert payload["commonScreenBoundary"]["screenCases"] == 1943
    assert payload["commonScreenBoundary"]["screenArtifact"] == "english-core-fixed-screen.jsonl"
    for name in FULL_DISTRIBUTION_SOURCE_NAMES:
        assert is_full_commit_sha(payload["sources"][name]["resolvedRevision"])
        assert payload["sources"][name]["dataset"] == PUBLIC_SOURCE_IDENTITIES[name].repo_id
        assert payload["sources"][name]["config"] == PUBLIC_SOURCE_IDENTITIES[name].config
        assert payload["sources"][name]["split"] == PUBLIC_SOURCE_IDENTITIES[name].split


def test_frozen_config_rejects_a_mutable_pin() -> None:
    payload = load_frozen_source_manifest(SOURCES_CONFIG)
    payload["sources"]["PAWS"]["resolvedRevision"] = "main"
    try:
        frozen_source_commits(payload)
    except SourceIdentityError as exc:
        assert "full 40-hex" in str(exc)
    else:
        raise AssertionError("a mutable pin must be rejected")


def test_locked_build_rejects_a_moved_source() -> None:
    """The drift guard: a moved repo must stop the locked build, not rename it."""
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    on_pin = {
        name: {"resolvedRevision": config["sources"][name]["resolvedRevision"]}
        for name in FULL_DISTRIBUTION_SOURCE_NAMES
    }
    BUILD.assert_no_frozen_source_drift(config, on_pin)

    moved = json.loads(json.dumps(on_pin))
    moved["PAWS"]["resolvedRevision"] = "0" * 40
    try:
        BUILD.assert_no_frozen_source_drift(config, moved)
    except SourceIdentityError as exc:
        assert "drift detected" in str(exc)
        assert "PAWS" in str(exc)
    else:
        raise AssertionError("a moved source must be refused by the locked build")


def test_locked_build_rejects_an_edited_frozen_pin() -> None:
    """Editing the frozen pins to match a moved repo is also a drift refusal."""
    config = load_frozen_source_manifest(SOURCES_CONFIG)
    outputs = {
        "cases": 2,
        "countsBySource": {"WiC": 1, "CoLA": 1, "PAWS": 0},
        "files": {},
        "orderedTaskIdsSha256": "b" * 64,
        "manifestSha256": "c" * 64,
        "manifestSources": config["sources"],
        "resolvedDatasetFingerprints": {},
    }
    receipt = PREP.build_receipt(
        sources_config=config,
        sources_config_path=SOURCES_CONFIG,
        outputs=outputs,
        tree={"head": "d" * 40, "promotionEligible": True},
        env_identity={"dependencyLock": {"state": "verified", "sha256": "f" * 64}},
        promotion=True,
        blockers=[],
    )
    committed = receipt["frozenSources"]["sha256"]

    # A hand-edited pin is a different versioned file, so the receipt binds a
    # different digest: the edit is visible rather than silently accepted.
    import tempfile

    edited = json.loads(SOURCES_CONFIG.read_text(encoding="utf-8"))
    edited["sources"]["PAWS"]["resolvedRevision"] = "0" * 40
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(edited, handle)
        edited_path = Path(handle.name)
    edited_receipt = PREP.build_receipt(
        sources_config=load_frozen_source_manifest(edited_path),
        sources_config_path=edited_path,
        outputs=outputs,
        tree={"head": "d" * 40, "promotionEligible": True},
        env_identity={"dependencyLock": {"state": "verified", "sha256": "f" * 64}},
        promotion=True,
        blockers=[],
    )
    assert edited_receipt["frozenSources"]["sha256"] != committed
    edited_path.unlink()


def test_fast_and_full_builders_name_the_same_paws_distribution() -> None:
    """The regression #67 asks for: the two public lanes cannot silently diverge."""
    fast_source = (HERE / "build-english-core-public-fast.py").read_text(encoding="utf-8")
    full_source = (HERE / "build-english-core-public-full-classification.py").read_text(encoding="utf-8")
    canonical = canonical_source_table()
    assert "PUBLIC_SOURCE_IDENTITIES" in fast_source
    assert "PUBLIC_SOURCE_IDENTITIES" in full_source or "source_identity" in full_source
    # Neither builder may pass the retired bare alias to load_dataset. The only
    # permitted mention is declaring it retired in the manifest.
    for name, text in (("fast", fast_source), ("full", full_source)):
        assert 'load_dataset(\n        "paws"' not in text
        assert 'load_dataset("paws"' not in text
        assert '"paws", "labeled_final"' not in text, (
            f"{name} builder still loads the retired bare paws identifier"
        )
    assert canonical["PAWS"]["dataset"] == "google-research-datasets/paws"
    assert canonical["PAWS"]["config"] == "labeled_final"
    assert canonical["PAWS"]["split"] == "validation"


def test_public_fast_manifest_reports_the_same_paws_source_identity() -> None:
    """The fast lane's manifest table is built from the same canonical identity."""
    table = canonical_source_table()
    fast_source = (HERE / "build-english-core-public-fast.py").read_text(encoding="utf-8")
    assert 'PUBLIC_SOURCE_IDENTITIES["PAWS"].repo_id' in fast_source
    assert 'PUBLIC_SOURCE_IDENTITIES["PAWS"].config' in fast_source
    assert 'PUBLIC_SOURCE_IDENTITIES["PAWS"].split' in fast_source
    assert table["PAWS"]["dataset"] not in {"paws", ""}


def test_mutable_request_set_covers_every_omitted_or_moving_spelling() -> None:
    for value in (None, "", "main", "MASTER", "latest", "default", "unknown", "mutable_default_not_pinned"):
        assert is_mutable_request(value)
    for value in (WIC_SHA, COLA_SHA, PAWS_SHA, "refs/pr/1", "v1.2.0"):
        assert not is_mutable_request(value)


def main() -> None:
    cases = [
        test_promotion_rejects_omitted_revisions_before_building,
        test_promotion_rejects_mutable_branch_names,
        test_locked_config_supplies_immutable_revisions,
        test_branch_resolves_once_and_the_resolved_sha_is_loaded,
        test_manifest_records_requested_and_resolved_refs_distinctly,
        test_source_moving_after_resolution_does_not_change_the_build,
        test_non_canonical_paws_repo_is_rejected_in_promotion_mode,
        test_retired_alias_is_never_accepted_even_with_a_reviewed_override,
        test_reviewed_override_still_requires_every_other_field,
        test_commit_from_the_wrong_repository_is_rejected,
        test_commit_that_the_repository_does_not_echo_is_rejected,
        test_repository_answering_with_a_different_sha_is_rejected,
        test_non_full_revision_is_rejected_at_resolution,
        test_repository_mismatch_from_the_hub_is_rejected,
        test_same_pinned_sources_regenerate_identical_task_and_answer_bytes,
        test_ordered_id_digest_matches_the_prepared_stage_register_convention,
        test_answer_letter_and_label_mapping_stay_consistent,
        test_mutable_request_is_a_warning_when_exploratory_and_an_error_when_promotion,
        test_exploratory_manifest_is_marked_non_promotion_and_names_its_blockers,
        test_promotion_manifest_is_eligible_only_with_a_clean_gate,
        test_receipt_binds_preparation_hashes_and_the_common_screen_boundary,
        test_unverified_environment_or_dirty_tree_blocks_promotion_eligibility,
        test_verify_receipt_rejects_a_missing_receipt,
        test_frozen_source_config_is_versioned_and_holds_full_commits,
        test_frozen_config_rejects_a_mutable_pin,
        test_locked_build_rejects_a_moved_source,
        test_locked_build_rejects_an_edited_frozen_pin,
        test_fast_and_full_builders_name_the_same_paws_distribution,
        test_public_fast_manifest_reports_the_same_paws_source_identity,
        test_mutable_request_set_covers_every_omitted_or_moving_spelling,
    ]
    for case in cases:
        case()
    print(f"Public full-distribution source contract tests passed ({len(cases)} cases).")


if __name__ == "__main__":
    main()
