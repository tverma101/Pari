#!/usr/bin/env python3
"""Blind judging by Claude subagents in a Claude Code session (#87).

Use this when ``v2.claude_batch_judge`` cannot run, for example when the
``claude`` CLI has no API key or login of its own. The orchestrating session
gives each subagent a batch of task prompts; the subagent writes one answer
file per task. Nothing here calls a model.

    cd bench/word-studio
    python3 -m v2.subagent_judge prepare --judging v2/judging/<run-id> --work <dir>
    # each subagent: read <dir>/prompts/<task>.md, write <dir>/answers/<task>.json, then
    python3 -m v2.subagent_judge check --judging v2/judging/<run-id> --work <dir> --task <task>
    # orchestrator: record which agent judged which task in <dir>/agents.json, then
    python3 -m v2.subagent_judge collect --judging v2/judging/<run-id> --work <dir> --model claude-opus-5-5

``prepare`` writes each task's prompt, exactly as the CLI judge would send it,
into a work folder that holds no key, run metadata or raw output. ``collect``
validates every answer with the CLI judge's rules, copies the answers into the
judging folder, and writes ``scores.jsonl`` and ``judge-session-receipt.json``.
A subagent's model cannot be checked per call the way the CLI's ``modelUsage``
can, so the receipt records ``model_verified: false`` and how the model was
chosen. A missing or malformed answer stops ``collect``; no score is guessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from v2 import claude_batch_judge as cli_judge
from v2.aggregate import SUBAGENT_PREFIX, SUBAGENT_PROVIDER, SUPPORTED_JUDGE_EFFORT_LEVELS

RUBRIC = Path(__file__).with_name("RUBRIC.md")
ANSWER_FORMAT = {"scores": [{"label": "A", "relevance": {"1": 2, "2": 0}, "criteria": {
    c: 4 for c in cli_judge.CRITERIA}, "note": "option 2 is the wrong sense"}]}
BLINDNESS = ("Each subagent was told to read only its prompt files in the work folder, which hold the rubric, the "
             "anonymized packet and the required labels; the work folder has no key, run metadata or raw output. "
             "Subagent file tools were not technically restricted.")


def prepare(judging: Path, work: Path, batch_size: int) -> dict:
    _index, _template, _header, ids, groups = cli_judge.load_frozen(judging, RUBRIC)
    if (work / "prompts").exists():
        raise SystemExit(f"{work} already has prompts; use a new work folder")
    (work / "prompts").mkdir(parents=True)
    (work / "answers").mkdir()
    rubric_text = RUBRIC.read_text()
    for tid in ids:
        packet = (judging / "packets" / f"{tid}.md").read_text()
        (work / "prompts" / f"{tid}.md").write_text(cli_judge.build_prompt(packet, rubric_text, groups[tid]))
    batches = [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)]
    plan = {"judging": str(judging), "packet_index_sha256": cli_judge.sha(judging / "packets/index.json"),
            "answer_format": ANSWER_FORMAT, "batches": batches}
    (work / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return {"tasks": len(ids), "batches": len(batches), "work": str(work)}


def read_answer(work: Path, tid: str, rows: list[dict]) -> list[dict]:
    path = work / "answers" / f"{tid}.json"
    if not path.is_file():
        raise ValueError(f"no answer for {tid}")
    return cli_judge.validate(json.loads(path.read_text()), rows)


def collect(judging: Path, work: Path, model: str, effort: str, model_source: str) -> dict:
    index, _template, header, ids, groups = cli_judge.load_frozen(judging, RUBRIC)
    output = judging / "scores.jsonl"
    if output.exists():
        raise FileExistsError("Refusing to overwrite final judged evidence")
    agents = json.loads((work / "agents.json").read_text())
    if set(agents) != set(ids) or any(not isinstance(a, str) or not a for a in agents.values()):
        raise ValueError("agents.json must name the agent that judged every task")
    rows = {tid: read_answer(work, tid, groups[tid]) for tid in ids}
    saved = judging / "subagent-answers"
    saved.mkdir(exist_ok=True)
    answers_sha256 = {}
    for tid in ids:
        shutil.copyfile(work / "answers" / f"{tid}.json", saved / f"{tid}.json")
        answers_sha256[tid] = cli_judge.sha(saved / f"{tid}.json")
    sessions = {tid: agents[tid] for tid in ids}
    session_digest = hashlib.sha256(json.dumps(sessions, sort_keys=True).encode()).hexdigest()
    result = [dict(header, judge=SUBAGENT_PREFIX + model, session="batch:" + session_digest,
                   effort_level=effort, provider=SUBAGENT_PROVIDER)]
    result += [r for tid in ids for r in rows[tid]]
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in result))
    plan = json.loads((work / "plan.json").read_text())
    (judging / "judge-session-receipt.json").write_text(json.dumps({
        "schema_version": 1, "provider": SUBAGENT_PROVIDER, "model": model, "model_verified": False,
        "model_source": model_source, "effort_level": effort, "blindness": BLINDNESS,
        "batches": plan["batches"], "sessions": sessions, "answers_sha256": answers_sha256,
        "packet_index_sha256": cli_judge.sha(judging / "packets/index.json"),
        "scores_sha256": cli_judge.sha(output)}, indent=2) + "\n")
    return {"tasks": len(ids), "agents": len(set(agents.values())), "wrote_scores": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "check", "collect"):
        p = sub.add_parser(name)
        p.add_argument("--judging", type=Path, required=True)
        p.add_argument("--work", type=Path, required=True)
        if name == "prepare":
            p.add_argument("--batch-size", type=int, default=8)
        if name == "check":
            p.add_argument("--task", required=True)
        if name == "collect":
            p.add_argument("--model", required=True, help="the model the subagents ran on, as configured")
            p.add_argument("--effort", default="high", choices=sorted(SUPPORTED_JUDGE_EFFORT_LEVELS))
            p.add_argument("--model-source", default="Claude Code subagents inherited the session's configured "
                                                     "model; not verified per call")
    args = parser.parse_args(argv)
    judging, work = args.judging.resolve(), args.work.resolve()
    try:
        if args.command == "prepare":
            out = prepare(judging, work, args.batch_size)
        elif args.command == "check":
            groups = cli_judge.load_frozen(judging, RUBRIC)[4]
            if args.task not in groups:
                raise ValueError(f"unknown task {args.task}")
            out = {"task": args.task, "valid": len(read_answer(work, args.task, groups[args.task]))}
        else:
            out = collect(judging, work, args.model, args.effort, args.model_source)
    except (ValueError, KeyError, FileNotFoundError, FileExistsError, json.JSONDecodeError) as error:
        print(f"Fail closed; no scores were written or guessed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
