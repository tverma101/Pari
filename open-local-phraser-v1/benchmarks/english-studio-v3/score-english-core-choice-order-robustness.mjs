#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CHOICE_STATUS, parseChoice } from "./english-core-choice-parser.mjs";
import { validateEnglishCoreResult } from "./english-core-result-contract.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultPath = process.argv[2];
if (!resultPath) {
  console.error("Usage: node score-english-core-choice-order-robustness.mjs <result.json>");
  process.exit(2);
}
const resultValidation = validateEnglishCoreResult(resultPath, {
  promotion: process.argv.includes("--promotion"),
  compatLegacyV0: process.argv.includes("--compat-legacy-v0"),
});

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

// Issue #64: the frozen strict/recoverable forced-choice identity block.
//
// These strings restate the constants in english_core_choice_views.py, which is
// the frozen shared contract for the strict/recoverable split. The Python
// scorers publish them from that module and english-core-snapshot-binding.mjs
// restates the same values independently, so the three restatements have to
// move together; english-core-snapshot-binding.mjs fails closed on any
// disagreement and test_mjs_score_view_contract.py checks the parity. This file
// must not become the place where the policy is edited.
const SCORE_VIEW_CONTRACT_VERSION = "strict-recoverable-choice-views-v1";
const SCORE_VIEW_DENOMINATOR_POLICY = "fixed-screening-denominator-v1";
const SCORE_VIEW_ALLOWED_LABEL_CONTRACT = "allowed-choices-frozen-v1";
const SCORE_VIEW_CONTRACT_FILE = "english_core_choice_views.py";
const STRICT_SCORE_VIEW = "strict";
const PRIMARY_SCREENING_SCORE_VIEW = "recoverable_anchored";
const SCORE_VIEW_METRIC_KEYS = Object.freeze({
  [STRICT_SCORE_VIEW]: "strictAccuracyFixedDenominator",
  [PRIMARY_SCREENING_SCORE_VIEW]: "recoverableAccuracyFixedDenominator",
});
const STRICT_ALLOWED_STATUSES = new Set([CHOICE_STATUS.STRICT_ALLOWED]);
const RECOVERABLE_ALLOWED_STATUSES = new Set([
  CHOICE_STATUS.STRICT_ALLOWED,
  CHOICE_STATUS.RECOVERABLE_ALLOWED,
]);
const TRUNCATION_FINISH_REASONS = new Set(["length", "max_tokens", "token_limit", "max_new_tokens"]);
const RUNTIME_UNQUALIFIED_STATUSES = new Set([
  "runtime_unqualified", "failed", "incomplete", "error", "crashed", "aborted", "timeout",
]);

// Mirrors english_core_choice_views.run_runtime_qualification.
function runRuntimeQualification(source) {
  if (!source || typeof source !== "object") {
    return { runtimeQualified: false, runtimeQualificationReason: "result_is_not_an_object" };
  }
  const status = source.status == null ? null : String(source.status).trim().toLowerCase();
  if (status !== null && RUNTIME_UNQUALIFIED_STATUSES.has(status)) {
    return { runtimeQualified: false, runtimeQualificationReason: `run_status_${status}` };
  }
  if (source.complete === false) {
    return { runtimeQualified: false, runtimeQualificationReason: "run_reports_incomplete" };
  }
  const completed = source.completedCount;
  const taskCount = source.taskCount;
  if (Number.isInteger(completed) && Number.isInteger(taskCount) && taskCount > 0 && completed < taskCount) {
    return {
      runtimeQualified: false,
      runtimeQualificationReason: `completed_count_${completed}_below_task_count_${taskCount}`,
    };
  }
  return { runtimeQualified: true, runtimeQualificationReason: null };
}

// One parse of the preserved raw output feeds both views, evaluated against the
// frozen base-choice gold index rather than the displayed letter. The gold
// index is only compared after the fact, so a correct recoverable answer can
// never mutate strict correctness.
function scoreChoiceViews(rawOutput, {
  allowedChoices,
  baseIndexByLetter,
  goldBaseChoiceIndex,
  runtimeUnqualified,
  missing,
  finishReason,
  truncated,
}) {
  const parse = parseChoice(rawOutput, allowedChoices);
  const strictParsedChoice = STRICT_ALLOWED_STATUSES.has(parse.status) ? parse.letter : null;
  const recoverableParsedChoice = RECOVERABLE_ALLOWED_STATUSES.has(parse.status) ? parse.letter : null;
  const strictProtocolValid = strictParsedChoice !== null;
  const recoverableProtocolValid = recoverableParsedChoice !== null;
  const strictBaseChoiceIndex = strictProtocolValid ? baseIndexByLetter[strictParsedChoice] : null;
  const recoverableBaseChoiceIndex = recoverableProtocolValid ? baseIndexByLetter[recoverableParsedChoice] : null;

  let strictCorrect = null;
  let recoverableCorrect = null;
  if (!runtimeUnqualified && Number.isInteger(goldBaseChoiceIndex)) {
    strictCorrect = Number.isInteger(strictBaseChoiceIndex) && strictBaseChoiceIndex === goldBaseChoiceIndex;
    recoverableCorrect = Number.isInteger(recoverableBaseChoiceIndex) && recoverableBaseChoiceIndex === goldBaseChoiceIndex;
  }

  const finishText = finishReason == null ? null : String(finishReason).trim().toLowerCase();
  const truncatedOutput = Boolean(truncated) || TRUNCATION_FINISH_REASONS.has(finishText);
  const ambiguous = parse.status === CHOICE_STATUS.AMBIGUOUS;
  const invalidOptionLabelStatus = parse.status === CHOICE_STATUS.STRICT_INVALID_LABEL
    || parse.status === CHOICE_STATUS.RECOVERABLE_INVALID_LABEL;

  let outcome;
  if (runtimeUnqualified) outcome = "runtime_unqualified_excluded_from_denominator";
  else if (missing) outcome = "missing_output";
  else if (strictCorrect && recoverableCorrect) outcome = "strict_and_recoverable_correct";
  else if (recoverableCorrect) outcome = "recoverable_only_correct_format_recovery";
  else if (strictParsedChoice !== null && recoverableParsedChoice !== null) {
    outcome = "strict_and_recoverable_wrong_allowed_choice";
  } else if (truncatedOutput) outcome = "truncated_output";
  else if (ambiguous) outcome = "ambiguous_multiple_choices";
  else if (parse.status === CHOICE_STATUS.EMPTY
    || parse.status === CHOICE_STATUS.WHITESPACE
    || parse.status === CHOICE_STATUS.NO_ANCHORED_ANSWER) {
    outcome = "non_answer_no_anchored_label";
  } else outcome = "invalid_protocol_output";

  return {
    parseViewContractVersion: SCORE_VIEW_CONTRACT_VERSION,
    denominatorPolicyVersion: SCORE_VIEW_DENOMINATOR_POLICY,
    allowedLabelContractVersion: SCORE_VIEW_ALLOWED_LABEL_CONTRACT,
    rawOutput: parse.rawOutput,
    rawOutputPreserved: true,
    allowedChoices: parse.allowedChoices ?? null,
    allowedChoicesFrozen: parse.allowedSetFrozen,
    finishReason: finishReason ?? null,
    strictParsedChoice,
    recoverableParsedChoice,
    strictProtocolValid,
    recoverableProtocolValid,
    strictBaseChoiceIndex: Number.isInteger(strictBaseChoiceIndex) ? strictBaseChoiceIndex : null,
    recoverableBaseChoiceIndex: Number.isInteger(recoverableBaseChoiceIndex) ? recoverableBaseChoiceIndex : null,
    strictCorrect,
    recoverableCorrect,
    viewsDisagree: strictParsedChoice !== recoverableParsedChoice,
    recoveredOnly: recoverableProtocolValid && !strictProtocolValid,
    choiceStatus: parse.status,
    ambiguous,
    truncatedOutput,
    invalidOptionLabel: parse.invalidOptionLabel,
    invalidOptionLabelStatus,
    anchoredLabel: parse.anchoredLabel,
    goldBaseChoiceIndexForComparison: Number.isInteger(goldBaseChoiceIndex) ? goldBaseChoiceIndex : null,
    outcome,
  };
}

function rate(numerator, denominator) {
  return denominator ? Number((numerator / denominator).toFixed(6)) : null;
}

function wilson95(successes, n) {
  if (n <= 0) return null;
  const z = 1.959963984540054;
  const p = successes / n;
  const denom = 1 + z * z / n;
  const center = (p + z * z / (2 * n)) / denom;
  const half = z * Math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n))) / denom;
  return [Number(Math.max(0, center - half).toFixed(6)), Number(Math.min(1, center + half).toFixed(6))];
}

// Mirrors english_core_choice_views.summarize_choice_views over one fixed
// denominator. Runtime-unqualified rows leave the denominator entirely so an
// infrastructure failure can never become an English zero.
function summarizeChoiceViews(rows) {
  const excluded = rows.filter((row) => row.outcome === "runtime_unqualified_excluded_from_denominator");
  const scored = rows.filter((row) => row.outcome !== "runtime_unqualified_excluded_from_denominator");
  const denominator = scored.length;
  const strictValid = scored.filter((row) => row.strictProtocolValid).length;
  const recoverableValid = scored.filter((row) => row.recoverableProtocolValid).length;
  const strictCorrect = scored.filter((row) => row.strictCorrect === true).length;
  const recoverableCorrect = scored.filter((row) => row.recoverableCorrect === true).length;
  const disagreements = scored.filter((row) => row.viewsDisagree).length;
  const recoverableOnly = scored.filter((row) => row.recoveredOnly).length;
  const ambiguousCount = scored.filter((row) => row.ambiguous).length;
  const outcomeCount = (name) => scored.filter((row) => row.outcome === name).length;
  const invalidLabels = [...new Set(scored.map((row) => row.invalidOptionLabel).filter(Boolean))].sort();

  return {
    denominatorPolicy: SCORE_VIEW_DENOMINATOR_POLICY,
    parseViewContractVersion: SCORE_VIEW_CONTRACT_VERSION,
    allowedLabelContractVersion: SCORE_VIEW_ALLOWED_LABEL_CONTRACT,
    fixedDenominator: denominator,
    excludedRuntimeUnqualified: excluded.length,
    strictValidOutputCoverage: rate(strictValid, denominator),
    strictValidOutputCount: strictValid,
    strictAccuracyFixedDenominator: rate(strictCorrect, denominator),
    strictCorrectCount: strictCorrect,
    strictAccuracyFixedDenominatorWilson95: wilson95(strictCorrect, denominator),
    recoverableValidOutputCoverage: rate(recoverableValid, denominator),
    recoverableValidOutputCount: recoverableValid,
    recoverableAccuracyFixedDenominator: rate(recoverableCorrect, denominator),
    recoverableCorrectCount: recoverableCorrect,
    recoverableAccuracyFixedDenominatorWilson95: wilson95(recoverableCorrect, denominator),
    strictAccuracyGivenStrictValid: rate(strictCorrect, strictValid),
    recoverableAccuracyGivenRecoverableValid: rate(recoverableCorrect, recoverableValid),
    strictRecoverableDisagreementCount: disagreements,
    strictRecoverableDisagreementRate: rate(disagreements, denominator),
    recoverableOnlyCount: recoverableOnly,
    recoverableOnlyRate: rate(recoverableOnly, denominator),
    outcomes: {
      strict_and_recoverable_correct: outcomeCount("strict_and_recoverable_correct"),
      recoverable_only_correct_format_recovery: outcomeCount("recoverable_only_correct_format_recovery"),
      strict_and_recoverable_wrong_allowed_choice: outcomeCount("strict_and_recoverable_wrong_allowed_choice"),
      invalid_protocol_output: outcomeCount("invalid_protocol_output"),
      missing_output: outcomeCount("missing_output"),
      ambiguous_multiple_choices: outcomeCount("ambiguous_multiple_choices"),
      non_answer_no_anchored_label: outcomeCount("non_answer_no_anchored_label"),
      truncated_output: outcomeCount("truncated_output"),
      runtime_unqualified_excluded_from_denominator: excluded.length,
    },
    ambiguousOutputCount: ambiguousCount,
    ambiguousOutputRate: rate(ambiguousCount, denominator),
    nonAnswerOutputCount: outcomeCount("non_answer_no_anchored_label"),
    nonAnswerOutputRate: rate(outcomeCount("non_answer_no_anchored_label"), denominator),
    invalidOptionLabelCount: scored.filter((row) => row.invalidOptionLabelStatus).length,
    truncatedOutputCount: scored.filter((row) => row.truncatedOutput).length,
    invalidOptionLabelsObserved: invalidLabels,
  };
}

// The frozen scoreView block english-core-snapshot-binding.mjs reads. It names
// the exact contract bytes and the exact parser bytes that produced the split,
// so a later analysis can prove which checkout produced this artifact.
function scoreViewContract({
  taskFileSha256,
  taskManifestSha256,
  sourceResultSha256,
  sourceRunId,
}) {
  const contractPath = path.join(here, SCORE_VIEW_CONTRACT_FILE);
  const parserPath = path.join(here, "english-core-choice-parser.mjs");
  return {
    parseViewContractVersion: SCORE_VIEW_CONTRACT_VERSION,
    denominatorPolicyVersion: SCORE_VIEW_DENOMINATOR_POLICY,
    allowedLabelContractVersion: SCORE_VIEW_ALLOWED_LABEL_CONTRACT,
    selected: PRIMARY_SCREENING_SCORE_VIEW,
    primaryScreeningView: PRIMARY_SCREENING_SCORE_VIEW,
    metricKeys: { ...SCORE_VIEW_METRIC_KEYS },
    [STRICT_SCORE_VIEW]: {
      name: STRICT_SCORE_VIEW,
      metric: SCORE_VIEW_METRIC_KEYS[STRICT_SCORE_VIEW],
      metricKey: SCORE_VIEW_METRIC_KEYS[STRICT_SCORE_VIEW],
    },
    [PRIMARY_SCREENING_SCORE_VIEW]: {
      name: PRIMARY_SCREENING_SCORE_VIEW,
      metric: SCORE_VIEW_METRIC_KEYS[PRIMARY_SCREENING_SCORE_VIEW],
      metricKey: SCORE_VIEW_METRIC_KEYS[PRIMARY_SCREENING_SCORE_VIEW],
    },
    contractFile: SCORE_VIEW_CONTRACT_FILE,
    contractSha256: sha256Text(fs.readFileSync(contractPath)),
    parserFile: path.basename(parserPath),
    parserSha256: sha256Text(fs.readFileSync(parserPath)),
    taskFileSha256,
    taskManifestSha256,
    sourceResultSha256,
    sourceRunId,
  };
}

const runtimeQualification = runRuntimeQualification(run);
const detail = [];
for (const task of tasks) {
  const meta = answers[task.id];
  if (!meta) throw new Error(`Missing choice-order answer metadata for ${task.id}`);
  const got = outputs.get(task.id);
  const views = scoreChoiceViews(got?.output ?? "", {
    allowedChoices: task.allowedChoices,
    baseIndexByLetter: meta.baseIndexByLetter,
    goldBaseChoiceIndex: meta.goldBaseChoiceIndex,
    runtimeUnqualified: !runtimeQualification.runtimeQualified,
    missing: !got,
    finishReason: got?.finishReason ?? null,
    truncated: got?.truncated ?? false,
  });
  const parsedLetter = views.recoverableParsedChoice;
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
    // Issue #64: both views of one parse, published side by side and never merged.
    choiceViews: views,
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
// Issue #64 strict/recoverable views over the whole forced-choice lane and per
// dimension, on the frozen fixed denominator.
const choiceViewsByDimension = Object.fromEntries(
  dimensions.map((d) => [d, summarizeChoiceViews(detail.filter((x) => x.dimension === d).map((x) => x.choiceViews))]),
);
const choiceViews = summarizeChoiceViews(detail.map((x) => x.choiceViews));
const manifestSha256 = sha256Text(manifestText);
const scoreView = scoreViewContract({
  taskFileSha256: canonicalTaskSha256,
  taskManifestSha256: manifestSha256,
  sourceResultSha256: sha256Text(fs.readFileSync(resultPath)),
  sourceRunId: run.runId ?? null,
});

const report = {
  version: 3,
  schemaVersion: 1,
  artifactType: "pari.english-core.choice-order-score",
  inputResultSchema: resultValidation.schemaValidation,
  runId: run.runId ?? null,
  model: run.model ?? null,
  taskFileSha256: run.taskFileSha256 ?? null,
  taskCount: run.taskCount ?? null,
  benchmarkInputs: {
    choiceOrderTaskSha256: canonicalTaskSha256,
    choiceOrderAnswerSha256: sha256Text(answerText),
    choiceOrderManifestSha256: manifestSha256,
  },
  // Issue #64: the frozen strict/recoverable forced-choice identity and
  // provenance block, consumed by english-core-snapshot-binding.mjs. The
  // policy itself lives in english_core_choice_views.py and is restated, never
  // redefined, here.
  scoreView,
  scoreViewsSeparated: true,
  runtimeQualification,
  choiceViews,
  choiceViewsByDimension,
  // The pre-#64 forced-choice fields were computed from the anchored
  // recoverable parse. Each one now names the view it actually measures
  // instead of silently standing in for strict letter-only accuracy.
  legacyScoreViewAliases: {
    "presentation0AccuracyInvalidAsWrong": PRIMARY_SCREENING_SCORE_VIEW,
    "presentation1AccuracyInvalidAsWrong": PRIMARY_SCREENING_SCORE_VIEW,
    "averagePresentationAccuracyInvalidAsWrong": PRIMARY_SCREENING_SCORE_VIEW,
    "bothOrdersCorrectRate": PRIMARY_SCREENING_SCORE_VIEW,
    "bothOrdersCorrectRateAmongFullyValidPairs": PRIMARY_SCREENING_SCORE_VIEW,
    "atLeastOneOrderCorrectRateAmongFullyValidPairs": PRIMARY_SCREENING_SCORE_VIEW,
    "semanticAnswerConsistencyRateAmongFullyValidPairs": PRIMARY_SCREENING_SCORE_VIEW,
    "oneCorrectOneWrongRateAmongFullyValidPairs": PRIMARY_SCREENING_SCORE_VIEW,
    "overall.validOutputCoverage": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].correct": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].predictedLetter": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].parsedLetter": PRIMARY_SCREENING_SCORE_VIEW,
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
    "choiceViews publishes the strict and recoverable_anchored views of the same forced-choice parses over one fixed denominator. Every key named in legacyScoreViewAliases is a recoverable_anchored measurement, not strict letter-only accuracy; read strictAccuracyFixedDenominator for protocol compliance.",
    "The scorer is bound to exact task/answer/manifest bytes and rejects duplicate or extra run-output IDs.",
    "A substantial order effect or poor fullyValidPairRate weakens claims from single-order prompted forced-choice scores and should be reported rather than averaged away."
  ],
  researchBasis: [
    "Wei et al., Findings ACL 2024, Unveiling Selection Biases: Exploring Order and Token Sensitivity in Large Language Models",
    "Alzahrani et al., ACL 2024, benchmark perturbation and answer-order sensitivity"
  ]
};

console.log(JSON.stringify(report, null, 2));
