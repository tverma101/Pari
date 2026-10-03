#!/usr/bin/env python3
"""Validate blinded human-evaluation rating documents (issue #69).

Each rater submission is checked against that rater's own frozen packet and the
frozen preregistration. Rejected: unknown item/candidate IDs, duplicate
rater/pair/criterion rows, outdated packet digests, impossible labels, missing
required criteria, and any exposure of the private A/B mapping inside reviewer
data.

Prints normalized rating documents to ``--out-dir`` when every submission is
valid; exits non-zero and prints every error when any submission is not.
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preregistration", required=True, type=Path)
    ap.add_argument("--private-mapping", type=Path, default=None)
    ap.add_argument("--packets", required=True, type=Path, help="directory of per-rater packets")
    ap.add_argument("--ratings", action="append", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    preregistration = json.loads(args.preregistration.read_text(encoding="utf-8"))
    private_mapping = (
        json.loads(args.private_mapping.read_text(encoding="utf-8"))
        if args.private_mapping
        else None
    )

    packets: dict[str, dict] = {}
    for path in sorted(Path(args.packets).glob("*.json")):
        packet = json.loads(path.read_text(encoding="utf-8"))
        packets[str(packet["raterId"])] = packet
    if not packets:
        raise SystemExit(f"no packets found under {args.packets}")

    failed = False
    normalized: list[dict] = []
    for path in args.ratings:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        packet = packets.get(str(document.get("raterId")))
        if packet is None:
            print(
                f"FAIL {path.name}: raterId {document.get('raterId')!r} has no frozen packet",
                file=sys.stderr,
            )
            failed = True
            continue
        report = HE.validate_rating_document(
            document,
            packet=packet,
            preregistration=preregistration,
            private_mapping=private_mapping,
        )
        if not report.ok:
            failed = True
            print(f"FAIL {path.name}", file=sys.stderr)
            for error in report.errors:
                print(f"  - {error}", file=sys.stderr)
            continue
        for warning in report.warnings:
            print(f"WARN {path.name}: {warning}", file=sys.stderr)
        print(f"OK   {path.name} rater={document['raterId']} rows={len(report.normalized['pairRatings'])}")
        normalized.append(report.normalized)

    if failed:
        raise SystemExit("one or more rating documents failed validation")

    if args.out_dir:
        for entry in normalized:
            HE.atomic_write(
                Path(args.out_dir) / f"{entry['raterId']}.ratings.normalized.json",
                HE.document_bytes(entry),
            )
    print(json.dumps({"validated": len(normalized), "raterIds": sorted(e["raterId"] for e in normalized)}, indent=2))


if __name__ == "__main__":
    main()
