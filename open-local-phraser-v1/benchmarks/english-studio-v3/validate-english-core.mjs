#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const errors = [];
const warnings = [];

function readJson(name) {
  const file = path.join(here, name);
  if (!fs.existsSync(file)) {
    errors.push(`missing required JSON file: ${name}`);
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    errors.push(`invalid JSON ${name}: ${error.message}`);
    return null;
  }
}

function checkFile(name, label) {
  if (!name) {
    errors.push(`missing file reference for ${label}`);
    return;
  }
  if (!fs.existsSync(path.join(here, name))) {
    errors.push(`config references missing ${label}: ${name}`);
  }
}

const config = readJson("english-core-config.json");
const seed = readJson("english-core-shadow.seed.json");
const anchors = readJson("english-core-public-anchors.json");
const resultSchema = readJson("english-core-result-schema.json");
const metricContract = readJson("english-core-generative-metric-contract.json");
const compatibilitySources = readJson("english-core-sources.json");

if (config) {
  if (Number(config.version) < 7) errors.push(`english-core-config.json version ${config.version} is older than required v7`);

  const weights = config.composite?.weights ?? {};
  const total = Object.values(weights).reduce((a, b) => a + Number(b), 0);
  if (total !== 100) errors.push(`composite weights sum to ${total}, expected 100`);

  const dimensions = Object.keys(config.dimensions ?? {});
  if (!dimensions.length) errors.push("config defines no dimensions");

  for (const dimension of dimensions) {
    const dimWeight = config.dimensions[dimension]?.weight;
    const compositeWeight = weights[dimension];
    if (typeof compositeWeight !== "number") errors.push(`dimension ${dimension} missing from composite weights`);
    if (dimWeight !== compositeWeight) errors.push(`weight mismatch for ${dimension}: dimension=${dimWeight}, composite=${compositeWeight}`);
    if (!config.dimensions[dimension]?.researchConstruct) errors.push(`dimension ${dimension} missing researchConstruct`);
    if (!(config.dimensions[dimension]?.publicAnchors?.length > 0)) warnings.push(`dimension ${dimension} has no publicAnchors`);
  }

  for (const dimension of Object.keys(weights)) {
    if (!config.dimensions?.[dimension]) errors.push(`composite weight references unknown dimension ${dimension}`);
  }

  for (const [label, name] of Object.entries(config.files ?? {})) checkFile(name, label);

  for (const requiredFileKey of [
    "runValidator",
    "packageValidator",
    "selfCheck",
    "reproManifestBuilder",
    "uncertaintyAnalyzer",
    "pairedComparator",
    "choiceOrderRobustnessBuilder",
    "choiceOrderRobustnessScorer",
    "generativeMetricContract",
    "swordsOfficialEvaluatorRunner",
    "jflegOfficialEvaluatorRunner"
  ]) {
    if (!config.files?.[requiredFileKey]) errors.push(`config.files missing required key: ${requiredFileKey}`);
  }

  for (const requiredRule of [
    "sourceRevisionPinning",
    "shadowAudit",
    "forcedChoice",
    "choiceOrderRobustness",
    "choiceParser",
    "nativeProtocolSeparation",
    "metricDirectionContract",
    "multiPrompt",
    "uncertainty",
    "pairedComparison",
    "distributionValidity",
    "promotionValidation",
    "reproducibility"
  ]) {
    if (!config.evaluationProtocol?.[requiredRule]) errors.push(`evaluationProtocol missing required rule: ${requiredRule}`);
  }

  if (!String(config.evaluationProtocol?.pairedComparison ?? "").includes("hierarchical")) {
    errors.push("evaluationProtocol.pairedComparison must preserve the v7 paired phenomenon/item hierarchical sensitivity rule");
  }
  if (!config.researchBasis?.externalEvaluatorBasis) {
    errors.push("researchBasis.externalEvaluatorBasis missing; official evaluator provenance must be documented");
  }

  for (const lane of [
    "publicNative",
    "publicPromptedFull",
    "publicPromptedFast",
    "freshShadow",
    "robustnessDiagnostics"
  ]) {
    if (!config.evidenceLanes?.[lane]) errors.push(`evidenceLanes missing ${lane}`);
  }
}

if (metricContract) {
  const directions = new Set(["higher_is_better", "lower_is_better"]);
  for (const [name, definition] of Object.entries(metricContract.metrics ?? {})) {
    if (!directions.has(definition.direction)) errors.push(`metric ${name} has invalid direction ${definition.direction}`);
    if (!definition.construct) errors.push(`metric ${name} missing construct definition`);
  }
  if (!Object.keys(metricContract.metrics ?? {}).length) errors.push("generative metric contract has no metrics");
}

let shadowCounts = {};
if (seed && config) {
  if (!Array.isArray(seed.cases) || seed.cases.length === 0) errors.push("shadow seed has no cases");
  if (!seed.validationStatus) errors.push("shadow seed missing validationStatus");
  if (seed.validationStatus !== "author_labeled_unvalidated") {
    warnings.push(`shadow validationStatus is ${seed.validationStatus}; verify independent annotation evidence before allowing a stronger status`);
  }

  const ids = new Set();
  const counts = {};
  for (const row of seed.cases ?? []) {
    if (!row.id) errors.push("shadow row missing id");
    else if (ids.has(row.id)) errors.push(`duplicate shadow id: ${row.id}`);
    else ids.add(row.id);

    if (!config.dimensions?.[row.dimension]) errors.push(`${row.id}: unknown dimension ${row.dimension}`);
    counts[row.dimension] = (counts[row.dimension] ?? 0) + 1;

    if (row.dimension === "generative_expression") {
      if (!Array.isArray(row.scoring) || row.scoring.length === 0) {
        errors.push(`${row.id}: generative case missing scoring metrics`);
      } else if (metricContract) {
        for (const metric of row.scoring) {
          if (!metricContract.metrics?.[metric]) errors.push(`${row.id}: unregistered generative metric ${metric}`);
        }
      }
    }
  }
  shadowCounts = counts;

  for (const dimension of Object.keys(config.dimensions ?? {})) {
    if (!counts[dimension]) errors.push(`shadow seed has no cases for dimension ${dimension}`);
  }

  const configuredGenerative = new Set(config.dimensions?.generative_expression?.metrics ?? []);
  for (const row of seed.cases ?? []) {
    if (row.dimension !== "generative_expression") continue;
    for (const metric of row.scoring ?? []) {
      if (!configuredGenerative.has(metric)) {
        errors.push(`${row.id}: required metric ${metric} is used by seed but absent from config generative_expression.metrics`);
      }
    }
  }
}

if (anchors && config) {
  if (!Array.isArray(anchors.anchors) || anchors.anchors.length === 0) errors.push("public anchor registry has no anchors");
  const ids = new Set();
  for (const anchor of anchors.anchors ?? []) {
    if (!anchor.id) errors.push("public anchor missing id");
    else if (ids.has(anchor.id)) errors.push(`duplicate public anchor id: ${anchor.id}`);
    else ids.add(anchor.id);
    if (!config.dimensions?.[anchor.dimension]) errors.push(`${anchor.id}: unknown anchor dimension ${anchor.dimension}`);
    if (!anchor.reference) errors.push(`${anchor.id}: missing research reference`);
    if (!anchor.role) errors.push(`${anchor.id}: missing role/construct explanation`);
    if (!anchor.evidencePriority) warnings.push(`${anchor.id}: missing evidencePriority`);
    if (!anchor.implementationStatus) warnings.push(`${anchor.id}: missing implementationStatus`);
    if (!(anchor.preferredMetrics?.length > 0)) warnings.push(`${anchor.id}: missing preferredMetrics`);
    if (!anchor.nativeProtocol && anchor.evidencePriority !== "secondary") warnings.push(`${anchor.id}: primary/supporting anchor lacks nativeProtocol description`);
    for (const file of anchor.pariFiles ?? []) {
      if (!fs.existsSync(path.join(here, file))) errors.push(`${anchor.id}: pariFiles references missing file ${file}`);
    }
  }
}

if (compatibilitySources) {
  if (compatibilitySources.canonicalRegistry !== "english-core-public-anchors.json") {
    errors.push("english-core-sources.json must identify english-core-public-anchors.json as canonicalRegistry");
  }
  if (compatibilitySources.status !== "compatibility_registry") {
    warnings.push("english-core-sources.json is not labeled compatibility_registry; avoid maintaining two competing canonical source registries");
  }
}

if (resultSchema) {
  const provenance = resultSchema.properties?.outputs?.items?.properties?.metricProvenance;
  const provenanceKind = provenance?.properties?.kind?.enum ?? [];
  const provenanceRequired = new Set(provenance?.required ?? []);
  if (!provenanceKind.includes("official_benchmark_metric")) errors.push("result schema metricProvenance must support official_benchmark_metric");
  if (!provenanceKind.includes("blinded_human")) errors.push("result schema metricProvenance must support blinded_human");
  if (!provenanceRequired.has("protocol")) errors.push("result schema metricProvenance must require protocol/normalization description");

  const decoding = resultSchema.properties?.decoding?.properties ?? {};
  for (const field of ["temperature", "topP", "topK", "maxNewTokens", "forcedChoiceMaxNewTokens", "seed"]) {
    if (!decoding[field]) errors.push(`result schema must preserve decoding.${field}`);
  }

  const taskCount = resultSchema.properties?.taskCount;
  if (!taskCount) errors.push("result schema must preserve taskCount");
  else if (Number(taskCount.minimum) < 1) errors.push("result schema taskCount.minimum must be >= 1");

  const outputsSchema = resultSchema.properties?.outputs;
  if (!outputsSchema) errors.push("result schema must preserve outputs");
  else if (Number(outputsSchema.minItems) < 1) errors.push("result schema outputs.minItems must be >= 1");

  const modelProps = resultSchema.properties?.model?.properties ?? {};
  for (const field of ["artifactSha256", "tokenizerName", "chatTemplateSha256", "checkpointType", "quantization", "revision"]) {
    if (!modelProps[field]) errors.push(`result schema model must preserve ${field}`);
  }
  const artifactTypes = Array.isArray(modelProps.artifactSha256?.type)
    ? modelProps.artifactSha256.type
    : [modelProps.artifactSha256?.type].filter(Boolean);
  if (!artifactTypes.includes("string") || !artifactTypes.includes("null")) {
    errors.push("result schema model.artifactSha256 must allow string for pinned runs and null for exploratory runs");
  }
}

for (const requiredDoc of [
  "ENGLISH_CORE.md",
  "ENGLISH_CORE_RUN.md",
  "ENGLISH_CORE_RESEARCH_BASIS.md",
  "ENGLISH_CORE_ROBUSTNESS.md",
  "ENGLISH_CORE_HUMAN_EVAL.md",
  "ENGLISH_CORE_NATIVE_PROTOCOLS.md",
  "RESEARCH_GROUNDING_POLICY.md"
]) {
  if (!fs.existsSync(path.join(here, requiredDoc))) errors.push(`missing governance/research document: ${requiredDoc}`);
}

for (const requiredImplementation of [
  "english-core-choice-parser.mjs",
  "english_core_choice_parser.py",
  "test-english-core-choice-parser.mjs",
  "test_english_core_choice_parser.py",
  "english-core-generative-metric-contract.json",
  "run-english-core-mlx.py",
  "validate-english-core-run.py",
  "build-english-core-repro-manifest.py",
  "build-english-core.mjs",
  "score-english-core.mjs",
  "build-english-core-prompt-robustness.mjs",
  "score-english-core-prompt-robustness.mjs",
  "build-english-core-choice-order-robustness.mjs",
  "score-english-core-choice-order-robustness.mjs",
  "analyze-english-core-statistics.mjs",
  "compare-english-core-models.mjs",
  "build-english-core-public-fast.py",
  "score-english-core-public-fast.py",
  "build-english-core-public-full-classification.py",
  "score-english-core-public-full-classification.py",
  "build-swords-english-core-prompts.py",
  "convert-swords-english-core-output.py",
  "run-swords-official-eval.py",
  "build-jfleg-english-core-prompts.py",
  "convert-jfleg-english-core-output.py",
  "run-jfleg-official-eval.py",
  "self-check-english-core.sh"
]) {
  if (!fs.existsSync(path.join(here, requiredImplementation))) errors.push(`missing required implementation file: ${requiredImplementation}`);
}

const report = {
  version: 7,
  configVersion: config?.version ?? null,
  seedVersion: seed?.version ?? null,
  metricContractVersion: metricContract?.version ?? null,
  shadowValidationStatus: seed?.validationStatus ?? null,
  shadowCases: seed?.cases?.length ?? null,
  shadowCasesByDimension: shadowCounts,
  dimensions: Object.keys(config?.dimensions ?? {}),
  publicAnchors: anchors?.anchors?.length ?? null,
  registeredGenerativeMetrics: Object.keys(metricContract?.metrics ?? {}).length,
  errors,
  warnings,
  status: errors.length ? "fail" : warnings.length ? "pass_with_warnings" : "pass",
  interpretation: [
    "This validates benchmark package consistency, not linguistic validity.",
    "A passing package validator does not upgrade author-written shadow labels to independent human gold.",
    "Per-dimension case counts are reported rather than judged against an invented universal adequacy threshold; evidence strength is assessed through construct coverage, uncertainty, external anchors, and claim tiers.",
    "Generative metric registration/direction checks prevent accidental inversion but do not validate the evaluator itself.",
    "Registered public-anchor adapter/evaluator files are checked for existence so protocol documentation cannot silently point at missing tooling.",
    "Choice-parser regression tests and task-builder leakage checks are separate executable checks run by self-check-english-core.sh.",
    "Public data/evaluator revision and fingerprint requirements are enforced at promotion-run/workflow level; package validation alone cannot prove that a future external checkout used immutable source bytes.",
    "The v7 paired-comparison contract requires both item-level paired bootstrap and phenomenon/item hierarchical sensitivity for close-model robustness claims.",
    "Run audit-english-core-shadow.mjs separately for item-level structural/distribution diagnostics.",
    "Research-level claims still require the claim-tier gates in ENGLISH_CORE_ROBUSTNESS.md."
  ]
};

console.log(JSON.stringify(report, null, 2));
if (errors.length) process.exitCode = 1;
