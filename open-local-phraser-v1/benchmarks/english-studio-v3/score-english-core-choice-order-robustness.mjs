#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseChoiceLetter } from "./english-core-choice-parser.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultPath = process.argv[2];
if (!resultPath) {
  console.error("Usage: node score-english-core-choice-order-robustness.mjs <result.json>");
  process.exit(2);
}

const taskPath = path.join(here, "english-core-choice-order-robustness.jsonl");
const answerPath = path.join(here, "english-core-choice-order-robustness.answers.json");
if (!fs.existsSync(taskPath) || !fs.existsSync(answerPath)) {
  throw new Error("Run build-english-core-choice-order-robustness.mjs first");
}
const tasks = fs.readFileSync(taskPath, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse);
const answers = JSON.parse(fs.readFileSync(answerPath, "utf8")).answers;
const run = JSON.parse(fs.readFileSync(resultPath, "utf8"));
const outputs = new Map((run.outputs ?? []).map((x) => [x.id, x]));

const detail = [];
for (const task of tasks) {
  const meta = answers[task.id];
  const got = outputs.get(task.id);
  const predictedLetter = got ? parseChoiceLetter(got.output) : null;
  const predictedBaseChoiceIndex = predictedLetter == null ? null : meta.baseIndexByLetter[predictedLetter];
  const valid = Number.isInteger(predictedBaseChoiceIndex);
  detail.push({
    id: task.id,
    baseId: task.baseId,
    orderVariant: task.orderVariant,
    dimension: task.dimension,
    phenomenon: task.phenomenon ?? null,
    expectedLetter: meta.expectedLetter,
    predictedLetter,
    goldBaseChoiceIndex: meta.goldBaseChoiceIndex,
    predictedBaseChoiceIndex: valid ? predictedBaseChoiceIndex : null,
    correct: valid ? Number(predictedBaseChoiceIndex === meta.goldBaseChoiceIndex) : 0,
    status: !got ? "missing" : (valid ? "scored" : "invalid_output"),
  });
}

function mean(xs) { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; }

function summarize(rows) {
  const byBase = new Map();
  for (const row of rows) {
    if (!byBase.has(row.baseId)) byBase.set(row.baseId, []);
    byBase.get(row.baseId).push(row);
  }
  let completePairs = 0;
  let bothCorrect = 0;
  let eitherCorrect = 0;
  let semanticConsistent = 0;
  let oneCorrectOneWrong = 0;
  for (const pair of byBase.values()) {
    if (pair.length !== 2 || pair.some((x) => x.status !== "scored")) continue;
    completePairs += 1;
    const correctCount = pair.reduce((a, x) => a + x.correct, 0);
    if (correctCount === 2) bothCorrect += 1;
    if (correctCount >= 1) eitherCorrect += 1;
    if (correctCount === 1) oneCorrectOneWrong += 1;
    if (pair[0].predictedBaseChoiceIndex === pair[1].predictedBaseChoiceIndex) semanticConsistent += 1;
  }
  const v0 = rows.filter((x) => x.orderVariant === 0);
  const v1 = rows.filter((x) => x.orderVariant === 1);
  return {
    baseCases: byBase.size,
    taskInstances: rows.length,
    validOutputCoverage: rows.length ? rows.filter((x) => x.status === "scored").length / rows.length : null,
    presentation0Accuracy: v0.length ? mean(v0.map((x) => x.correct)) : null,
    presentation1Accuracy: v1.length ? mean(v1.map((x) => x.correct)) : null,
    averagePresentationAccuracy: rows.length ? mean(rows.map((x) => x.correct)) : null,
    completePairs,
    bothOrdersCorrectRate: completePairs ? bothCorrect / completePairs : null,
    atLeastOneOrderCorrectRate: completePairs ? eitherCorrect / completePairs : null,
    semanticAnswerConsistencyRate: completePairs ? semanticConsistent / completePairs : null,
    oneCorrectOneWrongRate: completePairs ? oneCorrectOneWrong / completePairs : null,
  };
}

const dimensions = [...new Set(detail.map((x) => x.dimension))];
const byDimension = Object.fromEntries(dimensions.map((d) => [d, summarize(detail.filter((x) => x.dimension === d))]));

const report = {
  version: 1,
  runId: run.runId ?? null,
  model: run.model ?? null,
  overall: summarize(detail),
  byDimension,
  detail,
  interpretationRules: [
    "This is a robustness diagnostic, not an additional weighted English Core score.",
    "bothOrdersCorrectRate is the strictest simple measure: the linguistic judgment must survive both option positions.",
    "semanticAnswerConsistencyRate compares the underlying selected option rather than the displayed letter, so a correct A->B shift after reordering counts as consistent.",
    "oneCorrectOneWrongRate exposes position-sensitive items even when average accuracy looks acceptable.",
    "Missing/invalid outputs are not silently excluded from presentation accuracy; pair-based rates require both presentations to be parseable.",
    "A substantial order effect weakens claims from single-order prompted forced-choice scores and should be reported rather than averaged away."
  ],
  researchBasis: [
    "Wei et al., Findings ACL 2024, Unveiling Selection Biases: Exploring Order and Token Sensitivity in Large Language Models",
    "Alzahrani et al., ACL 2024, benchmark perturbation and answer-order sensitivity"
  ]
};

console.log(JSON.stringify(report, null, 2));
