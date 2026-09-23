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

if (config) {
  const weights = config.composite?.weights ?? {};
  const total = Object.values(weights).reduce((a, b) => a + Number(b), 0);
  if (total !== 100) errors.push(`composite weights sum to ${total}, expected 100`);

  const dimensions = Object.keys(config.dimensions ?? {});
  if (!dimensions.length) errors.push("config defines no dimensions");

  for (const dimension of dimensions) {
    const dimWeight = config.dimensions[dimension]?.weight;
    const compositeWeight = weights[dimension];
    if (typeof compositeWeight !== "number") {
      errors.push(`dimension ${dimension} missing from composite weights`);
    }
    if (dimWeight !== compositeWeight) {
      errors.push(`weight mismatch for ${dimension}: dimension=${dimWeight}, composite=${compositeWeight}`);
    }
    if (!config.dimensions[dimension]?.researchConstruct) {
      errors.push(`dimension ${dimension} missing researchConstruct`);
    }
    if (!(config.dimensions[dimension]?.publicAnchors?.length > 0)) {
      warnings.push(`dimension ${dimension} has no publicAnchors`);
    }
  }

  for (const dimension of Object.keys(weights)) {
    if (!config.dimensions?.[dimension]) errors.push(`composite weight references unknown dimension ${dimension}`);
  }

  for (const [label, name] of Object.entries(config.files ?? {})) checkFile(name, label);

  for (const requiredRule of [
    "shadowAudit",
    "nativeProtocolSeparation",
    "multiPrompt",
    "uncertainty",
    "pairedComparison",
    "distributionValidity",
    "reproducibility"
  ]) {
    if (!config.evaluationProtocol?.[requiredRule]) {
      errors.push(`evaluationProtocol missing required rule: ${requiredRule}`);
    }
  }

  if (!config.evidenceLanes?.publicNative || !config.evidenceLanes?.freshShadow) {
    errors.push("evidenceLanes must distinguish publicNative and freshShadow");
  }
}

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
  }

  for (const dimension of Object.keys(config.dimensions ?? {})) {
    if (!counts[dimension]) errors.push(`shadow seed has no cases for dimension ${dimension}`);
  }

  // The author-labeled shadow is deliberately not required to hit one arbitrary
  // sample-size threshold. Flag thin dimensions instead of inventing a universal
  // research constant.
  for (const [dimension, count] of Object.entries(counts)) {
    if (count < 6) warnings.push(`shadow dimension ${dimension} has only ${count} cases`);
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
    if (!(anchor.preferredMetrics?.length > 0)) warnings.push(`${anchor.id}: missing preferredMetrics`);
  }
}

if (resultSchema) {
  const provenanceKind = resultSchema.properties?.outputs?.items?.properties?.metricProvenance?.properties?.kind?.enum ?? [];
  if (!provenanceKind.includes("official_benchmark_metric")) {
    errors.push("result schema metricProvenance must support official_benchmark_metric");
  }
  if (!provenanceKind.includes("blinded_human")) {
    errors.push("result schema metricProvenance must support blinded_human");
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

const report = {
  version: 1,
  configVersion: config?.version ?? null,
  seedVersion: seed?.version ?? null,
  shadowValidationStatus: seed?.validationStatus ?? null,
  shadowCases: seed?.cases?.length ?? null,
  dimensions: Object.keys(config?.dimensions ?? {}),
  publicAnchors: anchors?.anchors?.length ?? null,
  errors,
  warnings,
  status: errors.length ? "fail" : warnings.length ? "pass_with_warnings" : "pass",
  interpretation: [
    "This validates benchmark package consistency, not linguistic validity.",
    "A passing package validator does not upgrade author-written shadow labels to independent human gold.",
    "Run audit-english-core-shadow.mjs separately for item-level structural/distribution diagnostics.",
    "Research-level claims still require the claim-tier gates in ENGLISH_CORE_ROBUSTNESS.md."
  ]
};

console.log(JSON.stringify(report, null, 2));
if (errors.length) process.exitCode = 1;
