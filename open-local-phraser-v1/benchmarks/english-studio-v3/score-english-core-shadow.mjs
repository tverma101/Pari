#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(fs.readFileSync(path.join(here, "english-core-config.json"), "utf8"));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const resultPath = process.argv[2];

if (!resultPath) {
  console.error("Usage: node score-english-core-shadow.mjs <results.jsonl>");
  process.exit(2);
}

const results = new Map(
  fs.readFileSync(resultPath, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .map((row) => [row.id, row]),
);

const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

function goldIndex(row) {
  switch (row.task) {
    case "same_sense": return ["same", "different"].indexOf(row.answer);
    case "best_substitute": return row.choices.indexOf(row.answer);
    case "minimal_pair": return row.choices.indexOf(row.answer);
    case "acceptability_pair": return letters.indexOf(row.answer);
    case "same_meaning": return ["same", "different"].indexOf(row.answer);
    case "closer_register":
    case "closer_meaning_and_register":
    case "more_natural": return row.answer;
    case "relation_preservation": return ["preserved", "changed"].indexOf(row.answer);
    case "relation_label": return row.choices.indexOf(row.answer);
    case "sentence_order": return row.choices.findIndex((x) => JSON.stringify(x) === JSON.stringify(row.answer));
    default: return null;
  }
}

function predictedIndex(output) {
  if (output == null) return null;
  const text = String(output).trim().toUpperCase();
  const match = text.match(/^([A-Z])/);
  return match ? letters.indexOf(match[1]) : null;
}

const stats = {};
for (const name of Object.keys(config.dimensions)) {
  stats[name] = { correct: 0, answered: 0, objectiveCases: 0, generativeScores: [] };
}

const misses = [];
for (const row of seed.cases) {
  const result = results.get(row.id);
  if (row.dimension === "generative_expression") {
    if (result && Number.isFinite(result.score_0_100)) {
      const score = Math.max(0, Math.min(100, Number(result.score_0_100)));
      stats[row.dimension].generativeScores.push(score);
    }
    continue;
  }

  const gold = goldIndex(row);
  if (gold == null || gold < 0) throw new Error(`No objective gold mapping for ${row.id}`);
  stats[row.dimension].objectiveCases += 1;
  if (!result) {
    misses.push({ id: row.id, reason: "missing_result" });
    continue;
  }
  const predicted = predictedIndex(result.output ?? result.answer);
  if (predicted == null) {
    misses.push({ id: row.id, reason: "unparseable_output", output: result.output ?? result.answer });
    continue;
  }
  stats[row.dimension].answered += 1;
  if (predicted === gold) stats[row.dimension].correct += 1;
  else misses.push({ id: row.id, reason: "wrong", predicted: letters[predicted], gold: letters[gold] });
}

const dimensionScores = {};
for (const [dimension, stat] of Object.entries(stats)) {
  if (dimension === "generative_expression") {
    dimensionScores[dimension] = stat.generativeScores.length
      ? stat.generativeScores.reduce((a, b) => a + b, 0) / stat.generativeScores.length
      : null;
  } else {
    dimensionScores[dimension] = stat.objectiveCases
      ? (100 * stat.correct) / stat.objectiveCases
      : null;
  }
}

let weightedPoints = 0;
let availableWeight = 0;
for (const [dimension, weight] of Object.entries(config.composite.weights)) {
  const score = dimensionScores[dimension];
  if (score == null) continue;
  weightedPoints += (score / 100) * weight;
  availableWeight += weight;
}

const complete = availableWeight === 100;
const report = {
  benchmark: config.name,
  shadowOnly: true,
  dimensionScores,
  weightedPoints,
  availableWeight,
  englishCore100: complete ? weightedPoints : null,
  note: complete
    ? "Full shadow composite available. Public-anchor results must still be reported separately."
    : "Composite withheld because one or more dimensions are missing. Supply score_0_100 for generative cases after rubric/human/specialist evaluation.",
  stats,
  misses,
};

console.log(JSON.stringify(report, null, 2));
