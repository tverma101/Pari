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
const seedCountByDimension = Object.fromEntries(
  Object.keys(config.composite.weights).map((dimension) => [
    dimension,
    seed.cases.filter((row) => row.dimension === dimension).length,
  ]),
);

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
  const declared = score.dimensionScores?.[dimension] ?? {};
  const expectedCases = Number(declared.cases ?? seedCountByDimension[dimension] ?? 0);
  const complete = declared.complete === true && rows.length === expectedCases && expectedCases > 0;
  const boot = [];
  if (complete) {
    for (let b = 0; b < iterations; b += 1) boot.push(mean(sampleWithReplacement(rows).map((x) => x.score)) * 100);
  }
  const phenomena = {};
  for (const row of rows) {
    const phenomenon = metadata.get(row.id)?.phenomenon ?? "unspecified";
    if (!phenomena[phenomenon]) phenomena[phenomenon] = [];
    phenomena[phenomenon].push(row.score);
  }
  dimensionReport[dimension] = {
    expectedCases,
    scoredCases: rows.length,
    coverage: expectedCases ? Number((rows.length / expectedCases).toFixed(6)) : null,
    complete,
    score100: complete ? Number((mean(rows.map((x) => x.score)) * 100).toFixed(3)) : null,
    bootstrap95: complete ? ci95(boot) : null,
    incompleteReason: complete ? null : "Uncertainty withheld because the dimension is not completely scored; partial-item intervals would overstate comparability.",
    phenomena: Object.fromEntries(Object.entries(phenomena).map(([k, xs]) => [k, {
      cases: xs.length,
      score100Exploratory: Number((mean(xs) * 100).toFixed(3))
    }]))
  };
}

const allDimensionsComplete = score.complete === true && dimensions.every((d) => dimensionReport[d].complete);
const weightedBoot = [];
const equalBoot = [];
if (allDimensionsComplete) {
  for (let b = 0; b < iterations; b += 1) {
    const dimMeans = {};
    for (const d of dimensions) dimMeans[d] = mean(sampleWithReplacement(byDimension[d]).map((x) => x.score)) * 100;
    weightedBoot.push(dimensions.reduce((acc, d) => acc + dimMeans[d] * (config.composite.weights[d] / 100), 0));
    equalBoot.push(mean(dimensions.map((d) => dimMeans[d])));
  }
}

const report = {
  version: 3,
  runId: score.runId ?? null,
  model: score.model ?? null,
  benchmarkInputs: score.benchmarkInputs ?? null,
  taskFileSha256: score.taskFileSha256 ?? null,
  bootstrapIterations: iterations,
  bootstrapSeed: "0x45c0a11d",
  dimensions: dimensionReport,
  compositeComplete: allDimensionsComplete,
  compositeUncertainty: allDimensionsComplete ? {
    productWeighted95: ci95(weightedBoot),
    equalWeight95: ci95(equalBoot)
  } : null,
  compositeWithheldReason: allDimensionsComplete ? null : "Composite uncertainty is withheld until every English Core dimension is completely scored.",
  interpretationRules: [
    "These are nonparametric item-resampling intervals conditional on the current English Core shadow set.",
    "They do not imply that the handcrafted shadow set is a random sample from a universal distribution of English.",
    "A dimension must be fully scored before its bootstrap interval is reported; missing generative judgments are not silently ignored.",
    "Expected per-dimension case counts come from the scored report when present, otherwise from the current seed's true per-dimension counts; the full 68-case seed size is never used as a dimension fallback.",
    "Composite uncertainty is reported only when the score report itself is complete and all seven dimensions have full item coverage.",
    "Very wide intervals are evidence against making fine-grained winner claims.",
    "Per-phenomenon descriptive values remain visible, but they are labeled exploratory because many phenomena contain very few items.",
    "Use paired comparison on the same items when comparing two models; do not infer a model-vs-model significance result from separate confidence-interval overlap."
  ],
  researchBasis: [
    "Fornaciari et al., ACL 2022, BooStSa: bootstrap sampling for NLP model evaluation",
    "Peyrard et al., ACL 2021, Better than Average: Paired Evaluation of NLP systems",
    "Siska et al., ACL 2024, robustness to benchmark distributional assumptions",
    "Kovatchev and Lease, NAACL 2024, Benchmark Transparency"
  ]
};

console.log(JSON.stringify(report, null, 2));
