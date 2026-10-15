#!/usr/bin/env python3
"""Freeze a blinded Word Studio human-evaluation packet set (issue #69).

Consumes only provenance-qualified artifacts: frozen task files, finalist
raw-output/result artifacts that already bind the exact task-file digest, the
canonical usable-candidate parser and the frozen human-evaluation protocol
document. Mixed task/parser/result identities are refused.

Writes:

- ``preregistration.json``      - frozen analysis/rubric/randomization policy
- ``packets/<raterId>.json``   - reviewer-visible blinded packets
- ``PRIVATE/human-eval.private-mapping.json`` - the A/B -> finalist mapping
- ``rating-schema.json``        - strict JSON Schema for rater submissions
- ``packet-manifest.json``     - digests for everything above

This script builds and freezes only. It does not rate, upload, send or score
anything. Actual product-quality ratings require human raters and have not been
collected.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import word_studio_human_eval as HE  # noqa: E402


def _parse_expected_hashes(values: list[str]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--expected-task-sha expects NAME=SHA256, got {value!r}")
        name, digest = value.split("=", 1)
        expected[name.strip()] = digest.strip()
    return expected


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--tasks",
        action="append",
        required=True,
        type=Path,
        help="frozen task file (repeatable)",
    )
    ap.add_argument(
        "--results",
        action="append",
        required=True,
        type=Path,
        help="qualified finalist raw-output artifact (repeatable, >= 2)",
    )
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument(
        "--private-mapping",
        type=Path,
        default=None,
        help="private A/B mapping path; defaults to <out-dir>/PRIVATE/human-eval.private-mapping.json",
    )
    ap.add_argument("--seed", required=True, help="frozen randomization seed")
    ap.add_argument("--evaluation-id", default="ws-human-eval")
    ap.add_argument("--depths", default="3,5,10", help="candidate-depth policy, comma separated")
    ap.add_argument(
        "--raters",
        default=",".join(HE.DEFAULT_RATERS),
        help="anonymous rater ids; no personally identifying information",
    )
    ap.add_argument(
        "--author-expectation-mode",
        default="not_used",
        choices=["not_used", "reviewer_checklist"],
        help=(
            "whether preregistered author requirements may appear as reviewer "
            "checklist text; they are never model input and never validated gold"
        ),
    )
    ap.add_argument(
        "--reviewer-checklist",
        type=Path,
        default=None,
        help="private review key JSON; only read when --author-expectation-mode=reviewer_checklist",
    )
    ap.add_argument("--parser", type=Path, default=HERE / "word_studio_output_parser.py")
    ap.add_argument("--protocol", type=Path, default=HERE / HE.PROTOCOL_RELATIVE_PATH)
    ap.add_argument("--expected-task-sha", action="append", default=[])
    args = ap.parse_args()

    try:
        depths = tuple(int(x) for x in args.depths.split(",") if x.strip())
    except ValueError:
        raise SystemExit(f"--depths must be comma-separated integers, got {args.depths!r}")
    if not depths or any(value < 1 for value in depths):
        raise SystemExit("--depths must be positive integers")
    raters = tuple(x.strip() for x in args.raters.split(",") if x.strip())
    if not raters:
        raise SystemExit("--raters must name at least one anonymous rater id")

    checklist: dict[str, list[str]] = {}
    if args.author_expectation_mode == "reviewer_checklist":
        if not args.reviewer_checklist:
            raise SystemExit(
                "--author-expectation-mode=reviewer_checklist requires --reviewer-checklist"
            )
        key = json.loads(Path(args.reviewer_checklist).read_text(encoding="utf-8"))
        items = key.get("items") if isinstance(key, dict) else key
        if not isinstance(items, list):
            raise SystemExit(f"{args.reviewer_checklist}: expected an items array")
        for entry in items:
            task_id = entry.get("id")
            if not task_id:
                continue
            for field in ("expectations", "requirements"):
                values = entry.get(field)
                if isinstance(values, list):
                    checklist.setdefault(str(task_id), []).extend(
                        str(value) for value in values if str(value).strip()
                    )

    try:
        inputs = HE.load_inputs(
            task_files=args.tasks,
            result_files=args.results,
            parser_path=args.parser,
            protocol_path=args.protocol,
            expected_task_hashes=_parse_expected_hashes(args.expected_task_sha),
        )
        comparisons = HE.build_comparisons(inputs)
        preregistration = HE.build_preregistration(
            inputs,
            comparisons,
            seed=args.seed,
            depths=depths,
            rater_ids=raters,
            author_expectation_mode=args.author_expectation_mode,
            evaluation_id=args.evaluation_id,
        )
        built = HE.build_packets(
            inputs,
            comparisons,
            preregistration,
            depth=max(depths),
            reviewer_checklist=checklist or None,
        )
    except HE.HumanEvalContractError as exc:
        raise SystemExit(f"contract refusal: {exc}")

    out_dir = Path(args.out_dir)
    packet_dir = out_dir / "packets"
    mapping_path = Path(args.private_mapping) if args.private_mapping else (
        out_dir / "PRIVATE" / "human-eval.private-mapping.json"
    )
    if mapping_path.resolve().is_relative_to(packet_dir.resolve()):
        raise SystemExit(
            "--private-mapping must not live inside the reviewer packet directory; "
            "the A/B -> finalist mapping would ship with the packets"
        )

    for rater_id, packet in sorted(built["packets"].items()):
        HE.atomic_write(packet_dir / f"{rater_id}.json", HE.document_bytes(packet))
    HE.atomic_write(mapping_path, HE.document_bytes(built["privateMapping"]))
    HE.atomic_write(out_dir / "preregistration.json", HE.document_bytes(preregistration))
    HE.atomic_write(out_dir / "rating-schema.json", HE.document_bytes(HE.rating_schema()))

    manifest = {
        "schemaVersion": 1,
        "evaluationId": args.evaluation_id,
        "preregistrationSha256": preregistration["preregistrationSha256"],
        "rubricSha256": preregistration["protocol"]["rubricSha256"],
        "protocolSha256": preregistration["protocol"]["sha256"],
        "parserSha256": preregistration["usableCandidateContract"]["sha256"],
        "randomizationSeed": args.seed,
        "finalistCount": preregistration["finalistCount"],
        "taskFileSha256": sorted(
            artifact["taskFileSha256"] for artifact in preregistration["taskArtifacts"]
        ),
        "resultArtifactSha256": sorted(
            artifact["resultSha256"] for artifact in preregistration["resultArtifacts"]
        ),
        "packets": [
            {
                "raterId": rater_id,
                "packetSha256": packet["packetSha256"],
                "pairCount": sum(1 for i in packet["items"] if i["kind"] == "pair_comparison"),
                "strengthGroupCount": sum(
                    1 for i in packet["items"] if i["kind"] == "strength_trajectory"
                ),
            }
            for rater_id, packet in sorted(built["packets"].items())
        ],
        "privateMapping": {
            "path": str(mapping_path),
            "mappingSha256": built["privateMapping"]["mappingSha256"],
            "visibility": "PRIVATE - do not ship with reviewer packets",
        },
        "ratingSchemaSha256": HE.sha256_object(HE.rating_schema()),
        "evidenceStatus": preregistration["evidenceStatus"],
        "nextAction": (
            "independent human raters submit schema-validated rating documents; "
            "no ratings exist yet"
        ),
    }
    HE.atomic_write(out_dir / "packet-manifest.json", HE.document_bytes(manifest))

    print(
        json.dumps(
            {
                "outDir": str(out_dir),
                "preregistrationSha256": preregistration["preregistrationSha256"],
                "privateMappingSha256": built["privateMapping"]["mappingSha256"],
                "packets": [entry["raterId"] for entry in manifest["packets"]],
                "comparisons": len(comparisons),
                "evidenceStatus": preregistration["evidenceStatus"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
