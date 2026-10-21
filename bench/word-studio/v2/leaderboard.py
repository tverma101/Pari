#!/usr/bin/env python3
"""Rank every judged candidate on one task set, across judging folders.

    cd bench/word-studio
    python3 -m v2.leaderboard --set screen
    python3 -m v2.leaderboard --set full --judging v2/judging/<a> v2/judging/<b>

This is how a new model joins without re-judging the others. Run only the new
model on Kaggle, build its packets with drift anchors (``v2.blind
--anchors-from <an earlier judging> --anchor-tasks 10``), judge them, and pool
them here with the earlier judgings.

Pooling is allowed because the rubric gives absolute labels per option, not a
ranking inside a packet. It still assumes the judge behaves the same in every
folder, so each folder's anchor agreement is reported, and folders judged by
different judges are pooled only with ``--allow-mixed-judges``.

Every folder is fully verified by ``v2.aggregate.verify`` (raw-output hashes,
code checks, citations). All folders must share the task set, rubric and code
checks, and every candidate must have judged outputs for the whole set. A
candidate judged in two folders stops the run; pass ``--judging`` to choose.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2 import aggregate, blind, build_tasks

HERE = Path(__file__).resolve().parent


def judged_folders(task_set: str) -> list[Path]:
    folders = []
    for index_path in sorted((HERE / "judging").glob("*/packets/index.json")):
        folder = index_path.parents[1]
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if index["task_set"] == task_set and (folder / "scores.jsonl").is_file():
            folders.append(folder)
    return folders


def pool(task_set: str, folders: list[Path], allow_mixed_judges: bool = False) -> dict[str, Any]:
    if not folders:
        raise aggregate.VerificationError([f"no judged folders for the {task_set} set"])
    all_tasks = build_tasks.load_tasks(task_set)
    task_ids = {task["id"] for task in all_tasks}
    cluster_of = {task["id"]: task["paragraph_id"] for task in all_tasks}
    problems: list[str] = []
    sources, candidates, per_task, judged_in = [], {}, {}, {}
    rubrics, judges = set(), set()
    for folder in folders:
        index, key, verified, receipt, receipt_path = aggregate.verify(folder, folder / "scores.jsonl")
        header = aggregate.read_jsonl(folder / "scores.jsonl")[0]
        if index["task_set"] != task_set:
            problems.append(f"{blind.rel(folder)} judged the {index['task_set']} set")
            continue
        rubrics.add(index["rubric_sha256"])
        judge = {"judge": header["judge"], "effort_level": header.get("effort_level"),
                 "provider": receipt.get("provider"),
                 "model_verified": receipt.get("model_verified", receipt.get("provider") == "claude-code")}
        judges.add((judge["judge"], judge["effort_level"]))
        source = {"judging": blind.rel(folder), "run_id": index["run_id"], **judge,
                  "scores_sha256": blind.sha256_file(folder / "scores.jsonl"),
                  "judge_receipt_sha256": blind.sha256_file(receipt_path),
                  "anchor_agreement": aggregate.anchor_agreement(verified), "candidates": []}
        for cid, items in sorted(aggregate.by_candidate(verified).items()):
            if cid in judged_in:
                problems.append(f"{cid} is judged in both {judged_in[cid]} and {source['judging']}; "
                                "pass --judging to choose one")
                continue
            missing = task_ids - {item["row"]["task_id"] for item in items}
            if missing:
                problems.append(f"{cid} in {source['judging']} misses {len(missing)} {task_set} tasks")
                continue
            judged_in[cid] = source["judging"]
            candidates[cid] = aggregate.candidate_result(items, key["candidates"][cid])
            candidates[cid]["judged_in"] = source["judging"]
            per_task[cid] = {item["row"]["task_id"]: aggregate.top3_share(item) for item in items}
            source["candidates"].append(cid)
        sources.append(source)
    if len(rubrics) > 1:
        problems.append("the folders were judged under different rubrics")
    if len(judges) > 1 and not allow_mixed_judges:
        problems.append(f"the folders have different judges {sorted(judges)}; "
                        "check their anchor agreement, then pass --allow-mixed-judges")
    if problems:
        raise aggregate.VerificationError(problems)
    ranking = aggregate.rank(candidates)
    return {
        "benchmark": "word-studio-v2",
        "view": "leaderboard",
        "task_set": task_set,
        "tasks": len(task_ids),
        "mixed_judges": len(judges) > 1,
        "sources": sources,
        "ranking": ranking,
        "ranking_rule": "top3_at_bar, then usable_per_task (v2/RUBRIC.md)",
        "uncertainty": aggregate.uncertainty(per_task, ranking, cluster_of),
        "candidates": candidates,
        "pooled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [f"# Word Studio v2 leaderboard: {result['task_set']} set", "",
             f"{len(result['ranking'])} candidates on the {result['tasks']}-task {result['task_set']} set, pooled "
             f"from {len(result['sources'])} blind judging folder(s). Ranked by {result['ranking_rule']}. "
             "Latency is Kaggle T4, Transformers fp16, not the Mac.", "",
             "| Candidate | Top-3 at bar | 95% CI | Gap to leader (95% CI) | Usable / task | Strict JSON | "
             "First option p50 | Judged in |",
             "|---|---|---|---|---|---|---|---|"]
    spread = result["uncertainty"]
    pct = lambda pair: "—" if pair is None else f"{pair[0]:.1%} to {pair[1]:.1%}"  # noqa: E731
    for cid in result["ranking"]:
        m = result["candidates"][cid]
        gap = spread["gap_to_leader"].get(cid)
        gap_text = "leader" if gap is None else (
            f"{gap['mean']:+.1%} ({pct(gap['ci95'])}){'' if gap['separable'] else ', not separable'}")
        first = m["latency_t4"]["first_option"]["median_ms"]
        lines.append(f"| {cid} | {m['top3_at_bar']:.1%} | {pct(spread['candidates'][cid]['ci95'])} | {gap_text} | "
                     f"{m['usable_per_task']} | {m['formats'].get('strict', 0)}/{m['tasks']} | "
                     f"{'—' if first is None else f'{first / 1000:.1f} s'} | `{Path(m['judged_in']).name}` |")
    lines += ["", "| Judging folder | Judge | Effort | Model verified per call | Anchor agreement |",
              "|---|---|---|---|---|"]
    for source in result["sources"]:
        anchors = source["anchor_agreement"]
        agreement = "no anchors" if not anchors else (
            f"{anchors['anchors']} anchors: same label {anchors['label_agreement']:.1%}, "
            f"same side of the bar {anchors['bar_agreement']:.1%}, top-3 shift {anchors['top3_shift_mean']:+.1%}")
        lines.append(f"| `{source['judging']}` | {source['judge']} | {source['effort_level']} | "
                     f"{'yes' if source['model_verified'] else 'no'} | {agreement} |")
    if result["mixed_judges"]:
        lines += ["", "**Mixed judges.** The folders were judged by different judge setups. Gaps between "
                  "candidates from different folders also include any judge difference; see the anchor agreement."]
    lines += ["", f"Intervals: {spread['method']}.", "",
              "Every number traces to `leaderboard.json` and, through it, to each folder's verified scores and raw "
              "outputs.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=["screen", "full"], required=True)
    parser.add_argument("--judging", type=Path, nargs="+", help="default: every judged folder for --set")
    parser.add_argument("--allow-mixed-judges", action="store_true")
    parser.add_argument("--out", type=Path, help="default: v2/results/leaderboard-<set>-<UTC time>")
    args = parser.parse_args(argv)
    folders = [f.resolve() for f in args.judging] if args.judging else judged_folders(args.set)
    try:
        result = pool(args.set, folders, args.allow_mixed_judges)
    except aggregate.VerificationError as exc:
        print("leaderboard not written:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    out = (args.out or HERE / "results" / f"leaderboard-{args.set}-{stamp}").resolve()
    if (out / "leaderboard.json").exists():
        raise SystemExit(f"{out} already has a leaderboard; never overwrite evidence")
    out.mkdir(parents=True, exist_ok=True)
    (out / "leaderboard.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "leaderboard.md").write_text(markdown(result), encoding="utf-8")
    print(markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
