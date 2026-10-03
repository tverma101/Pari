#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CHOICE_STATUS, allowedChoicesFromTask, parseChoice } from "./english-core-choice-parser.mjs";
import { validateEnglishCoreResult } from "./english-core-result-contract.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultPath = process.argv[2];
if (!resultPath) {
  console.error("Usage: node score-english-core.mjs <result.json>");
  process.exit(2);
}
const resultValidation = validateEnglishCoreResult(resultPath, {
  promotion: process.argv.includes("--promotion"),
  compatLegacyV0: process.argv.includes("--compat-legacy-v0"),
});

function readText(name) {
  return fs.readFileSync(path.join(here, name), "utf8");
}
function sha256Text(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

const configText = readText("english-core-config.json");
const seedText = readText("english-core-shadow.seed.json");
const metricContractText = readText("english-core-generative-metric-contract.json");
const taskText = readText("english-core-shadow.jsonl");
const manifestText = readText("english-core-shadow.manifest.json");
const config = JSON.parse(configText);
const seed = JSON.parse(seedText);
const metricContract = JSON.parse(metricContractText);
const shadowManifest = JSON.parse(manifestText);
const taskRows = taskText.split("\n").filter(Boolean).map(JSON.parse);
const taskById = new Map(taskRows.map((row) => [row.id, row]));
const run = JSON.parse(fs.readFileSync(resultPath, "utf8"));
const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

const seedIds = seed.cases.map((row) => row.id);
const taskIds = taskRows.map((row) => row.id);
if (new Set(seedIds).size !== seedIds.length) throw new Error("Shadow seed contains duplicate IDs");
if (new Set(taskIds).size !== taskIds.length) throw new Error("Generated shadow task file contains duplicate IDs");
if (seedIds.length !== taskIds.length || seedIds.some((id, i) => id !== taskIds[i])) {
  throw new Error("Generated english-core-shadow.jsonl is stale or does not match the current seed; rebuild it before scoring");
}
if (Number(shadowManifest.cases) !== taskRows.length) {
  throw new Error("Shadow manifest case count does not match english-core-shadow.jsonl");
}
const canonicalTaskSha256 = sha256Text(taskText);
if (run.taskFileSha256 !== canonicalTaskSha256) {
  throw new Error("Result taskFileSha256 does not match the current english-core-shadow.jsonl; refusing cross-suite scoring");
}
if (Number(run.taskCount) !== taskRows.length) {
  throw new Error(`Result taskCount ${run.taskCount} does not match shadow task count ${taskRows.length}`);
}

const outputRows = run.outputs ?? [];
if (!Array.isArray(outputRows)) throw new Error("Result outputs must be an array");
const outputIds = outputRows.map((row) => row?.id);
if (outputIds.some((id) => !id)) throw new Error("Result contains an output without an ID");
if (new Set(outputIds).size !== outputIds.length) throw new Error("Result contains duplicate output IDs");
const extraOutputIds = outputIds.filter((id) => !new Set(seedIds).has(id));
if (extraOutputIds.length) {
  throw new Error(`Result contains ${extraOutputIds.length} output IDs not present in the shadow suite`);
}
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

function choiceCount(row) {
  switch (row.task) {
    case "same_sense":
    case "same_meaning":
    case "relation_preservation":
    case "acceptability_pair": return 2;
    case "best_substitute":
    case "minimal_pair":
    case "relation_label":
    case "closer_register":
    case "closer_meaning_and_register":
    case "more_natural":
    case "sentence_order": return row.choices?.length ?? -1;
    default: return -1;
  }
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

function expectedLetter(row) {
  const baseIndex = baseChoiceIndex(row);
  const count = choiceCount(row);
  if (baseIndex < 0 || count < 1 || baseIndex >= count) return null;
  const order = permutation(count, row.id);
  const permutedIndex = order.indexOf(baseIndex);
  return permutedIndex >= 0 ? letters[permutedIndex] : null;
}

function validDisplayedChoice(row, parsedLetter) {
  if (!parsedLetter) return null;
  const count = choiceCount(row);
  const index = letters.indexOf(parsedLetter);
  return count > 0 && index >= 0 && index < count ? parsedLetter : null;
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
const STRICT_ALLOWED_STATUSES = new Set([
  CHOICE_STATUS.STRICT_ALLOWED,
]);
const RECOVERABLE_ALLOWED_STATUSES = new Set([
  CHOICE_STATUS.STRICT_ALLOWED,
  CHOICE_STATUS.RECOVERABLE_ALLOWED,
]);
const TRUNCATION_FINISH_REASONS = new Set(["length", "max_tokens", "token_limit", "max_new_tokens"]);
const RUNTIME_UNQUALIFIED_STATUSES = new Set([
  "runtime_unqualified", "failed", "incomplete", "error", "crashed", "aborted", "timeout",
]);

// Mirrors english_core_choice_views.run_runtime_qualification: infrastructure
// state is surfaced instead of being counted as English zeros.
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

function mean(values) {
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function approvedMetricProvenance(provenance) {
  if (!provenance || typeof provenance !== "object") return { approved: false, reason: "missing_metricProvenance" };
  if (provenance.candidateSelfGrade !== false) return { approved: false, reason: "candidate_self_grade_or_unspecified" };
  if (!String(provenance.name ?? "").trim()) return { approved: false, reason: "missing_metric_name" };
  if (!String(provenance.protocol ?? "").trim()) return { approved: false, reason: "missing_metric_normalization_protocol" };

  const direct = new Set(["deterministic", "human_reference", "official_benchmark_metric", "blinded_human"]);
  if (direct.has(provenance.kind)) return { approved: true, reason: null };

  if (provenance.kind === "specialist_model") {
    if (provenance.validatedAgainstHumans === true && String(provenance.validationReference ?? "").trim()) {
      return { approved: true, reason: null };
    }
    return { approved: false, reason: "specialist_model_lacks_human_validation" };
  }

  if (provenance.kind === "general_llm_diagnostic") {
    return { approved: false, reason: "general_llm_judge_is_secondary_only" };
  }
  return { approved: false, reason: "unknown_metric_kind" };
}

function metricUtility(metricName, observedValue) {
  const definition = metricContract.metrics?.[metricName];
  if (!definition) return { ok: false, reason: "unregistered_metric", utility: null };
  if (typeof observedValue !== "number" || observedValue < 0 || observedValue > 1) {
    return { ok: false, reason: "metric_out_of_range", utility: null };
  }
  if (definition.direction === "higher_is_better") {
    return { ok: true, reason: null, utility: observedValue, direction: definition.direction };
  }
  if (definition.direction === "lower_is_better") {
    return { ok: true, reason: null, utility: 1 - observedValue, direction: definition.direction };
  }
  return { ok: false, reason: "unknown_metric_direction", utility: null };
}

const runtimeQualification = runRuntimeQualification(run);
const choiceViewRows = [];
const choiceViewsByDimension = {};
const detail = [];
for (const row of seed.cases) {
  const got = outputs.get(row.id);
  const isGenerative = row.dimension === "generative_expression";
  const forcedChoiceViewsApplicable = !isGenerative;
  const expected = isGenerative ? null : expectedLetter(row);
  if (forcedChoiceViewsApplicable && !expected) {
    throw new Error(`Cannot derive permuted gold answer for ${row.id}`);
  }
  const views = forcedChoiceViewsApplicable
    ? scoreChoiceViews(got?.output ?? "", {
      allowedChoices: allowedChoicesFromTask(taskById.get(row.id)),
      gold: expected,
      runtimeUnqualified: !runtimeQualification.runtimeQualified,
      missing: !got,
      finishReason: got?.finishReason ?? null,
      truncated: got?.truncated ?? false,
    })
    : null;
  if (views) {
    choiceViewRows.push(views);
    (choiceViewsByDimension[row.dimension] ??= []).push(views);
  }

  if (!got) {
    detail.push({
      id: row.id,
      dimension: row.dimension,
      task: row.task,
      phenomenon: row.phenomenon ?? null,
      status: "missing",
      score: null,
      forcedChoiceViewsApplicable,
      ...(views ? { choiceViews: views } : {}),
    });
    continue;
  }

  if (isGenerative) {
    const requiredMetrics = row.scoring ?? [];
    const scores = got.metricScores ?? {};
    const missing = requiredMetrics.filter((m) => typeof scores[m] !== "number");
    const contractIssues = [];
    const metricUtilities = {};
    const metricDirections = {};

    for (const metric of requiredMetrics) {
      if (typeof scores[metric] !== "number") continue;
      const converted = metricUtility(metric, scores[metric]);
      if (!converted.ok) contractIssues.push({ metric, issue: converted.reason });
      else {
        metricUtilities[metric] = converted.utility;
        metricDirections[metric] = converted.direction;
      }
    }

    const provenanceCheck = approvedMetricProvenance(got.metricProvenance);
    if (missing.length || contractIssues.length || !provenanceCheck.approved) {
      detail.push({
        id: row.id,
        dimension: row.dimension,
        task: row.task,
        phenomenon: row.phenomenon ?? null,
        status: "needs_external_scoring",
        missingMetrics: missing,
        metricContractIssues: contractIssues,
        provenanceIssue: provenanceCheck.approved ? null : provenanceCheck.reason,
        score: null,
        // A generative case has no forced-choice label, so it is not an item of
        // either strict/recoverable view and is never a view denominator unit.
        forcedChoiceViewsApplicable: false,
      });
      continue;
    }

    const score = mean(requiredMetrics.map((m) => metricUtilities[m]));
    detail.push({
      id: row.id,
      dimension: row.dimension,
      task: row.task,
      phenomenon: row.phenomenon ?? null,
      status: "scored",
      score,
      rawMetricScores: Object.fromEntries(requiredMetrics.map((m) => [m, scores[m]])),
      metricUtilities,
      metricDirections,
      metricProvenance: got.metricProvenance,
      forcedChoiceViewsApplicable: false,
    });
    continue;
  }

  const parsed = views.recoverableParsedChoice;
  const predicted = validDisplayedChoice(row, parsed);
  detail.push({
    id: row.id,
    dimension: row.dimension,
    task: row.task,
    phenomenon: row.phenomenon ?? null,
    status: predicted ? "scored" : "invalid_output",
    expected,
    parsedLetter: parsed,
    predicted,
    score: predicted ? Number(predicted === expected) : 0,
    // Issue #64: both views of one parse, published side by side and never merged.
    choiceViews: views,
    forcedChoiceViewsApplicable: true,
  });
}

const dimensionScores = {};
for (const dimension of Object.keys(config.dimensions)) {
  const rows = detail.filter((x) => x.dimension === dimension);
  const scored = rows.filter((x) => typeof x.score === "number");
  const byPhenomenon = {};
  for (const row of scored) {
    const key = row.phenomenon ?? "unspecified";
    if (!byPhenomenon[key]) byPhenomenon[key] = [];
    byPhenomenon[key].push(row.score);
  }
  dimensionScores[dimension] = {
    cases: rows.length,
    scored: scored.length,
    missing: rows.length - scored.length,
    complete: scored.length === rows.length,
    score100: scored.length === rows.length ? mean(scored.map((x) => x.score)) * 100 : null,
    byPhenomenon: Object.fromEntries(Object.entries(byPhenomenon).map(([k, xs]) => [k, {
      cases: xs.length,
      score100: Number((mean(xs) * 100).toFixed(3)),
    }]))
  };
}

let englishCore100 = 0;
let complete = true;
const completeDimensionValues = [];
for (const [dimension, weight] of Object.entries(config.composite.weights)) {
  const value = dimensionScores[dimension]?.score100;
  if (typeof value !== "number") {
    complete = false;
    continue;
  }
  completeDimensionValues.push(value);
  englishCore100 += value * (weight / 100);
}

const equalWeightMean100 = complete && completeDimensionValues.length ? mean(completeDimensionValues) : null;
const manifestSha256 = sha256Text(manifestText);
const choiceViews = summarizeChoiceViews(choiceViewRows);
const choiceViewsByDimensionSummary = Object.fromEntries(
  Object.keys(choiceViewsByDimension).map((dimension) => [dimension, summarizeChoiceViews(choiceViewsByDimension[dimension])]),
);
const scoreView = scoreViewContract({
  taskFileSha256: canonicalTaskSha256,
  taskManifestSha256: manifestSha256,
  sourceResultSha256: sha256Text(fs.readFileSync(resultPath)),
  sourceRunId: run.runId ?? null,
});
const report = {
  version: 9,
  schemaVersion: 1,
  artifactType: "pari.english-core.shadow-score",
  inputResultSchema: resultValidation.schemaValidation,
  runId: run.runId ?? null,
  model: run.model ?? null,
  taskFile: run.taskFile ?? null,
  taskFileSha256: run.taskFileSha256 ?? null,
  taskCount: run.taskCount ?? null,
  promptModeRequested: run.promptModeRequested ?? null,
  promptAdaptationModesObserved: run.promptAdaptationModesObserved ?? null,
  promptAdaptationDetailsObserved: run.promptAdaptationDetailsObserved ?? null,
  decoding: run.decoding ?? null,
  shadowCases: seed.cases.length,
  generativeMetricContractVersion: metricContract.version ?? null,
  benchmarkInputs: {
    configSha256: sha256Text(configText),
    shadowSeedSha256: sha256Text(seedText),
    shadowTaskSha256: canonicalTaskSha256,
    shadowManifestSha256: manifestSha256,
    generativeMetricContractSha256: sha256Text(metricContractText),
  },
  // Issue #64: the frozen strict/recoverable forced-choice identity and
  // provenance block, consumed by english-core-snapshot-binding.mjs. The
  // policy itself lives in english_core_choice_views.py and is restated, never
  // redefined, here.
  scoreView,
  scoreViewsSeparated: true,
  runtimeQualification,
  choiceViews,
  choiceViewsByDimension: choiceViewsByDimensionSummary,
  forcedChoiceViewCases: choiceViewRows.length,
  // The pre-#64 forced-choice fields were computed from the anchored
  // recoverable parse. They stay exactly as they were, and each one now names
  // the view it actually measures instead of silently standing in for strict
  // letter-only accuracy (the role of english_core_choice_views.
  // legacy_view_aliases on the Python lanes).
  legacyScoreViewAliases: {
    "detail[].predicted": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].parsedLetter": PRIMARY_SCREENING_SCORE_VIEW,
    "detail[].score": PRIMARY_SCREENING_SCORE_VIEW,
    "dimensionScores[].score100": PRIMARY_SCREENING_SCORE_VIEW,
  },
  dimensionScores,
  englishCoreShadow100: complete ? Number(englishCore100.toFixed(3)) : null,
  equalWeightDimensionMean100: typeof equalWeightMean100 === "number" ? Number(equalWeightMean100.toFixed(3)) : null,
  weightSensitivityDelta: complete && typeof equalWeightMean100 === "number"
    ? Number((englishCore100 - equalWeightMean100).toFixed(3))
    : null,
  complete,
  notes: [
    "This scorer covers the fresh Pari shadow set only; public-anchor benchmark results must be reported separately.",
    "The scorer is bound to the exact current english-core-shadow.jsonl bytes/count and rejects duplicate or extra output IDs before scoring.",
    "Forced-choice option positions are deterministically permuted per case ID to reduce answer-position artifacts.",
    "The shared choice parser accepts only unambiguous forms such as A, A., Answer: A, The answer is A, or Option A; a parsed letter outside the actual option range is an invalid output rather than a normal classification error.",
    "Forced-choice cases are deterministically scored from the private seed answer key.",
    "Generative metricScores are normalized observations in [0,1], not assumed utilities. Directionality comes from english-core-generative-metric-contract.json; lower-is-better criteria are inverted before aggregation.",
    "Generative cases require complete registered metricScores plus structured approved metricProvenance including the normalization/scoring protocol.",
    "General-purpose LLM judges are secondary diagnostics and cannot by themselves enter the official generative composite; validated specialist models require an explicit human-validation reference.",
    "Benchmark input hashes include the config, private seed, model-visible shadow task file, shadow manifest, and generative metric contract so paired/statistical tooling can reject incompatible benchmark states.",
    "The product-weighted composite is a Pari product prior, not a literature-derived psychometric scale; compare it with the equal-weight dimension mean and all seven subscores.",
    "Run validate-english-core-run.py before relying on a result's raw-output provenance, analyze-english-core-statistics.mjs for uncertainty, and compare-english-core-models.mjs for paired model comparison.",
    "Runtime, RAM and quantization do not affect English Core competence evidence."
  ],
  detail,
};

console.log(JSON.stringify(report, null, 2));
