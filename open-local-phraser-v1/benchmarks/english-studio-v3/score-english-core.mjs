#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultPath = process.argv[2];
if (!resultPath) {
  console.error("Usage: node score-english-core.mjs <result.json>");
  process.exit(2);
}

const config = JSON.parse(fs.readFileSync(path.join(here, "english-core-config.json"), "utf8"));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const run = JSON.parse(fs.readFileSync(resultPath, "utf8"));

const outputs = new Map((run.outputs ?? []).map((x) => [x.id, x]));
const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

function choiceIndex(row) {
  switch (row.task) {
    case "same_sense":
    case "same_meaning":
      return ["same", "different"].indexOf(row.answer);
    case "relation_preservation":
      return ["preserved", "changed"].indexOf(row.answer);
    case "best_substitute":
    case "minimal_pair":
    case "relation_label":
      return row.choices.indexOf(row.answer);
    case "acceptability_pair":
      return letters.indexOf(row.answer);
    case "closer_register":
    case "closer_meaning_and_register":
    case "more_natural":
      return row.answer;
    case "sentence_order":
      return row.choices.findIndex((x) => JSON.stringify(x) === JSON.stringify(row.answer));
    default:
      return -1;
  }
}

function parseLetter(text) {
  const s = String(text ?? "").trim().toUpperCase();
  if (!s) return null;

  // Do not turn this benchmark into an instruction-format test. Accept common
  // harmless wrappers while still refusing to mine a long explanation for a guess.
  const patterns = [
    /^([A-Z])$/,
    /^([A-Z])(?:[.)\]:-])(?:\s|$)/,
    /^ANSWER\s*[:=-]\s*([A-Z])(?:\b|[.)\]:-])/,
    /^OPTION\s+([A-Z])(?:\b|[.)\]:-])/,
  ];
  for (const pattern of patterns) {
    const match = s.match(pattern);
    if (match) return match[1];
  }
  return null;
}

function mean(values) {
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

const detail = [];
for (const row of seed.cases) {
  const got = outputs.get(row.id);
  if (!got) {
    detail.push({ id: row.id, dimension: row.dimension, task: row.task, status: "missing", score: null });
    continue;
  }

  if (row.dimension === "generative_expression") {
    const requiredMetrics = row.scoring ?? [];
    const scores = got.metricScores ?? {};
    const missing = requiredMetrics.filter((m) => typeof scores[m] !== "number" || scores[m] < 0 || scores[m] > 1);
    if (missing.length || !got.metricSource) {
      detail.push({
        id: row.id,
        dimension: row.dimension,
        task: row.task,
        status: "needs_external_scoring",
        missingMetrics: missing,
        score: null,
      });
      continue;
    }
    const score = mean(requiredMetrics.map((m) => scores[m]));
    detail.push({ id: row.id, dimension: row.dimension, task: row.task, status: "scored", score, metricSource: got.metricSource });
    continue;
  }

  const expectedIndex = choiceIndex(row);
  if (expectedIndex < 0) throw new Error(`Cannot derive gold answer for ${row.id}`);
  const expected = letters[expectedIndex];
  const predicted = parseLetter(got.output);
  detail.push({
    id: row.id,
    dimension: row.dimension,
    task: row.task,
    status: predicted ? "scored" : "invalid_output",
    expected,
    predicted,
    score: predicted ? Number(predicted === expected) : 0,
  });
}

const dimensionScores = {};
for (const dimension of Object.keys(config.dimensions)) {
  const rows = detail.filter((x) => x.dimension === dimension);
  const scored = rows.filter((x) => typeof x.score === "number");
  dimensionScores[dimension] = {
    cases: rows.length,
    scored: scored.length,
    missing: rows.length - scored.length,
    score100: scored.length === rows.length ? mean(scored.map((x) => x.score)) * 100 : null,
  };
}

let englishCore100 = 0;
let complete = true;
for (const [dimension, weight] of Object.entries(config.composite.weights)) {
  const value = dimensionScores[dimension]?.score100;
  if (typeof value !== "number") {
    complete = false;
    continue;
  }
  englishCore100 += value * (weight / 100);
}

const report = {
  version: 1,
  runId: run.runId ?? null,
  model: run.model ?? null,
  shadowCases: seed.cases.length,
  dimensionScores,
  englishCoreShadow100: complete ? Number(englishCore100.toFixed(3)) : null,
  complete,
  notes: [
    "This scorer covers the fresh Pari shadow set only; public-anchor benchmark results must be reported separately.",
    "Forced-choice cases are deterministically scored from the private seed answer key.",
    "Generative cases require normalized external metricScores and a metricSource; candidate-model self-grading is not accepted.",
    "Harmless answer wrappers such as `Answer: A` are accepted so formatting compliance is not confused with English competence.",
    "Runtime, RAM and quantization do not affect English Core competence scores.",
  ],
  detail,
};

console.log(JSON.stringify(report, null, 2));
