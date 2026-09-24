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

function sha256Text(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

const seedText = fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8");
const seed = JSON.parse(seedText);
const taskPath = path.join(here, "english-core-prompt-robustness.jsonl");
const manifestPath = path.join(here, "english-core-prompt-robustness.manifest.json");
if (!fs.existsSync(taskPath) || !fs.existsSync(manifestPath)) throw new Error("Run build-english-core-prompt-robustness.mjs first");
const taskText = fs.readFileSync(taskPath, "utf8");
const tasks = taskText.trim().split("\n").filter(Boolean).map(JSON.parse);
const manifestText = fs.readFileSync(manifestPath, "utf8");
const manifest = JSON.parse(manifestText);
const run = JSON.parse(fs.readFileSync(resultPath, "utf8"));
const byBase = new Map(seed.cases.map((x) => [x.id, x]));
const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

const taskIds = tasks.map((task) => task.id);
if (new Set(taskIds).size !== taskIds.length) throw new Error("Prompt-robustness task file contains duplicate IDs");
if (Number(manifest.taskInstances) !== tasks.length) throw new Error("Prompt-robustness manifest taskInstances does not match task file");
if (Number(manifest.baseCases) !== seed.cases.length) throw new Error("Prompt-robustness manifest baseCases does not match shadow seed");
const canonicalTaskSha256 = sha256Text(taskText);
if (run.taskFileSha256 !== canonicalTaskSha256) throw new Error("Result taskFileSha256 does not match english-core-prompt-robustness.jsonl");
if (Number(run.taskCount) !== tasks.length) throw new Error(`Result taskCount ${run.taskCount} does not match prompt-robustness task count ${tasks.length}`);

const outputRows = run.outputs ?? [];
if (!Array.isArray(outputRows)) throw new Error("Result outputs must be an array");
const outputIds = outputRows.map((row) => row?.id);
if (outputIds.some((id) => !id)) throw new Error("Result contains an output without an ID");
if (new Set(outputIds).size !== outputIds.length) throw new Error("Result contains duplicate output IDs");
const taskIdSet = new Set(taskIds);
const extras = outputIds.filter((id) => !taskIdSet.has(id));
if (extras.length) throw new Error(`Result contains ${extras.length} IDs not present in the prompt-robustness task file`);
const outputs = new Map(outputRows.map((row) => [row.id, row]));

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
  if (baseIndex < 0 || n < 1 || baseIndex >= n) return null;
  const order = permutation(n, row.id);
  const idx = order.indexOf(baseIndex);
  return idx >= 0 ? letters[idx] : null;
}

function validChoice(row, parsed) {
  if (!parsed) return null;
  const n = choiceCount(row);
  const idx = letters.indexOf(parsed);
  return n > 0 && idx >= 0 && idx < n ? parsed : null;
}

function mean(xs) { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; }

const forced = tasks.filter((x) => !x.generative);
const detail = [];
for (const task of forced) {
  const row = byBase.get(task.baseId);
  if (!row) throw new Error(`Prompt-robustness task ${task.id} references unknown baseId ${task.baseId}`);
  const expected = expectedLetter(row);
  if (!expected) throw new Error(`Cannot derive gold answer for ${task.id}`);
  const got = outputs.get(task.id);
  const parsed = got ? parseChoiceLetter(got.output) : null;
  const predicted = validChoice(row, parsed);
  detail.push({
    id: task.id,
    baseId: task.baseId,
    dimension: task.dimension,
    phenomenon: task.phenomenon ?? null,
    promptVariant: task.promptVariant,
    expected,
    parsedLetter: parsed,
    predicted,
    correct: predicted ? Number(predicted === expected) : 0,
    status: !got ? "missing" : (predicted ? "scored" : "invalid_output")
  });
}

function summarize(rows) {
  const variants = [...new Set(rows.map((x) => x.promptVariant))];
  const variantAccuracy = {};
  const variantCoverage = {};
  for (const v of variants) {
    const vr = rows.filter((x) => x.promptVariant === v);
    variantAccuracy[v] = mean(vr.map((x) => x.correct));
    variantCoverage[v] = vr.length ? vr.filter((x) => x.status === "scored").length / vr.length : null;
  }

  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.baseId)) groups.set(row.baseId, []);
    groups.get(row.baseId).push(row);
  }

  let allCorrect = 0;
  let majorityCorrect = 0;
  let answerConsistent = 0;
  let allVariantsValid = 0;
  let structurallyCompleteItems = 0;
  for (const itemRows of groups.values()) {
    if (itemRows.length !== variants.length) continue;
    structurallyCompleteItems += 1;
    const allValid = itemRows.every((x) => x.status === "scored");
    if (allValid) allVariantsValid += 1;
    if (itemRows.every((x) => x.correct === 1)) allCorrect += 1;
    if (itemRows.reduce((a, x) => a + x.correct, 0) >= Math.floor(variants.length / 2) + 1) majorityCorrect += 1;
    if (allValid && new Set(itemRows.map((x) => x.predicted)).size === 1) answerConsistent += 1;
  }

  const accValues = Object.values(variantAccuracy).filter((x) => typeof x === "number");
  const scoredTasks = rows.filter((x) => x.status === "scored").length;
  return {
    baseCases: groups.size,
    taskInstances: rows.length,
    validOutputCoverage: rows.length ? scoredTasks / rows.length : null,
    allVariantsValidRate: structurallyCompleteItems ? allVariantsValid / structurallyCompleteItems : null,
    meanPromptAccuracyInvalidAsWrong: mean(accValues),
    worstPromptAccuracyInvalidAsWrong: accValues.length ? Math.min(...accValues) : null,
    bestPromptAccuracyInvalidAsWrong: accValues.length ? Math.max(...accValues) : null,
    promptAccuracySpread: accValues.length ? Math.max(...accValues) - Math.min(...accValues) : null,
    allPromptsCorrectRate: structurallyCompleteItems ? allCorrect / structurallyCompleteItems : null,
    majorityPromptCorrectRate: structurallyCompleteItems ? majorityCorrect / structurallyCompleteItems : null,
    semanticAnswerConsistencyRateAllItems: structurallyCompleteItems ? answerConsistent / structurallyCompleteItems : null,
    semanticAnswerConsistencyRateAmongFullyValidItems: allVariantsValid ? answerConsistent / allVariantsValid : null,
    variantAccuracyInvalidAsWrong: variantAccuracy,
    variantValidOutputCoverage: variantCoverage,
  };
}

const byDimension = {};
for (const dim of [...new Set(detail.map((x) => x.dimension))]) {
  byDimension[dim] = summarize(detail.filter((x) => x.dimension === dim));
}

const report = {
  version: 3,
  model: run.model ?? null,
  runId: run.runId ?? null,
  taskFileSha256: run.taskFileSha256 ?? null,
  taskCount: run.taskCount ?? null,
  benchmarkInputs: {
    shadowSeedSha256: sha256Text(seedText),
    promptRobustnessTaskSha256: canonicalTaskSha256,
    promptRobustnessManifestSha256: sha256Text(manifestText),
  },
  forcedChoice: summarize(detail),
  byDimension,
  generativeTaskInstancesPresent: tasks.filter((x) => x.generative).length,
  generativeNote: "Generative prompt sensitivity must be analyzed with the same independently validated metric/human protocol across variants; this scorer intentionally does not invent an automatic generative quality score.",
  interpretation: {
    primary: ["meanPromptAccuracyInvalidAsWrong", "worstPromptAccuracyInvalidAsWrong", "allPromptsCorrectRate", "semanticAnswerConsistencyRateAllItems", "validOutputCoverage"],
    parserPolicy: "Only unambiguous choice forms are accepted, and a parsed letter outside the actual option range is invalid. Formatting wrappers such as 'The answer is A' are recovered; free-form/inferred choices remain invalid.",
    coveragePolicy: "Invalid/missing responses count as wrong in robustness accuracy and are separately exposed through valid-output coverage. Semantic consistency is reported both over all base items and conditionally among items whose three outputs were all valid.",
    rule: "Do not pick the best prompt after observing model results. Large promptAccuracySpread, low all-prompts-correct, low consistency, or weak output coverage is a robustness warning even when canonical accuracy is high."
  },
  researchBasis: [
    "Mizrahi et al., TACL 2024: State of What Art? A Call for Multi-Prompt LLM Evaluation",
    "Zhuo et al., Findings EMNLP 2024: ProSA",
    "Chatterjee et al., Findings EMNLP 2024: POSIX"
  ],
  detail
};

console.log(JSON.stringify(report, null, 2));
