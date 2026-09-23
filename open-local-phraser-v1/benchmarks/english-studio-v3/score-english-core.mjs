#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseChoiceLetter } from "./english-core-choice-parser.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const resultPath = process.argv[2];
if (!resultPath) {
  console.error("Usage: node score-english-core.mjs <result.json>");
  process.exit(2);
}

const config = JSON.parse(fs.readFileSync(path.join(here, "english-core-config.json"), "utf8"));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const metricContract = JSON.parse(fs.readFileSync(path.join(here, "english-core-generative-metric-contract.json"), "utf8"));
const run = JSON.parse(fs.readFileSync(resultPath, "utf8"));
const outputs = new Map((run.outputs ?? []).map((x) => [x.id, x]));
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

function expectedLetter(row) {
  const baseIndex = baseChoiceIndex(row);
  if (baseIndex < 0) return null;
  let choiceCount;
  switch (row.task) {
    case "same_sense":
    case "same_meaning":
    case "relation_preservation":
    case "acceptability_pair": choiceCount = 2; break;
    default: choiceCount = row.choices?.length ?? -1;
  }
  if (choiceCount < 1) return null;
  const order = permutation(choiceCount, row.id);
  const permutedIndex = order.indexOf(baseIndex);
  return permutedIndex >= 0 ? letters[permutedIndex] : null;
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

const detail = [];
for (const row of seed.cases) {
  const got = outputs.get(row.id);
  if (!got) {
    detail.push({ id: row.id, dimension: row.dimension, task: row.task, phenomenon: row.phenomenon ?? null, status: "missing", score: null });
    continue;
  }

  if (row.dimension === "generative_expression") {
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
    });
    continue;
  }

  const expected = expectedLetter(row);
  if (!expected) throw new Error(`Cannot derive permuted gold answer for ${row.id}`);
  const predicted = parseChoiceLetter(got.output);
  detail.push({
    id: row.id,
    dimension: row.dimension,
    task: row.task,
    phenomenon: row.phenomenon ?? null,
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
const report = {
  version: 6,
  runId: run.runId ?? null,
  model: run.model ?? null,
  shadowCases: seed.cases.length,
  generativeMetricContractVersion: metricContract.version ?? null,
  dimensionScores,
  englishCoreShadow100: complete ? Number(englishCore100.toFixed(3)) : null,
  equalWeightDimensionMean100: typeof equalWeightMean100 === "number" ? Number(equalWeightMean100.toFixed(3)) : null,
  weightSensitivityDelta: complete && typeof equalWeightMean100 === "number"
    ? Number((englishCore100 - equalWeightMean100).toFixed(3))
    : null,
  complete,
  notes: [
    "This scorer covers the fresh Pari shadow set only; public-anchor benchmark results must be reported separately.",
    "Forced-choice option positions are deterministically permuted per case ID to reduce answer-position artifacts.",
    "The shared choice parser accepts only unambiguous forms such as A, A., Answer: A, The answer is A, or Option A; free-form prose and inferred choices remain invalid.",
    "Forced-choice cases are deterministically scored from the private seed answer key.",
    "Generative metricScores are normalized observations in [0,1], not assumed utilities. Directionality comes from english-core-generative-metric-contract.json; lower-is-better criteria are inverted before aggregation.",
    "Generative cases require complete registered metricScores plus structured approved metricProvenance including the normalization/scoring protocol.",
    "General-purpose LLM judges are secondary diagnostics and cannot by themselves enter the official generative composite; validated specialist models require an explicit human-validation reference.",
    "The product-weighted composite is a Pari product prior, not a literature-derived psychometric scale; compare it with the equal-weight dimension mean and all seven subscores.",
    "Run analyze-english-core-statistics.mjs for uncertainty and compare-english-core-models.mjs for paired model comparison.",
    "Runtime, RAM and quantization do not affect English Core competence evidence."
  ],
  detail,
};

console.log(JSON.stringify(report, null, 2));
