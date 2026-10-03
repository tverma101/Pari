#!/usr/bin/env python3
"""Criterion-specific paired analysis of blinded Word Studio ratings (issue #69).

Consumes only schema-validated rating documents (from
``validate-word-studio-human-eval-ratings.py``), the frozen preregistration and
the private A/B mapping. Ties and both-unacceptable stay first-class outcomes;
disagreement is reported, never adjudicated into one score; the blinded mapping
is revealed only in this final step, with its digest retained.

No ratings exist in this repository yet, so any analysis produced today would
describe synthetic fixtures only.
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
    ap.add_argument("--private-mapping", required=True, type=Path)
    ap.add_argument(
        "--ratings",
        action="append",
        required=True,
        type=Path,
        help="normalized rating document from the validator (repeatable)",
    )
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", default=None, help="defaults to the frozen preregistration seed")
    ap.add_argument(
        "--no-reveal",
        action="store_true",
        help="analyze blind; omit the final mapping reveal",
    )
    ap.add_argument("--bootstrap-resamples", type=int, default=2000)
    args = ap.parse_args()

    preregistration = json.loads(args.preregistration.read_text(encoding="utf-8"))
    private_mapping = json.loads(args.private_mapping.read_text(encoding="utf-8"))
    seed = args.seed or preregistration["randomization"]["seed"]
    validated = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.ratings]

    try:
        analysis = HE.analyze(
            preregistration,
            private_mapping,
            validated,
            seed=seed,
            reveal_mapping=not args.no_reveal,
            bootstrap_resamples=args.bootstrap_resamples,
        )
    except HE.HumanEvalContractError as exc:
        raise SystemExit(f"contract refusal: {exc}")

    if args.out:
        HE.atomic_write(Path(args.out), HE.document_bytes(analysis))
    print(json.dumps(analysis, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
