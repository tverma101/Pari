#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const scorePath = process.argv[2];
const iterations = Number(process.argv[3] ?? 10000);
if (!scorePath) {
  console.error("Usage: node analyze-english-core-statistics.mjs <score.json> [bootstrap_iterations]");
  process.exit(2);
}
if (!Number.isInteger(iterations) || iterations < 1000) throw new Error("bootstrap_iterations must be an integer >= 1000");

const score = JSON.parse(fs.readFileSync(scorePath, "utf8"));
const config = JSON.parse(fs.readFileSync(path.join(here, "english-core-config.json"), "utf8"));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const metadata = new Map(seed.cases.map((x) => [x.id, x]));

// Deterministic PRNG so reports are reproducible. This is only for bootstrap
// resampling, not for generation.
let state = 0x45c0a11d;
function random() {
  state ^= state << 13;
  state ^= state >>> 17;
  state ^= state << 5;
  return (state >>> 0) / 4294967296;
}

function mean(xs) { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; }
function percentile(sorted, p) {
  if (!sorted.length) return null;
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}
function ci95(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return [percentile(s, 0.025), percentile(s, 0.975)].map((x) => Number(x.toFixed(3)));
}
function sampleWithReplacement(rows) {
  const out = [];
  for (let i = 0; i < rows.length; i += 1) out.push(rows[Math.floor(random() * rows.length)]);
  return out;
}

const scored = (score.detail ?? []).filter((x) => typeof x.score === "number");
const dimensions = Object.keys(config.composite.weights);
const byDimension = Object.fromEntries(dimensions.map((d) => [d, scored.filter((x) => x.dimension === d)]));

const dimensionReport = {};
for (const dimension of dimensions) {
  const rows = byDimension[dimension];
  const boot = [];
  if (rows.length) {
    for (let b = 0; b < iterations; b += 1) boot.push(mean(sampleWithReplacement(rows).map((x) => x.score)) * 100);
  }
  const phenomena = {};
  for (const row of rows) {
    const phenomenon = metadata.get(row.id)?.phenomenon ?? "unspecified";
    if (!phenomena[phenomenon]) phenomena[phenomenon] = [];
    phenomena[phenomenon].push(row.score);
  }
  dimensionReport[dimension] = {
    cases: rows.length,
    score100: rows.length ? Number((mean(rows.map((x) => x.score)) * 100).toFixed(3)) : null,
    bootstrap95: ci95(boot),
    phenomena: Object.fromEntries(Object.entries(phenomena).map(([k, xs]) => [k, {
      cases: xs.length,
      score100: Number((mean(xs) * 100).toFixed(3))
    }]))
  };
}

const allDimensionsPresent = dimensions.every((d) => byDimension[d].length > 0);
const weightedBoot = [];
const equalBoot = [];
if (allDimensionsPresent) {
  for (let b = 0; b < iterations; b += 1) {
    const dimMeans = {};
    for (const d of dimensions) dimMeans[d] = mean(sampleWithReplacement(byDimension[d]).map((x) => x.score)) * 100;
    weightedBoot.push(dimensions.reduce((acc, d) => acc + dimMeans[d] * (config.composite.weights[d] / 100), 0));
    equalBoot.push(mean(dimensions.map((d) => dimMeans[d])));
  }
}

const report = {
  version: 1,
  runId: score.runId ?? null,
  model: score.model ?? null,
  bootstrapIterations: iterations,
  bootstrapSeed: "0x45c0a11d",
  dimensions: dimensionReport,
  compositeUncertainty: allDimensionsPresent ? {
    productWeighted95: ci95(weightedBoot),
    equalWeight95: ci95(equalBoot)
  } : null,
  interpretationRules: [
    "These are nonparametric item-resampling intervals conditional on the current English Core shadow set.",
    "They do not imply that the handcrafted shadow set is a random sample from a universal distribution of English.",
    "Very wide intervals are expected for dimensions with only a handful of shadow items and are evidence against making fine-grained winner claims.",
    "Per-phenomenon results remain visible because correlated/similar items can make naive item-level precision look stronger than it is.",
    "Use paired comparison on the same items when comparing two models; do not infer a model-vs-model significance result merely from overlap or non-overlap of two separate confidence intervals."
  ],
  researchBasis: [
    "Fornaciari et al., ACL 2022, BooStSa: bootstrap sampling for NLP model evaluation",
    "Peyrard et al., ACL 2021, Better than Average: Paired Evaluation of NLP systems",
    "Siska et al., ACL 2024, robustness to benchmark distributional assumptions",
    "Kovatchev and Lease, NAACL 2024, Benchmark Transparency"
  ]
};

console.log(JSON.stringify(report, null, 2));
