"""Adding a model without re-judging the others: anchors, subagent judging, leaderboard."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v2 import aggregate, blind, leaderboard, run_candidate, subagent_judge
from v2.test_v2_judging import ScriptedBackend

LABELS = {"cand-a": {"1": 2, "2": 1, "3": 0}, "cand-b": {"1": 1, "3": 1, "4": 2},
          "cand-new": {"1": 2, "2": 2, "3": 1}}
BACKENDS = {"cand-a": ["alpha", "beta", "gamma"], "cand-b": ["alpha", "alpha", "delta", "epsilon"],
            "cand-new": ["omega", "sigma", "kappa"]}


def labels_for(key: dict, row: dict) -> dict:
    """What a consistent judge would answer. Only tests read the key to pick labels."""
    cid = key["tasks"][row["task_id"]][row["label"]]["candidate_id"]
    relevance = {k: LABELS[cid][k] for k in row["relevance"]}
    return {"label": row["label"], "relevance": relevance,
            "criteria": {c: 4 for c in blind.CRITERIA} if relevance else None,
            "note": "option 3 is off" if 0 in relevance.values() else ""}


def run_set(run_dir: Path, candidates: list[str]) -> None:
    for cid in candidates:
        candidate = {"candidate_id": cid, "model_id": f"fake/{cid}", "revision": "0" * 40}
        run_candidate.run(candidate, "screen", run_dir / cid, ScriptedBackend(BACKENDS[cid]), log=lambda _: None)


def judge_with_cli_receipt(judging: Path) -> None:
    key = json.loads((judging / "sealed" / "key.json").read_text(encoding="utf-8"))
    rows = aggregate.read_jsonl(judging / "scores.template.jsonl")
    index = json.loads((judging / "packets" / "index.json").read_text(encoding="utf-8"))
    sessions = {task_id: "cli-" + task_id for task_id in index["tasks"]}
    digest = hashlib.sha256(json.dumps(sessions, sort_keys=True).encode()).hexdigest()
    rows[0].update(judge="claude:claude-opus-5-5", session="batch:" + digest, effort_level="high")
    rows[1:] = [dict(row, **labels_for(key, row)) for row in rows[1:]]
    path = judging / "scores.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (judging / "claude-session-receipt.json").write_text(json.dumps({
        "model": "claude-opus-5-5", "effort_level": "high", "sessions": sessions,
        "packet_index_sha256": blind.sha256_file(judging / "packets" / "index.json"),
        "scores_sha256": blind.sha256_file(path)}), encoding="utf-8")


class IncrementalJudgingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        run_set(self.root / "runs" / "first", ["cand-a", "cand-b"])
        self.first = self.root / "judging" / "first"
        blind.build(self.root / "runs" / "first", self.first)
        judge_with_cli_receipt(self.first)
        run_set(self.root / "runs" / "new", ["cand-new"])
        self.new = self.root / "judging" / "new"
        self.index = blind.build(self.root / "runs" / "new", self.new, anchors_from=self.first, anchor_tasks=5)
        self.work = self.root / "work"

    def judge_with_subagents(self, tamper: bool = False) -> None:
        subagent_judge.prepare(self.new, self.work, batch_size=8)
        key = json.loads((self.new / "sealed" / "key.json").read_text(encoding="utf-8"))
        template = aggregate.read_jsonl(self.new / "scores.template.jsonl")[1:]
        for task_id in self.index["tasks"]:
            scores = [labels_for(key, row) for row in template if row["task_id"] == task_id]
            (self.work / "answers" / f"{task_id}.json").write_text(json.dumps({"scores": scores}), encoding="utf-8")
        plan = json.loads((self.work / "plan.json").read_text(encoding="utf-8"))
        agents = {t: f"agent-{n}" for n, batch in enumerate(plan["batches"]) for t in batch}
        (self.work / "agents.json").write_text(json.dumps(agents), encoding="utf-8")
        subagent_judge.collect(self.new, self.work, "claude-opus-5-5", "high", "inherited, not verified")
        if tamper:
            answer = self.new / "subagent-answers" / f"{self.index['tasks'][0]}.json"
            answer.write_text(answer.read_text(encoding="utf-8") + " ", encoding="utf-8")

    def test_anchors_are_blind_extra_outputs(self) -> None:
        self.assertEqual(len(self.index["anchor_tasks"]), 5)
        self.assertEqual(self.index["outputs_per_task"], 1)
        key = json.loads((self.new / "sealed" / "key.json").read_text(encoding="utf-8"))
        for task_id in self.index["tasks"]:
            entries = key["tasks"][task_id]
            self.assertEqual(len(entries), 1 + (task_id in self.index["anchor_tasks"]))
            anchors = [e for e in entries.values() if "anchor" in e]
            self.assertEqual(len(anchors), int(task_id in self.index["anchor_tasks"]))
            for e in anchors:
                self.assertIn(e["candidate_id"], {"cand-a", "cand-b"})
                self.assertEqual(e["anchor"]["task_id"], task_id)
        for packet in (self.new / "packets").glob("*.md"):
            text = packet.read_text(encoding="utf-8")
            for leak in ("cand-", "fake/", "anchor", "outputs/"):
                self.assertNotIn(leak, text)

    def test_subagent_prompts_hold_no_key_or_paths(self) -> None:
        subagent_judge.prepare(self.new, self.work, batch_size=8)
        prompts = list((self.work / "prompts").glob("*.md"))
        self.assertEqual(len(prompts), len(self.index["tasks"]))
        for prompt in prompts:
            text = prompt.read_text(encoding="utf-8")
            self.assertIn("RUBRIC:", text)
            self.assertIn("REQUIRED LABELS AND INDICES:", text)
            for leak in ("cand-", "fake/", "outputs/", "run.json"):
                self.assertNotIn(leak, text)
        with self.assertRaises(SystemExit):
            subagent_judge.prepare(self.new, self.work, batch_size=8)

    def test_subagent_scores_aggregate_and_anchors_agree(self) -> None:
        self.judge_with_subagents()
        result = aggregate.aggregate(self.new, self.new / "scores.jsonl")
        self.assertEqual(list(result["candidates"]), ["cand-new"], "anchors never count as candidates")
        self.assertEqual(result["judge"]["provider"], "claude-code-subagent")
        self.assertFalse(result["judge"]["model_verified"])
        anchors = result["anchor_agreement"]
        self.assertEqual((anchors["anchors"], anchors["label_agreement"], anchors["top3_shift_mean"]), (5, 1.0, 0.0))
        self.assertIn("Drift anchors", aggregate.markdown(result))

    def test_missing_answer_writes_nothing(self) -> None:
        subagent_judge.prepare(self.new, self.work, batch_size=8)
        (self.work / "agents.json").write_text(json.dumps({t: "a" for t in self.index["tasks"]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            subagent_judge.collect(self.new, self.work, "claude-opus-5-5", "high", "x")
        self.assertFalse((self.new / "scores.jsonl").exists())

    def test_changed_subagent_answer_is_refused(self) -> None:
        self.judge_with_subagents(tamper=True)
        with self.assertRaises(aggregate.VerificationError) as caught:
            aggregate.aggregate(self.new, self.new / "scores.jsonl")
        self.assertTrue(any("subagent answer" in p for p in caught.exception.problems))

    def test_leaderboard_pools_folders_and_flags_mixed_judges(self) -> None:
        self.judge_with_subagents()
        with self.assertRaises(aggregate.VerificationError) as caught:
            leaderboard.pool("screen", [self.first, self.new])
        self.assertTrue(any("different judges" in p for p in caught.exception.problems))
        result = leaderboard.pool("screen", [self.first, self.new], allow_mixed_judges=True)
        self.assertEqual(result["ranking"], ["cand-new", "cand-b", "cand-a"])
        self.assertTrue(result["mixed_judges"])
        self.assertEqual(result["candidates"]["cand-new"]["judged_in"], blind.rel(self.new))
        self.assertEqual(result["sources"][1]["anchor_agreement"]["label_agreement"], 1.0)
        self.assertIn("Mixed judges", leaderboard.markdown(result))

    def test_leaderboard_refuses_a_candidate_judged_twice(self) -> None:
        run_set(self.root / "runs" / "again", ["cand-a"])
        again = self.root / "judging" / "again"
        blind.build(self.root / "runs" / "again", again)
        judge_with_cli_receipt(again)
        with self.assertRaises(aggregate.VerificationError) as caught:
            leaderboard.pool("screen", [self.first, again])
        self.assertTrue(any("judged in both" in p for p in caught.exception.problems))


if __name__ == "__main__":
    unittest.main()
