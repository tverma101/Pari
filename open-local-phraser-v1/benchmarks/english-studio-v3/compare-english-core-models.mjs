#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const aPath = process.argv[2];
const bPath = process.argv[3];
const iterations = Number(process.argv[4] ?? 10000);
if (!aPath || !bPath) {
  console.error("Usage: node compare-english-core-models.mjs <score-A.json> <score-B.json> [bootstrap_iterations]");
  process.exit(2);
}
if (!Number.isInteger(iterations) || iterations < 1000) throw new Error("bootstrap_iterations must be an integer >= 1000");

const A = JSON.parse(fs.readFileSync(aPath, "utf8"));
const B = JSON.parse(fs.readFileSync(bPath, "utf8"));
const config = JSON.parse(fs.readFileSync(path.join(here, "english-core-config.json"), "utf8"));

const mapA = new Map((A.detail ?? []).filter((x) => typeof x.score === "number").map((x) => [x.id, x]));
const mapB = new Map((B.detail ?? []).filter((x) => typeof x.score === "number").map((x) => [x.id, x]));
const ids = [...mapA.keys()].filter((id) => mapB.has(id));
if (!ids.length) throw new Error("No aligned scored items between the two score files");

const pairs = ids.map((id) => ({
  id,
  dimension: mapA.get(id).dimension,
  a: mapA.get(id).score,
  b: mapB.get(id).score,
  diff: mapA.get(id).score - mapB.get(id).score
}));

let state = 0x70a1b00b;
function random() {
  state ^= state << 13;
  state ^= state >>> 17;
  state ^= state << 5;
  return (state >>> 0) / 4294967296;
}
function mean(xs) { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; }
function percentile(sorted, p) {
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}
function ci95(xs) {
  const s = [...xs].sort((a, b) => a - b);
  return [percentile(s, 0.025), percentile(s, 0.975)].map((x) => Number(x.toFixed(3)));
}
function resample(rows) {
  const out = [];
  for (let i = 0; i < rows.length; i += 1) out.push(rows[Math.floor(random() * rows.length)]);
  return out;
}
function summarize(rows) {
  const winsA = rows.filter((x) => x.diff > 0).length;
  const winsB = rows.filter((x) => x.diff < 0).length;
  const ties = rows.length - winsA - winsB;
  const boot = [];
  for (let i = 0; i < iterations; i += 1) boot.push(mean(resample(rows).map((x) => x.diff)) * 100);
  const delta = mean(rows.map((x) => x.diff)) * 100;
  const interval = ci95(boot);
  let conclusion = "inconclusive";
  if (interval[0] > 0) conclusion = "A_higher_on_this_set";
  else if (interval[1] < 0) conclusion = "B_higher_on_this_set";
  return {
    alignedCases: rows.length,
    deltaAminusB100: Number(delta.toFixed(3)),
    pairedBootstrap95: interval,
    winsA,
    ties,
    winsB,
    conclusion
  };
}

const dimensions = Object.keys(config.composite.weights);
const byDimension = {};
for (const d of dimensions) {
  const rows = pairs.filter((x) => x.dimension === d);
  byDimension[d] = rows.length ? summarize(rows) : null;
}

// Stratified paired bootstrap for the product-weighted and equal-weight composites.
const availableDimensions = dimensions.filter((d) => pairs.some((x) => x.dimension === d));
const complete = availableDimensions.length === dimensions.length;
const weightedBoot = [];
const equalBoot = [];
if (complete) {
  for (let i = 0; i < iterations; i += 1) {
    const dimDelta = {};
    for (const d of dimensions) {
      const rows = pairs.filter((x) => x.dimension === d);
      dimDelta[d] = mean(resample(rows).map((x) => x.diff)) * 100;
    }
    weightedBoot.push(dimensions.reduce((acc, d) => acc + dimDelta[d] * (config.composite.weights[d] / 100), 0));
    equalBoot.push(mean(dimensions.map((d) => dimDelta[d])));
  }
}

function observedComposite(weighted) {
  const vals = {};
  for (const d of dimensions) {
    const rows = pairs.filter((x) => x.dimension === d);
    if (!rows.length) return null;
    vals[d] = mean(rows.map((x) => x.diff)) * 100;
  }
  return weighted
    ? dimensions.reduce((acc, d) => acc + vals[d] * (config.composite.weights[d] / 100), 0)
    : mean(dimensions.map((d) => vals[d]));
}

function conclusionFrom(ci) {
  if (!ci) return "incomplete";
  if (ci[0] > 0) return "A_higher_on_this_set";
  if (ci[1] < 0) return "B_higher_on_this_set";
  return "inconclusive";
}

const weightedCI = complete ? ci95(weightedBoot) : null;
const equalCI = complete ? ci95(equalBoot) : null;
const report = {
  version: 1,
  modelA: A.model ?? null,
  modelB: B.model ?? null,
  alignedCases: pairs.length,
  overallPairedItemComparison: summarize(pairs),
  byDimension,
  compositeComparison: complete ? {
    productWeightedDeltaAminusB100: Number(observedComposite(true).toFixed(3)),
    productWeightedPairedBootstrap95: weightedCI,
    productWeightedConclusion: conclusionFrom(weightedCI),
    equalWeightDeltaAminusB100: Number(observedComposite(false).toFixed(3)),
    equalWeightPairedBootstrap95: equalCI,
    equalWeightConclusion: conclusionFrom(equalCI)
  } : null,
  interpretationRules: [
    "Comparisons are paired because both models are evaluated on the same items.",
    "If the paired interval includes zero, report the comparison as inconclusive rather than forcing a winner.",
    "A significant difference on this shadow set is not automatically a universal-English claim; public anchors, prompt robustness, distribution validity, and external replication still matter.",
    "Do not use independent-model confidence-interval overlap as a substitute for this paired comparison."
  ],
  bootstrapIterations: iterations,
  bootstrapSeed: "0x70a1b00b",
  researchBasis: [
    "Peyrard et al., ACL 2021, Better than Average: Paired Evaluation of NLP systems",
    "Fornaciari et al., ACL 2022, BooStSa",
    "Levtsov and Ustalov, ACL SRW 2025, Confidence and Stability of Global and Pairwise Scores"
  ]
};

console.log(JSON.stringify(report, null, 2));
