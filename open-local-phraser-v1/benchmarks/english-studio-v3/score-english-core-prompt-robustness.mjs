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
  console.error("Usage: node score-english-core-prompt-robustness.mjs <result.json>");
  process.exit(2);
}
const resultValidation = validateEnglishCoreResult(resultPath, {
  promotion: process.argv.includes("--promotion"),
  compatLegacyV0: process.argv.includes("--compat-legacy-v0"),
});

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

// One parse of the preserved raw output feeds both views. The gold label is
// only compared after the fact, so a correct recoverable answer can never
// mutate strict correctness.
function scoreChoiceViews(rawOutput, { allowedChoices, gold, runtimeUnqualified, missing, finishReason, truncated }) {
  const parse = parseChoice(rawOutput, allowedChoices);
  const strictParsedChoice = STRICT_ALLOWED_STATUSES.has(parse.status) ? parse.letter : null;
  const recoverableParsedChoice = RECOVERABLE_ALLOWED_STATUSES.has(parse.status) ? parse.letter : null;
  const strictProtocolValid = strictParsedChoice !== null;
  const recoverableProtocolValid = recoverableParsedChoice !== null;

  let strictCorrect = null;
  let recoverableCorrect = null;
  if (gold !== null && gold !== undefined && !runtimeUnqualified) {
    strictCorrect = strictProtocolValid && strictParsedChoice === gold;
    recoverableCorrect = recoverableProtocolValid && recoverableParsedChoice === gold;
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
    goldLabelForComparison: gold ?? null,
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

const forced = tasks.filter((x) => !x.generative);
const runtimeQualification = runRuntimeQualification(run);
const detail = [];
for (const task of forced) {
  const row = byBase.get(task.baseId);
  if (!row) throw new Error(`Prompt-robustness task ${task.id} references unknown baseId ${task.baseId}`);
  const expected = expectedLetter(row);
  if (!expected) throw new Error(`Cannot derive gold answer for ${task.id}`);
  const got = outputs.get(task.id);
  const views = scoreChoiceViews(got?.output ?? "", {
    allowedChoices: task.allowedChoices,
    gold: expected,
    runtimeUnqualified: !runtimeQualification.runtimeQualified,
    missing: !got,
    finishReason: got?.finishReason ?? null,
    truncated: got?.truncated ?? false,
  });
  const parsed = views.recoverableParsedChoice;
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
    status: !got ? "missing" : (predicted ? "scored" : "invalid_output"),
    // Issue #64: both views of one parse, published side by side and never merged.
    choiceViews: views,
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

// Issue #64 strict/recoverable views over the whole forced-choice lane and per
// dimension, on the frozen fixed denominator.
const choiceViewsByDimension = {};
for (const dim of [...new Set(detail.map((x) => x.dimension))]) {
  choiceViewsByDimension[dim] = summarizeChoiceViews(detail.filter((x) => x.dimension === dim).map((x) => x.choiceViews));
}
const choiceViews = summarizeChoiceViews(detail.map((x) => x.choiceViews));
const manifestSha256 = sha256Text(manifestText);
const scoreView = scoreViewContract({
  taskFileSha256: canonicalTaskSha256,
  taskManifestSha256: manifestSha256,
  sourceResultSha256: sha256Text(fs.readFileSync(resultPath)),
  sourceRunId: run.runId ?? null,
});

const report = {
  version: 4,
  schemaVersion: 1,
  artifactType: "pari.english-core.prompt-robustness-score",
  inputResultSchema: resultValidation.schemaValidation,
  model: run.model ?? null,
  runId: run.runId ?? null,
  taskFileSha256: run.taskFileSha256 ?? null,
  taskCount: run.taskCount ?? null,
  benchmarkInputs: {
    shadowSeedSha256: sha256Text(seedText),
    promptRobustnessTaskSha256: canonicalTaskSha256,
    promptRobustnessManifestSha256: manifestSha256,
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
    "meanPromptAccuracyInvalidAsWrong": PRIMARY_SCREENING_SCORE_VIEW,
    "worstPromptAccuracyInvalidAsWrong": PRIMARY_SCREENING_SCORE_VIEW,
    "bestPromptAccuracyInvalidAsWrong": PRIMARY_SCREENING_SCORE_VIEW,
    "promptAccuracySpread": PRIMARY_SCREENING_SCORE_VIEW,
    "allPromptsCorrectRate": PRIMARY_SCREENING_SCORE_VIEW,
    "majorityPromptCorrectRate": PRIMARY_SCREENING_SCORE_VIEW,
    "semanticAnswerConsistencyRateAllItems": PRIMARY_SCREENING_SCORE_VIEW,
    "semanticAnswerConsistencyRateAmongFullyValidItems": PRIMARY_SCREENING_SCORE_VIEW,
    "variantAccuracyInvalidAsWrong": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].correct": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].predicted": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].parsedLetter": PRIMARY_SCREENING_SCORE_VIEW,
    "forcedChoice.validOutputCoverage": PRIMARY_SCREENING_SCORE_VIEW,
  },
  forcedChoice: summarize(detail),
  byDimension,
  generativeTaskInstancesPresent: tasks.filter((x) => x.generative).length,
  generativeNote: "Generative prompt sensitivity must be analyzed with the same independently validated metric/human protocol across variants; this scorer intentionally does not invent an automatic generative quality score.",
  interpretation: {
    primary: ["meanPromptAccuracyInvalidAsWrong", "worstPromptAccuracyInvalidAsWrong", "allPromptsCorrectRate", "semanticAnswerConsistencyRateAllItems", "validOutputCoverage"],
    parserPolicy: "Only unambiguous choice forms are accepted, and a parsed letter outside the actual option range is invalid. Formatting wrappers such as 'The answer is A' are recovered; free-form/inferred choices remain invalid.",
    coveragePolicy: "Invalid/missing responses count as wrong in robustness accuracy and are separately exposed through valid-output coverage. Semantic consistency is reported both over all base items and conditionally among items whose three outputs were all valid.",
    scoreViewPolicy: "choiceViews publishes the strict and recoverable_anchored views of the same forced-choice parses over one fixed denominator. Every key named in legacyScoreViewAliases is a recoverable_anchored measurement, not strict letter-only accuracy; read strictAccuracyFixedDenominator for protocol compliance.",
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
