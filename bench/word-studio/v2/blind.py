#!/usr/bin/env python3
"""Turn a fetched run into blind judging packets and a sealed key (#87).

    cd bench/word-studio
    python3 -m v2.blind --run v2/runs/<run-id>

Writes ``v2/judging/<run-id>/``:

- ``packets/<task-id>.md``: what the judge reads. Each candidate's options
  appear under a letter that is shuffled for every task, with an opaque output
  ref and the sha256 of the raw output file. No model names or paths.
- ``packets/index.json``: the task list, the rubric hash, and the key's sha256,
  so the key cannot be swapped after judging.
- ``scores.template.jsonl``: one row per task and letter for the judge to fill
  in and save as ``scores.jsonl`` (format in ``v2/RUBRIC.md``).
- ``sealed/key.json``: letter -> candidate and raw file. The judge does not open
  it; ``v2.aggregate`` does.

Only candidates whose run completed are judged. Failed runs are listed in the
key as not judged, with their error.

Every completed run's output filenames must match its recorded task limit and
completion metadata. The default selection judges the same recorded task set
for every candidate; an explicit subset is marked in the frozen index.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WORD_STUDIO = HERE.parent
REPO_ROOT = WORD_STUDIO.parents[1]
RUBRIC = HERE / "RUBRIC.md"
CRITERIA = ("fit", "meaning", "register", "variety", "usefulness")

if str(WORD_STUDIO) not in sys.path:
    sys.path.insert(0, str(WORD_STUDIO))

from v2 import build_tasks, hard_checks  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    """Repository-relative path, so the key still resolves on another machine."""
    path = path.resolve()
    return path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_runs(run_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Completed candidate runs, and the ones that will not be judged."""
    judged, skipped = [], []
    for run_json in sorted(run_dir.glob("*/run.json")):
        run = json.loads(run_json.read_text(encoding="utf-8"))
        cid = (run.get("candidate") or {}).get("candidate_id") or run_json.parent.name
        entry = {"candidate_id": cid, "dir": run_json.parent, "run": run, "run_sha256": sha256_file(run_json)}
        if run.get("status") == "completed":
            judged.append(entry)
        else:
            skipped.append({"candidate_id": cid, "status": run.get("status"), "stage": run.get("stage"),
                            "error": run.get("error"), "run_json": rel(run_json),
                            "run_sha256": entry["run_sha256"]})
    return judged, skipped


def recorded_tasks(entry: dict[str, Any], task_order: list[str]) -> list[str]:
    """Validate a completed run's exact output set against its run receipt."""
    run = entry["run"]
    candidate_id = entry["candidate_id"]
    limit = run.get("task_limit")
    if run.get("complete_set") is True and limit is None:
        expected = task_order
    elif (run.get("complete_set") is False and type(limit) is int
          and 1 <= limit <= len(task_order)):
        expected = task_order[:limit]
    else:
        raise SystemExit(f"{candidate_id}: cannot verify task outputs from complete_set/task_limit metadata")

    planned = run.get("tasks_planned")
    counts = run.get("tasks")
    if type(planned) is not int or planned != len(expected):
        raise SystemExit(f"{candidate_id}: tasks_planned does not match its recorded task set")
    if (not isinstance(counts, dict) or type(counts.get("ok")) is not int
            or counts["ok"] != len(expected) or type(counts.get("error")) is not int
            or counts["error"] != 0):
        raise SystemExit(f"{candidate_id}: completed task counts do not match its recorded task set")

    output_dir = entry["dir"] / "outputs"
    found = {path.stem for path in output_dir.glob("*.json")}
    missing, extra = sorted(set(expected) - found), sorted(found - set(expected))
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing outputs: {missing}")
        if extra:
            details.append(f"unexpected outputs: {extra}")
        raise SystemExit(f"{candidate_id}: output files do not match run metadata ({'; '.join(details)})")
    return expected


def instruction_of(task: dict[str, Any]) -> str:
    return task["messages"][1]["content"].rsplit("\n\n", 1)[-1]


def render_packet(task: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    lines = [f"# {task['id']}", "", f"Kind: `{task['kind']}`, asks for {task['requested_options']} options.", ""]
    lines += ["Paragraph:", "", "> " + task["paragraph"], ""]
    if task.get("sentence"):
        selection = task["selection"]
        sentence = task["sentence"]
        if task["kind"] in {"tap_word", "phrase_to_word"}:
            start = selection["start"] - task["paragraph"].index(sentence)
            sentence = sentence[:start] + "[[" + selection["text"] + "]]" + sentence[start + len(selection["text"]):]
        lines += [f"Selected: {sentence}", ""]
    if task.get("word"):
        lines += [f"Word: **{task['word']}** ({task['word_origin']})", ""]
    lines += ["Instruction given to every model:", "", "> " + instruction_of(task), ""]
    for entry in entries:
        checked = entry["checked"]
        lines += [f"## Output {entry['label']}", "",
                  f"ref `{entry['output_ref']}`, raw sha256 `{entry['output_sha256']}`", "",
                  f"Format: {checked['format']} ({checked['parse_mode']}), {checked['returned']} options"
                  + (", hit the token limit" if checked["truncated"] else ""), ""]
        if not checked["options"]:
            lines += ["No options to judge.", ""]
        for option in checked["options"]:
            text = option["text"].replace("\n", " ")
            note = ""
            if option["fail"]:
                note = f"  — not judged, counts as 0 (fail: {', '.join(option['fail'])})"
            elif option["warn"]:
                note = f"  — check: {', '.join(option['warn'])}"
            lines.append(f"{option['index'] + 1}. {text}{note}")
        lines.append("")
    return "\n".join(lines)


def template_row(task_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    judged = [o["index"] + 1 for o in entry["checked"]["options"] if o["judge"]]
    return {
        "task_id": task_id,
        "label": entry["label"],
        "output_ref": entry["output_ref"],
        "output_sha256": entry["output_sha256"],
        "criteria": {c: None for c in CRITERIA} if judged else None,
        "relevance": {str(i): None for i in judged},
        "note": "",
    }


def load_anchor_pool(anchors_from: Path, set_name: str, task_sha: str, exclude: set[str]) -> dict[str, list[dict]]:
    """Already-judged outputs another judging folder can lend as anchors, by task.

    An anchor is an output whose score already exists. Judging it again among
    new outputs measures judge drift, so a new candidate can be judged alone and
    compared with candidates judged earlier (``v2.leaderboard``).
    """
    key_path = anchors_from / "sealed" / "key.json"
    index = json.loads((anchors_from / "packets" / "index.json").read_text(encoding="utf-8"))
    if sha256_file(key_path) != index["key_sha256"] or not (anchors_from / "scores.jsonl").is_file():
        raise SystemExit(f"{anchors_from} is not a sealed, judged folder")
    if index["task_set"] != set_name:
        raise SystemExit(f"anchors come from the {index['task_set']} set, this run is {set_name}")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    pool: dict[str, list[dict]] = {}
    for task_id, labels in key["tasks"].items():
        for label, sealed in sorted(labels.items()):
            if sealed["candidate_id"] in exclude or sealed.get("anchor"):
                continue
            run = json.loads((REPO_ROOT / key["candidates"][sealed["candidate_id"]]["run_json"]).read_text(
                encoding="utf-8"))
            if run["task_file_sha256"] != task_sha:
                raise SystemExit(f"{anchors_from} judged a different {set_name} task file")
            path = REPO_ROOT / sealed["raw_output"]
            if sha256_file(path) != sealed["output_sha256"]:
                raise SystemExit(f"anchor {sealed['raw_output']} changed after it was judged")
            pool.setdefault(task_id, []).append({"path": path, "candidate_id": sealed["candidate_id"],
                                                  "anchor": {"judging": rel(anchors_from), "task_id": task_id,
                                                             "label": label}})
    return pool


def build(run_dir: Path, out_dir: Path, *, task_ids: list[str] | None = None,
          anchors_from: Path | None = None, anchor_tasks: int = 0) -> dict[str, Any]:
    if (out_dir / "sealed" / "key.json").exists():
        raise SystemExit(f"{out_dir} already has a key; never overwrite judging evidence")
    judged, skipped = load_runs(run_dir)
    if not judged:
        raise SystemExit(f"no completed candidate runs in {run_dir}")
    sets = {(e["run"]["task_set"], e["run"]["task_file_sha256"], e["run"]["prompt_version"]) for e in judged}
    if len(sets) != 1:
        raise SystemExit(f"candidates ran different task sets or prompts: {sorted(sets)}")
    set_name, task_sha, _prompt = sets.pop()
    manifest = json.loads(build_tasks.MANIFEST.read_text(encoding="utf-8"))
    if manifest["sets"][set_name]["sha256"] != task_sha:
        raise SystemExit(f"the runs used a different {set_name} task file than v2/tasks has now; "
                         "judge them from the commit they ran at")
    task_records = build_tasks.load_tasks(set_name)
    task_order = [t["id"] for t in task_records]
    tasks = {t["id"]: t for t in task_records}
    candidate_task_sets = [recorded_tasks(e, task_order) for e in judged]
    if any(ids != candidate_task_sets[0] for ids in candidate_task_sets[1:]):
        raise SystemExit("completed candidates recorded different task subsets; refusing to intersect them")
    available = set(candidate_task_sets[0])
    if task_ids is None:
        chosen = candidate_task_sets[0]
    else:
        if len(task_ids) != len(set(task_ids)):
            raise SystemExit("explicit task list contains duplicate IDs")
        unknown = [task_id for task_id in task_ids if task_id not in tasks]
        if unknown:
            raise SystemExit(f"unknown task IDs: {unknown}")
        chosen = task_ids
    missing = [t for t in chosen if t not in available]
    if missing:
        raise SystemExit(f"tasks without an output from every judged candidate: {missing}")
    secret = secrets.token_hex(16)
    anchors: dict[str, dict] = {}
    if anchor_tasks:
        if anchors_from is None:
            raise SystemExit("--anchor-tasks needs --anchors-from")
        pool = load_anchor_pool(anchors_from, set_name, task_sha, {e["candidate_id"] for e in judged})
        eligible = [t for t in chosen if pool.get(t)]
        if len(eligible) < anchor_tasks:
            raise SystemExit(f"only {len(eligible)} tasks have an anchor in {anchors_from}")
        rng = random.Random(int(digest(secret, "anchors")[:16], 16))
        anchors = {t: rng.choice(pool[t]) for t in sorted(rng.sample(eligible, anchor_tasks), key=chosen.index)}
    key: dict[str, Any] = {
        "run_dir": rel(run_dir),
        "task_set": set_name,
        "secret": secret,
        "candidates": {e["candidate_id"]: {"run_json": rel(e["dir"] / "run.json"), "run_sha256": e["run_sha256"],
                                           "complete_set": e["run"].get("complete_set")} for e in judged},
        "not_judged": skipped,
        "tasks": {},
    }
    template: list[dict[str, Any]] = []
    for task_id in chosen:
        task = tasks[task_id]
        order = [{"path": e["dir"] / "outputs" / f"{task_id}.json", "candidate_id": e["candidate_id"]}
                 for e in judged] + ([anchors[task_id]] if task_id in anchors else [])
        random.Random(int(digest(secret, task_id)[:16], 16)).shuffle(order)
        entries = []
        for label, e in zip(string.ascii_uppercase, order):
            path = e["path"]
            output = json.loads(path.read_text(encoding="utf-8"))
            ref_parts = [e["candidate_id"], task_id] + (["anchor"] if "anchor" in e else [])
            entries.append({
                "label": label,
                "candidate_id": e["candidate_id"],
                "output_ref": "o-" + digest(secret, *ref_parts)[:12],
                "output_sha256": sha256_file(path),
                "raw_output": rel(path),
                "checked": hard_checks.check(task, output),
                **({"anchor": e["anchor"]} if "anchor" in e else {}),
            })
        (out_dir / "packets").mkdir(parents=True, exist_ok=True)
        (out_dir / "packets" / f"{task_id}.md").write_text(render_packet(task, entries), encoding="utf-8")
        key["tasks"][task_id] = {e["label"]: {k: e[k] for k in ("candidate_id", "output_ref", "output_sha256",
                                                                  "raw_output", "anchor") if k in e}
                                 for e in entries}
        template += [template_row(task_id, e) for e in entries]
    write_json(out_dir / "sealed" / "key.json", key)
    packet_hashes = {
        task_id: sha256_file(out_dir / "packets" / f"{task_id}.md")
        for task_id in chosen
    }
    index = {
        "run_id": run_dir.name,
        "task_set": set_name,
        "task_selection": "recorded_run_tasks" if task_ids is None else "explicit_task_ids",
        "task_set_complete": set(chosen) == set(task_order),
        "tasks": chosen,
        "packet_hashes": packet_hashes,
        "outputs_per_task": len(judged),
        # Tasks that carry one extra, already-judged output (a drift anchor).
        "anchor_tasks": list(anchors),
        "anchors_from": rel(anchors_from) if anchors else None,
        "checks_version": hard_checks.CHECKS_VERSION,
        "rubric_sha256": sha256_file(RUBRIC),
        "key_sha256": sha256_file(out_dir / "sealed" / "key.json"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "judge_reads": "RUBRIC.md, packets/*.md, and scores.template.jsonl only; candidate/run metadata, raw outputs, and sealed/key.json stay closed until scores.jsonl is final",
    }
    index_path = out_dir / "packets" / "index.json"
    write_json(index_path, index)
    header = {"header": True, "judge": None, "session": None, "blind": True,
              "rubric_sha256": index["rubric_sha256"], "key_sha256": index["key_sha256"],
              "packets_index_sha256": sha256_file(index_path)}
    with (out_dir / "scores.template.jsonl").open("w", encoding="utf-8") as fh:
        for row in [header, *template]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True, help="v2/runs/<run-id>")
    parser.add_argument("--out", type=Path, help="default: v2/judging/<run-id>")
    parser.add_argument("--tasks", help="comma-separated explicit task subset (default: the identical task set recorded by every completed candidate run)")
    parser.add_argument("--anchors-from", type=Path,
                        help="a judged v2/judging/<run-id> on the same set whose outputs are mixed in as drift anchors")
    parser.add_argument("--anchor-tasks", type=int, default=0,
                        help="how many tasks get one anchor output (default 0)")
    args = parser.parse_args(argv)
    run_dir = args.run.resolve()
    out_dir = (args.out or HERE / "judging" / run_dir.name).resolve()
    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
    index = build(run_dir, out_dir, task_ids=task_ids,
                  anchors_from=args.anchors_from.resolve() if args.anchors_from else None,
                  anchor_tasks=args.anchor_tasks)
    print(json.dumps({"out": rel(out_dir), "tasks": len(index["tasks"]),
                      "outputs_per_task": index["outputs_per_task"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
