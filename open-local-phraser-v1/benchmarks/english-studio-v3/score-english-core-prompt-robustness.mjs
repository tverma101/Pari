#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseChoiceLetter } from "./english-core-choice-parser.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultPath = process.argv[2];
if (!resultPath) {
  console.error("Usage: node score-english-core-prompt-robustness.mjs <result.json>");
  process.exit(2);
}

const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const taskPath = path.join(here, "english-core-prompt-robustness.jsonl");
if (!fs.existsSync(taskPath)) throw new Error("Run build-english-core-prompt-robustness.mjs first");
const tasks = fs.readFileSync(taskPath, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse);
const run = JSON.parse(fs.readFileSync(resultPath, "utf8"));
const outputs = new Map((run.outputs ?? []).map((x) => [x.id, x]));
const byBase = new Map(seed.cases.map((x) => [x.id, x]));
const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

function permutation(length, id) {
  const order = Array.from({ length }, (_, i) => i);
  for (let i = length - 1; i > 0; i -= 1) {
    const digest = crypto.createHash("sha256").update(`${id}:option:${i}`).digest();
    const value = digest.readUInt32BE(0);
    const j = value % (i + 1);
    [order[i], order[j]] = [order[j], order[i]];
  }
  return order;
}

function baseChoiceIndex(row) {
  switch (row.task) {
    case "same_sense":
    case "same_meaning": return ["same", "different"].indexOf(row.answer);
    case "relation_preservation": return ["preserved", "changed"].indexOf(row.answer);
    case "best_substitute":
    case "minimal_pair":
    case "relation_label": return row.choices.indexOf(row.answer);
    case "acceptability_pair": return letters.indexOf(row.answer);
    case "closer_register":
    case "closer_meaning_and_register":
    case "more_natural": return row.answer;
    case "sentence_order": return row.choices.findIndex((x) => JSON.stringify(x) === JSON.stringify(row.answer));
    default: return -1;
  }
}

function choiceCount(row) {
  if (["same_sense", "same_meaning", "relation_preservation", "acceptability_pair"].includes(row.task)) return 2;
  return row.choices?.length ?? -1;
}

function expectedLetter(row) {
  const baseIndex = baseChoiceIndex(row);
  const n = choiceCount(row);
  if (baseIndex < 0 || n < 1) return null;
  const order = permutation(n, row.id);
  const idx = order.indexOf(baseIndex);
  return idx >= 0 ? letters[idx] : null;
}

function mean(xs) { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; }

const forced = tasks.filter((x) => !x.generative);
const detail = [];
for (const task of forced) {
  const row = byBase.get(task.baseId);
  const expected = expectedLetter(row);
  const got = outputs.get(task.id);
  const predicted = got ? parseChoiceLetter(got.output) : null;
  detail.push({
    id: task.id,
    baseId: task.baseId,
    dimension: task.dimension,
    promptVariant: task.promptVariant,
    expected,
    predicted,
    correct: predicted ? Number(predicted === expected) : 0,
    status: !got ? "missing" : (predicted ? "scored" : "invalid_output")
  });
}

function summarize(rows) {
  const variants = [...new Set(rows.map((x) => x.promptVariant))];
  const variantAccuracy = {};
  for (const v of variants) {
    const vr = rows.filter((x) => x.promptVariant === v);
    variantAccuracy[v] = mean(vr.map((x) => x.correct));
  }

  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.baseId)) groups.set(row.baseId, []);
    groups.get(row.baseId).push(row);
  }

  let allCorrect = 0;
  let majorityCorrect = 0;
  let answerConsistent = 0;
  let completeItems = 0;
  for (const itemRows of groups.values()) {
    if (itemRows.length !== variants.length) continue;
    completeItems += 1;
    if (itemRows.every((x) => x.correct === 1)) allCorrect += 1;
    if (itemRows.reduce((a, x) => a + x.correct, 0) >= Math.floor(variants.length / 2) + 1) majorityCorrect += 1;
    const answers = itemRows.map((x) => x.predicted).filter(Boolean);
    if (answers.length === variants.length && new Set(answers).size === 1) answerConsistent += 1;
  }

  const accValues = Object.values(variantAccuracy).filter((x) => typeof x === "number");
  return {
    baseCases: groups.size,
    taskInstances: rows.length,
    meanPromptAccuracy: mean(accValues),
    worstPromptAccuracy: accValues.length ? Math.min(...accValues) : null,
    bestPromptAccuracy: accValues.length ? Math.max(...accValues) : null,
    promptAccuracySpread: accValues.length ? Math.max(...accValues) - Math.min(...accValues) : null,
    allPromptsCorrectRate: completeItems ? allCorrect / completeItems : null,
    majorityPromptCorrectRate: completeItems ? majorityCorrect / completeItems : null,
    answerConsistencyRate: completeItems ? answerConsistent / completeItems : null,
    variantAccuracy
  };
}

const byDimension = {};
for (const dim of [...new Set(detail.map((x) => x.dimension))]) {
  byDimension[dim] = summarize(detail.filter((x) => x.dimension === dim));
}

const report = {
  version: 2,
  model: run.model ?? null,
  runId: run.runId ?? null,
  forcedChoice: summarize(detail),
  byDimension,
  generativeTaskInstancesPresent: tasks.filter((x) => x.generative).length,
  generativeNote: "Generative prompt sensitivity must be analyzed with the same independently validated metric/human protocol across variants; this scorer intentionally does not invent an automatic generative quality score.",
  interpretation: {
    primary: ["meanPromptAccuracy", "worstPromptAccuracy", "allPromptsCorrectRate", "answerConsistencyRate"],
    parserPolicy: "Only unambiguous choice forms are accepted; formatting wrappers such as 'The answer is A' are recovered, while free-form/inferred choices remain invalid.",
    rule: "Do not pick the best prompt after observing model results. Large promptAccuracySpread or low answerConsistencyRate is a robustness warning even when canonical accuracy is high."
  },
  researchBasis: [
    "Mizrahi et al., TACL 2024: State of What Art? A Call for Multi-Prompt LLM Evaluation",
    "Zhuo et al., Findings EMNLP 2024: ProSA",
    "Chatterjee et al., Findings EMNLP 2024: POSIX"
  ],
  detail
};

console.log(JSON.stringify(report, null, 2));
