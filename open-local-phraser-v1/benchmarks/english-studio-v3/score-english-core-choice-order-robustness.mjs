#!/usr/bin/env node

import crypto from "node:crypto";
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

function sha256Text(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

const taskPath = path.join(here, "english-core-choice-order-robustness.jsonl");
const answerPath = path.join(here, "english-core-choice-order-robustness.answers.json");
const manifestPath = path.join(here, "english-core-choice-order-robustness.manifest.json");
if (!fs.existsSync(taskPath) || !fs.existsSync(answerPath) || !fs.existsSync(manifestPath)) {
  throw new Error("Run build-english-core-choice-order-robustness.mjs first");
}
const taskText = fs.readFileSync(taskPath, "utf8");
const tasks = taskText.trim().split("\n").filter(Boolean).map(JSON.parse);
const answerText = fs.readFileSync(answerPath, "utf8");
const answers = JSON.parse(answerText).answers;
const manifestText = fs.readFileSync(manifestPath, "utf8");
const manifest = JSON.parse(manifestText);
const run = JSON.parse(fs.readFileSync(resultPath, "utf8"));

const taskIds = tasks.map((task) => task.id);
if (new Set(taskIds).size !== taskIds.length) throw new Error("Choice-order task file contains duplicate IDs");
if (setDifference(new Set(taskIds), new Set(Object.keys(answers))).size || setDifference(new Set(Object.keys(answers)), new Set(taskIds)).size) {
  throw new Error("Choice-order answer keys do not exactly match task IDs");
}
if (Number(manifest.taskInstances) !== tasks.length) throw new Error("Choice-order manifest taskInstances does not match task file");
const canonicalTaskSha256 = sha256Text(taskText);
if (run.taskFileSha256 !== canonicalTaskSha256) throw new Error("Result taskFileSha256 does not match english-core-choice-order-robustness.jsonl");
if (Number(run.taskCount) !== tasks.length) throw new Error(`Result taskCount ${run.taskCount} does not match choice-order task count ${tasks.length}`);

const outputRows = run.outputs ?? [];
if (!Array.isArray(outputRows)) throw new Error("Result outputs must be an array");
const outputIds = outputRows.map((row) => row?.id);
if (outputIds.some((id) => !id)) throw new Error("Result contains an output without an ID");
if (new Set(outputIds).size !== outputIds.length) throw new Error("Result contains duplicate output IDs");
const taskIdSet = new Set(taskIds);
const extraIds = outputIds.filter((id) => !taskIdSet.has(id));
if (extraIds.length) throw new Error(`Result contains ${extraIds.length} IDs not present in the choice-order task file`);
const outputs = new Map(outputRows.map((row) => [row.id, row]));

function setDifference(a, b) {
  return new Set([...a].filter((x) => !b.has(x)));
}

const detail = [];
for (const task of tasks) {
  const meta = answers[task.id];
  if (!meta) throw new Error(`Missing choice-order answer metadata for ${task.id}`);
  const got = outputs.get(task.id);
  const parsedLetter = got ? parseChoiceLetter(got.output) : null;
  const predictedBaseChoiceIndex = parsedLetter == null ? null : meta.baseIndexByLetter[parsedLetter];
  const valid = Number.isInteger(predictedBaseChoiceIndex);
  detail.push({
    id: task.id,
    baseId: task.baseId,
    orderVariant: task.orderVariant,
    dimension: task.dimension,
    phenomenon: task.phenomenon ?? null,
    expectedLetter: meta.expectedLetter,
    parsedLetter,
    predictedLetter: valid ? parsedLetter : null,
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
  let structurallyCompletePairs = 0;
  let fullyValidPairs = 0;
  let bothCorrectAll = 0;
  let bothCorrectValid = 0;
  let eitherCorrectValid = 0;
  let semanticConsistentValid = 0;
  let oneCorrectOneWrongValid = 0;
  for (const pair of byBase.values()) {
    if (pair.length !== 2) continue;
    structurallyCompletePairs += 1;
    const allValid = pair.every((x) => x.status === "scored");
    const correctCount = pair.reduce((a, x) => a + x.correct, 0);
    if (correctCount === 2) bothCorrectAll += 1;
    if (!allValid) continue;
    fullyValidPairs += 1;
    if (correctCount === 2) bothCorrectValid += 1;
    if (correctCount >= 1) eitherCorrectValid += 1;
    if (correctCount === 1) oneCorrectOneWrongValid += 1;
    if (pair[0].predictedBaseChoiceIndex === pair[1].predictedBaseChoiceIndex) semanticConsistentValid += 1;
  }
  const v0 = rows.filter((x) => x.orderVariant === 0);
  const v1 = rows.filter((x) => x.orderVariant === 1);
  return {
    baseCases: byBase.size,
    taskInstances: rows.length,
    validOutputCoverage: rows.length ? rows.filter((x) => x.status === "scored").length / rows.length : null,
    presentation0AccuracyInvalidAsWrong: v0.length ? mean(v0.map((x) => x.correct)) : null,
    presentation1AccuracyInvalidAsWrong: v1.length ? mean(v1.map((x) => x.correct)) : null,
    averagePresentationAccuracyInvalidAsWrong: rows.length ? mean(rows.map((x) => x.correct)) : null,
    structurallyCompletePairs,
    fullyValidPairs,
    fullyValidPairRate: structurallyCompletePairs ? fullyValidPairs / structurallyCompletePairs : null,
    bothOrdersCorrectRate: structurallyCompletePairs ? bothCorrectAll / structurallyCompletePairs : null,
    bothOrdersCorrectRateAmongFullyValidPairs: fullyValidPairs ? bothCorrectValid / fullyValidPairs : null,
    atLeastOneOrderCorrectRateAmongFullyValidPairs: fullyValidPairs ? eitherCorrectValid / fullyValidPairs : null,
    semanticAnswerConsistencyRateAmongFullyValidPairs: fullyValidPairs ? semanticConsistentValid / fullyValidPairs : null,
    oneCorrectOneWrongRateAmongFullyValidPairs: fullyValidPairs ? oneCorrectOneWrongValid / fullyValidPairs : null,
  };
}

const dimensions = [...new Set(detail.map((x) => x.dimension))];
const byDimension = Object.fromEntries(dimensions.map((d) => [d, summarize(detail.filter((x) => x.dimension === d))]));

const report = {
  version: 2,
  runId: run.runId ?? null,
  model: run.model ?? null,
  taskFileSha256: run.taskFileSha256 ?? null,
  taskCount: run.taskCount ?? null,
  benchmarkInputs: {
    choiceOrderTaskSha256: canonicalTaskSha256,
    choiceOrderAnswerSha256: sha256Text(answerText),
    choiceOrderManifestSha256: sha256Text(manifestText),
  },
  overall: summarize(detail),
  byDimension,
  detail,
  interpretationRules: [
    "This is a robustness diagnostic, not an additional weighted English Core score.",
    "The strict bothOrdersCorrectRate uses every structurally complete counterbalanced base case as its denominator; an invalid/missing response on either order therefore prevents that base case from counting as robustly correct.",
    "Conditional rates amongFullyValidPairs are also reported so semantic order sensitivity can be separated from formatting/refusal instability.",
    "semanticAnswerConsistencyRateAmongFullyValidPairs compares the underlying selected option rather than the displayed letter, so a correct A->B shift after reordering counts as consistent.",
    "oneCorrectOneWrongRateAmongFullyValidPairs exposes genuine position-sensitive judgments only when both presentations produced valid options.",
    "Presentation accuracy counts invalid/missing responses as wrong and valid-output coverage is reported separately.",
    "The scorer is bound to exact task/answer/manifest bytes and rejects duplicate or extra run-output IDs.",
    "A substantial order effect or poor fullyValidPairRate weakens claims from single-order prompted forced-choice scores and should be reported rather than averaged away."
  ],
  researchBasis: [
    "Wei et al., Findings ACL 2024, Unveiling Selection Biases: Exploring Order and Token Sensitivity in Large Language Models",
    "Alzahrani et al., ACL 2024, benchmark perturbation and answer-order sensitivity"
  ]
};

console.log(JSON.stringify(report, null, 2));
