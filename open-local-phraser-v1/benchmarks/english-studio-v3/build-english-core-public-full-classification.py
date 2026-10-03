"""Build full-distribution prompted public classification tasks for English Core.

Issue #67. This lane is separate from:
- the balanced public-fast screen; and
- benchmark-native likelihood/generation protocols such as BLiMP/SWORDS/JFLEG.

It preserves the locally scoreable validation distribution for WiC, CoLA and
PAWS-Wiki so classification metrics are not distorted by Pari's fast-screen
balancing.

Source-identity contract:
- WiC, CoLA and PAWS have one canonical Hub repository ID, config, and split,
  owned by `english_core_public_sources.py` so this builder and the public-fast
  screen cannot drift semantically.
- Every requested ref (branch, tag, commit, or an omitted revision) is resolved
  exactly once through `HfApi.dataset_info(repo_id, revision=ref).sha` to a full
  40-hex commit, and that commit is proved to live in that repository.
- Loading always uses the resolved commit, never the requested ref, so a source
  that moves after resolution cannot change an in-flight build.
- The manifest records the requested ref and the resolved commit separately.

Modes:
- Exploratory (default): mutable refs are allowed but the manifest is marked
  `promotionEligible: false` and records every non-promotion reason.
- `--promotion`: fails closed before loading anything if any source identity is
  mutable, non-canonical, unresolved, or wrong-repository.
- `--lock-sources-to-config`: fills omitted revisions from the frozen versioned
  source manifest and requires the resolved commits to equal the frozen pins.
  Without it, an omitted revision under `--promotion` is a hard error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from english_core_public_sources import (
    FINALIST_LANE_ID,
    FULL_DISTRIBUTION_SOURCE_NAMES,
    REVISION_RESOLUTION_POLICY,
    SOURCE_CONTRACT_VERSION,
    SOURCE_MANIFEST_FILENAME,
    SourceIdentityError,
    frozen_source_commits,
    is_mutable_request,
    load_frozen_source_manifest,
    protocol_overrides,
    resolve_full_distribution_sources,
    sha256_file,
    source_identity,
    source_manifest_gate_report,
)

HERE = Path(__file__).resolve().parent
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

TASK_FILE = HERE / "english-core-public-full-classification.jsonl"
ANSWER_FILE = HERE / "english-core-public-full-classification.answers.json"
MANIFEST_FILE = HERE / "english-core-public-full-classification.manifest.json"
DEFAULT_SOURCES_CONFIG = HERE / SOURCE_MANIFEST_FILENAME

#: Prompts and per-source dimensions. Kept as data so the row->task transform is
#: pure and testable without any dataset dependency.
SOURCE_SPECS: dict[str, dict] = {
    "WiC": {
        "dimension": "lexical_context",
        "phenomenon": "word_sense_discrimination",
        "taskPrefix": "full-wic-",
        "choices": ["same", "different"],
        "prefix": lambda row: (
            f"Target word: {row['word']}\n"
            f"Sentence 1: {row['sentence1']}\n"
            f"Sentence 2: {row['sentence2']}\n"
            "Does the target have the same meaning in both sentences?"
        ),
    },
    "CoLA": {
        "dimension": "grammar_syntax",
        "phenomenon": "acceptability",
        "taskPrefix": "full-cola-",
        "choices": ["acceptable", "unacceptable"],
        "prefix": lambda row: (
            f"Sentence: {row['sentence']}\nIs this sentence acceptable in standard written English?"
        ),
    },
    "PAWS": {
        "dimension": "paraphrase_semantics",
        "phenomenon": "high_overlap_paraphrase",
        "taskPrefix": "full-paws-",
        "choices": ["same", "different"],
        "prefix": lambda row: (
            f"Sentence 1: {row['sentence1']}\n"
            f"Sentence 2: {row['sentence2']}\n"
            "Do these sentences preserve the same meaning?"
        ),
    },
}


def permute_choices(task_id: str, choices: list[str], correct_index: int) -> tuple[list[str], str, list[int]]:
    order = list(range(len(choices)))
    for i in range(len(order) - 1, 0, -1):
        digest = hashlib.sha256(f"{task_id}:option:{i}".encode()).digest()
        j = int.from_bytes(digest[:4], "big") % (i + 1)
        order[i], order[j] = order[j], order[i]
    shuffled = [choices[i] for i in order]
    return shuffled, LETTERS[order.index(correct_index)], order


def choice_prompt(prefix: str, choices: list[str]) -> str:
    rendered = "\n".join(f"{LETTERS[i]}. {choice}" for i, choice in enumerate(choices))
    return f"{prefix}\n{rendered}\nAnswer only with the letter."


def ordered_ids_sha256(ids: list[str]) -> str:
    """The canonical ordered-task-ID digest shared with the prepared stage register."""
    payload = json.dumps(
        {"orderedTaskIds": list(ids)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_lane(
    rows_by_source: dict[str, list[dict]]
) -> tuple[list[dict], dict[str, dict], Counter, dict[str, Counter]]:
    """Deterministic, dataset-independent task/answer construction."""
    tasks: list[dict] = []
    answers: dict[str, dict] = {}
    counts: Counter = Counter()
    label_counts: dict[str, Counter] = {}
    # The first choice is class 1 in every source's own labelling, the second class 0.
    binary_choice_labels = [1, 0]

    for source in FULL_DISTRIBUTION_SOURCE_NAMES:
        spec = SOURCE_SPECS[source]
        for index, row in enumerate(rows_by_source[source]):
            label = int(row["label"])
            task_id = f"{spec['taskPrefix']}{index:05d}"
            choices = list(spec["choices"])
            correct_index = 0 if label == 1 else 1
            shuffled, letter, order = permute_choices(task_id, choices, correct_index)
            label_by_letter = {
                LETTERS[new_index]: int(binary_choice_labels[original_index])
                for new_index, original_index in enumerate(order)
            }
            tasks.append(
                {
                    "id": task_id,
                    "source": source,
                    "dimension": spec["dimension"],
                    "phenomenon": spec["phenomenon"],
                    "prompt": choice_prompt(spec["prefix"](row), shuffled),
                    "generative": False,
                }
            )
            answers[task_id] = {
                "letter": letter,
                "goldLabel": int(label),
                "labelByLetter": label_by_letter,
            }
            counts[source] += 1
            label_counts.setdefault(source, Counter())[int(label)] += 1

    return tasks, answers, counts, label_counts


def load_source_rows(
    loader, resolved_sources: dict[str, dict[str, str]]
) -> tuple[dict[str, list[dict]], dict[str, str | None]]:
    """Load every source at its resolved immutable commit, preserving row order."""
    rows_by_source: dict[str, list[dict]] = {}
    fingerprints: dict[str, str | None] = {}
    for source in FULL_DISTRIBUTION_SOURCE_NAMES:
        record = resolved_sources[source]
        identity = source_identity(source)
        dataset = loader(
            record["dataset"],
            identity.config,
            split=identity.split,
            revision=record["resolvedRevision"],
        )
        rows_by_source[source] = list(dataset)
        fingerprints[source] = getattr(dataset, "_fingerprint", None)
    return rows_by_source, fingerprints


def manifest_source_table(resolved_sources: dict[str, dict[str, str]]) -> dict[str, dict]:
    sources: dict[str, dict] = {}
    for source in FULL_DISTRIBUTION_SOURCE_NAMES:
        identity = source_identity(source)
        record = resolved_sources[source]
        sources[source] = {
            "dataset": identity.repo_id,
            "config": identity.config,
            "split": identity.split,
            "headlineMetric": identity.headline_metric,
            "requestedRevision": record["requestedRevision"],
            "resolvedRevision": record["resolvedRevision"],
            "revisionResolution": REVISION_RESOLUTION_POLICY,
        }
    return sources


def build_manifest(
    *,
    tasks: list[dict],
    counts: Counter,
    label_counts: dict[str, Counter],
    fingerprints: dict[str, str | None],
    resolved_sources: dict[str, dict[str, str]],
    promotion: bool,
    gate_errors: list[str],
    gate_warnings: list[str],
    sources_config_path: Path,
    sources_config: dict | None,
    datasets_version: str | None,
    hub_version: str | None,
    files: dict[str, dict],
) -> dict:
    sources = manifest_source_table(resolved_sources)
    return {
        "version": 4,
        "sourceContractVersion": SOURCE_CONTRACT_VERSION,
        "lane": FINALIST_LANE_ID,
        "purpose": "full-distribution prompted classification lane; distinct from the balanced fast screen and benchmark-native protocols",
        "promotionEligible": bool(promotion and not gate_errors),
        "promotion": {
            "requested": bool(promotion),
            "gateErrors": gate_errors,
            "gateWarnings": gate_warnings,
            "note": (
                "promotionEligible is true only when --promotion was requested and every "
                "source is canonical, fully resolved to a commit present in its own "
                "repository, and fingerprinted. An exploratory build stays visibly "
                "non-promotion and cannot be upgraded by its task-file hash alone."
            ),
        },
        "cases": len(tasks),
        "countsBySource": dict(counts),
        "labelCountsBySource": {k: dict(v) for k, v in label_counts.items()},
        "datasetsLibraryVersion": datasets_version,
        "huggingfaceHubLibraryVersion": hub_version,
        "resolvedDatasetFingerprints": fingerprints,
        "revisionPolicy": (
            "Every requested Hub revision (including an omitted default, a branch, or a "
            "tag) is resolved exactly once to a full 40-hex commit via "
            "HfApi.dataset_info(repo_id, revision=ref).sha, proved to live in the "
            "canonical repository, and used for loading. requestedRevision and "
            "resolvedRevision are recorded separately."
        ),
        "sourceIdentity": {
            "canonicalPolicy": (
                "Canonical Hub repo ID, config, and split are owned by "
                "english_core_public_sources.py and shared with the public-fast screen "
                "so the two lanes cannot drift."
            ),
            "retiredAliases": {"paws": "google-research-datasets/paws"},
        },
        "frozenSources": {
            "file": sources_config_path.name,
            "present": sources_config is not None,
            "sha256": sha256_file(sources_config_path) if sources_config_path.is_file() else None,
            "lane": sources_config.get("lane") if sources_config else None,
            "expectedValidationRows": {
                name: sources_config["sources"][name].get("expectedValidationRows")
                for name in FULL_DISTRIBUTION_SOURCE_NAMES
            }
            if sources_config
            else None,
        },
        "orderedTaskIdsSha256": ordered_ids_sha256([task["id"] for task in tasks]),
        "optionOrder": "deterministic SHA-256 permutation per item; answer file preserves displayed-letter-to-class mapping",
        "distributionPolicy": "no Pari label balancing or subsampling; preserve each locally scoreable validation distribution",
        "adaptation": "zero-shot prompted classification; not identical to supervised benchmark-native model adaptation",
        "commonScreenBoundary": (
            "This lane is separate from the balanced 1,943-case common screen "
            "(public-fast + shadow + SemanticQA LCC). These full-distribution rows must "
            "never be merged into that screen."
        ),
        "files": files,
        "sources": sources,
        "researchReferences": {
            "WiC": "https://aclanthology.org/N19-1128/",
            "CoLA": "https://aclanthology.org/Q19-1040/",
            "PAWS": "https://aclanthology.org/N19-1131/",
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--super-glue-revision", default=None)
    ap.add_argument("--glue-revision", default=None)
    ap.add_argument("--paws-revision", default=None)
    ap.add_argument(
        "--sources-config",
        type=Path,
        default=DEFAULT_SOURCES_CONFIG,
        help="Versioned frozen source manifest; supplies canonical identities and frozen commits.",
    )
    ap.add_argument(
        "--lock-sources-to-config",
        action="store_true",
        help="Fill omitted revisions from the frozen sources config and require the resolved commits to equal its pins.",
    )
    ap.add_argument(
        "--promotion",
        action="store_true",
        help="Fail closed unless every source identity is canonical, fully resolved, and fingerprinted.",
    )
    return ap.parse_args(argv)


def resolve_requested_revisions(
    args: argparse.Namespace, sources_config: dict | None
) -> tuple[dict[str, object], list[str]]:
    """Decide the requested ref for each source and fail closed on promotion gaps."""
    cli = {
        "WiC": args.super_glue_revision,
        "CoLA": args.glue_revision,
        "PAWS": args.paws_revision,
    }
    errors: list[str] = []
    frozen = frozen_source_commits(sources_config) if sources_config else {}
    requested: dict[str, object] = {}
    for name in FULL_DISTRIBUTION_SOURCE_NAMES:
        supplied = cli[name]
        if supplied is None and args.lock_sources_to_config and name in frozen:
            requested[name] = frozen[name]
            continue
        if supplied is None:
            requested[name] = None
            if args.promotion:
                errors.append(
                    f"{name}: no revision supplied and --lock-sources-to-config was not "
                    "used; promotion requires an immutable requested ref"
                )
            continue
        requested[name] = supplied
        if args.promotion and is_mutable_request(supplied):
            errors.append(
                f"{name}: requested revision {supplied!r} is a moving ref; promotion "
                "requires a full commit SHA or an explicit frozen-source lock"
            )
    return requested, errors


def _hub_version() -> str | None:
    try:
        import huggingface_hub
        return huggingface_hub.__version__
    except Exception:  # pragma: no cover - defensive only
        return None


def assert_no_frozen_source_drift(
    sources_config: dict, resolved_sources: dict[str, dict[str, str]]
) -> None:
    """A locked build must land on exactly the frozen commits, or it is refused.

    This is the #67 drift guard: if a Hub repo moved, or the frozen pins were
    edited, the two disagree and the lane stops rather than silently producing
    a different distribution under the same name.
    """
    frozen = frozen_source_commits(sources_config)
    drift = {
        name: (frozen[name], resolved_sources[name]["resolvedRevision"])
        for name in FULL_DISTRIBUTION_SOURCE_NAMES
        if frozen[name] != resolved_sources[name]["resolvedRevision"]
    }
    if drift:
        detail = ", ".join(
            f"{name}: frozen {pinned} resolved {actual}" for name, (pinned, actual) in drift.items()
        )
        raise SourceIdentityError(f"--lock-sources-to-config drift detected: {detail}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    sources_config = None
    try:
        if args.sources_config.is_file():
            sources_config = load_frozen_source_manifest(args.sources_config)
        elif args.lock_sources_to_config or args.promotion:
            raise SourceIdentityError(
                f"promotion/locked builds require the frozen source manifest: {args.sources_config}"
            )
    except SourceIdentityError as exc:
        raise SystemExit(f"frozen source manifest unusable: {exc}") from exc

    requested, request_errors = resolve_requested_revisions(args, sources_config)
    if args.promotion and request_errors:
        raise SystemExit(
            "promotion build refused before loading any dataset:\n- "
            + "\n- ".join(request_errors)
        )

    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is required to resolve dataset revisions to immutable commits; "
            "run this builder inside the locked data-preparation environment"
        ) from exc

    api = HfApi()
    try:
        resolved_sources = resolve_full_distribution_sources(api, requested)
    except SourceIdentityError as exc:
        raise SystemExit(f"source resolution failed: {exc}") from exc

    # A locked build must land on exactly the frozen commits.
    if args.lock_sources_to_config and sources_config:
        try:
            assert_no_frozen_source_drift(sources_config, resolved_sources)
        except SourceIdentityError as exc:
            raise SystemExit(str(exc)) from exc

    overrides = protocol_overrides(sources_config) if sources_config else {}

    try:
        import datasets
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit("datasets is required to build the full classification lane") from exc

    rows_by_source, fingerprints = load_source_rows(load_dataset, resolved_sources)

    if sources_config:
        mismatches = []
        for name in FULL_DISTRIBUTION_SOURCE_NAMES:
            expected = sources_config["sources"][name].get("expectedValidationRows")
            if expected is not None and len(rows_by_source[name]) != int(expected):
                mismatches.append(
                    f"{name}: expected {expected} rows, loaded {len(rows_by_source[name])}"
                )
        if mismatches:
            raise SystemExit("validation row count mismatch:\n- " + "\n- ".join(mismatches))

    tasks, answers, counts, label_counts = build_lane(rows_by_source)

    provisional = manifest_source_table(resolved_sources)
    gate_errors, gate_warnings = source_manifest_gate_report(
        provisional, fingerprints, promotion=args.promotion, overrides=overrides
    )
    if args.promotion and gate_errors:
        raise SystemExit(
            "promotion build refused; source provenance gate failed:\n- "
            + "\n- ".join(gate_errors)
        )

    # Serialize task/answer first so the manifest can freeze their exact bytes.
    task_bytes = ("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n").encode("utf-8")
    answer_bytes = (json.dumps({"version": 3, "answers": answers}, indent=2) + "\n").encode("utf-8")
    TASK_FILE.write_bytes(task_bytes)
    ANSWER_FILE.write_bytes(answer_bytes)
    files = {
        TASK_FILE.name: {
            "sha256": hashlib.sha256(task_bytes).hexdigest(),
            "bytes": len(task_bytes),
            "cases": len(tasks),
        },
        ANSWER_FILE.name: {
            "sha256": hashlib.sha256(answer_bytes).hexdigest(),
            "bytes": len(answer_bytes),
        },
    }

    manifest = build_manifest(
        tasks=tasks,
        counts=counts,
        label_counts=label_counts,
        fingerprints=fingerprints,
        resolved_sources=resolved_sources,
        promotion=args.promotion,
        gate_errors=gate_errors,
        gate_warnings=gate_warnings,
        sources_config_path=args.sources_config,
        sources_config=sources_config,
        datasets_version=datasets.__version__,
        hub_version=_hub_version(),
        files=files,
    )
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "cases": len(tasks),
                "countsBySource": dict(counts),
                "promotionEligible": manifest["promotionEligible"],
                "datasetsVersion": datasets.__version__,
                "huggingfaceHubVersion": manifest["huggingfaceHubLibraryVersion"],
                "resolvedRevisions": {n: r["resolvedRevision"] for n, r in resolved_sources.items()},
                "gateErrors": gate_errors,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
