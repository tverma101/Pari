/**
 * Best-of-N selector: score every candidate with the eval gates and pick
 * the winner per case. Emits {"id","output"} JSONL for run-eval.mjs.
 *
 * Selection: passing candidates first; among them rank by
 *   sim + 0.01*clampedGrammarGain + 0.05*bandFitBonus,
 * ties broken toward lower temperature (determinism-friendly).
 * If nothing passes, fall back to the greedy (temp=0) candidate.
 */
import fs from "fs";
import path from "path";
import { scoreCase } from "../eval/metrics.mjs";

const ROOT = path.resolve(new URL("../..", import.meta.url).pathname);
const corpus = JSON.parse(fs.readFileSync(path.join(ROOT, "benchmarks/eval/corpus.json"), "utf8")).cases;
const byId = new Map(corpus.map((c) => [c.id, c]));

const inFile = process.argv[2];
const outFile = process.argv[3];

const rows = fs.readFileSync(inFile, "utf8").split("\n").filter(Boolean).map(JSON.parse);
const out = [];
let nPassFirst = 0;

for (const row of rows) {
  const cas = byId.get(row.id);
  const scored = [];
  for (const cand of row.candidates) {
    if (!cand.text.trim()) continue;
    const s = await scoreCase(cas, cand.text.trim());
    scored.push({ ...s, temp: cand.temp, text: cand.text.trim() });
  }
  const rank = (s) =>
    (s.passed ? 100 : 0) +
    s.metrics.cosineSim +
    0.01 * Math.max(0, Math.min(15, s.metrics.grammarGain)) +
    (s.metrics.editDistanceRatio >= 0.08 && s.metrics.editDistanceRatio <= 0.65 ? 0.05 : 0) -
    s.temp * 0.001;
  scored.sort((a, b) => rank(b) - rank(a));
  const winner = scored.find((s) => s.passed) ?? scored.find((s) => s.temp === 0) ?? scored[0];
  if (winner?.passed) nPassFirst += 1;
  out.push({ id: row.id, output: winner?.text ?? "", pickedTemp: winner?.temp });
}

fs.writeFileSync(outFile, out.map((r) => JSON.stringify(r)).join("\n"));
console.log(`selected ${out.length} winners; ${nPassFirst} cases have a gate-passing candidate -> ${outFile}`);
