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
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const metadata = new Map(seed.cases.map((row) => [row.id, row]));

function requireSameBenchmarkInputs(a, b) {
  const keys = [
    "configSha256",
    "shadowSeedSha256",
    "shadowTaskSha256",
    "shadowManifestSha256",
    "generativeMetricContractSha256",
  ];
  if (!a?.benchmarkInputs || !b?.benchmarkInputs) {
    throw new Error("Both score files must include benchmarkInputs hashes from score-english-core.mjs v8+");
  }
  for (const key of keys) {
    if (!a.benchmarkInputs[key] || !b.benchmarkInputs[key]) throw new Error(`Missing benchmark input hash: ${key}`);
    if (a.benchmarkInputs[key] !== b.benchmarkInputs[key]) {
      throw new Error(`Cannot pair runs from different benchmark inputs: ${key} differs`);
    }
  }
  if (!a.taskFileSha256 || !b.taskFileSha256) throw new Error("Both score files must include taskFileSha256");
  if (a.taskFileSha256 !== b.taskFileSha256) throw new Error("Cannot pair runs with different model-visible task files");
  if (a.taskFileSha256 !== a.benchmarkInputs.shadowTaskSha256 || b.taskFileSha256 !== b.benchmarkInputs.shadowTaskSha256) {
    throw new Error("Score taskFileSha256 must match benchmarkInputs.shadowTaskSha256");
  }
}

function validateScoreDetail(score, label) {
  const detail = score.detail ?? [];
  if (!Array.isArray(detail)) throw new Error(`${label} detail must be an array`);
  const ids = detail.map((row) => row?.id);
  if (ids.some((id) => !id)) throw new Error(`${label} detail contains a missing ID`);
  if (new Set(ids).size !== ids.length) throw new Error(`${label} detail contains duplicate IDs`);
  const unknown = ids.filter((id) => !metadata.has(id));
  if (unknown.length) throw new Error(`${label} detail contains ${unknown.length} IDs absent from the current shadow seed`);
}

requireSameBenchmarkInputs(A, B);
validateScoreDetail(A, "Model A score");
validateScoreDetail(B, "Model B score");

const mapA = new Map((A.detail ?? []).filter((x) => typeof x.score === "number").map((x) => [x.id, x]));
const mapB = new Map((B.detail ?? []).filter((x) => typeof x.score === "number").map((x) => [x.id, x]));
const ids = [...mapA.keys()].filter((id) => mapB.has(id));
if (!ids.length) throw new Error("No aligned scored items between the two score files");

const pairs = ids.map((id) => {
  const a = mapA.get(id);
  const b = mapB.get(id);
  if (a.dimension !== b.dimension) throw new Error(`Dimension mismatch for paired item ${id}`);
  const seedRow = metadata.get(id);
  if (!seedRow) throw new Error(`Missing seed metadata for paired item ${id}`);
  if (seedRow.dimension !== a.dimension) throw new Error(`Score/seed dimension mismatch for ${id}`);
  return {
    id,
    dimension: a.dimension,
    phenomenon: seedRow.phenomenon ?? "unspecified",
    a: a.score,
    b: b.score,
    diff: a.score - b.score,
  };
});

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
function resample(rows, count = rows.length) {
  const out = [];
  for (let i = 0; i < count; i += 1) out.push(rows[Math.floor(random() * rows.length)]);
  return out;
}
function conclusionFrom(ci) {
  if (!ci) return "incomplete";
  if (ci[0] > 0) return "A_higher_on_this_set";
  if (ci[1] < 0) return "B_higher_on_this_set";
  return "inconclusive";
}
function groupByPhenomenon(rows) {
  const groups = new Map();
  for (const row of rows) {
    if (!groups.has(row.phenomenon)) groups.set(row.phenomenon, []);
    groups.get(row.phenomenon).push(row);
  }
  return groups;
}
function hierarchicalSample(rows) {
  const groups = [...groupByPhenomenon(rows).entries()].map(([name, items]) => ({ name, items }));
  if (groups.length < 2) return null;
  const sampledGroups = resample(groups, groups.length);
  const sampledRows = [];
  for (const group of sampledGroups) sampledRows.push(...resample(group.items, group.items.length));
  return sampledRows;
}
function hierarchicalPairedSensitivity(rows) {
  const groups = [...groupByPhenomenon(rows).entries()].map(([name, items]) => ({ name, items }));
  if (groups.length < 2) {
    return {
      phenomenonCount: groups.length,
      pairedHierarchicalBootstrap95: null,
      conclusion: "insufficient_phenomenon_groups_for_sensitivity_lane",
      groupSizes: Object.fromEntries(groups.map((g) => [g.name, g.items.length])),
      note: "Too few phenomenon groups to run between-phenomenon resampling. No universal minimum adequacy threshold is asserted."
    };
  }
  const boot = [];
  for (let i = 0; i < iterations; i += 1) {
    const sampled = hierarchicalSample(rows);
    boot.push(mean(sampled.map((x) => x.diff)) * 100);
  }
  const interval = ci95(boot);
  return {
    phenomenonCount: groups.length,
    pairedHierarchicalBootstrap95: interval,
    conclusion: conclusionFrom(interval),
    groupSizes: Object.fromEntries(groups.map((g) => [g.name, g.items.length])),
    note: "Sensitivity analysis only. Pari phenomena were deliberately designed rather than randomly sampled from a universal English population, so this is not a population-confidence interval."
  };
}
function combinedRobustnessConclusion(itemConclusion, hierarchicalConclusion) {
  if (!["A_higher_on_this_set", "B_higher_on_this_set"].includes(itemConclusion)) return "inconclusive";
  if (hierarchicalConclusion === itemConclusion) return itemConclusion;
  if (hierarchicalConclusion === "insufficient_phenomenon_groups_for_sensitivity_lane") return "item_direction_only_hierarchical_unavailable";
  return "sensitivity_inconclusive";
}
function summarize(rows) {
  const winsA = rows.filter((x) => x.diff > 0).length;
  const winsB = rows.filter((x) => x.diff < 0).length;
  const ties = rows.length - winsA - winsB;
  const boot = [];
  for (let i = 0; i < iterations; i += 1) boot.push(mean(resample(rows).map((x) => x.diff)) * 100);
  const delta = mean(rows.map((x) => x.diff)) * 100;
  const interval = ci95(boot);
  const itemConclusion = conclusionFrom(interval);
  const hierarchical = hierarchicalPairedSensitivity(rows);
  return {
    alignedCases: rows.length,
    deltaAminusB100: Number(delta.toFixed(3)),
    pairedItemBootstrap95: interval,
    pairedItemBootstrapConclusion: itemConclusion,
    phenomenonHierarchicalSensitivity: hierarchical,
    robustnessConclusion: combinedRobustnessConclusion(itemConclusion, hierarchical.conclusion),
    winsA,
    ties,
    winsB,
  };
}

const dimensions = Object.keys(config.composite.weights);
const byDimension = {};
let everyDimensionComplete = true;
for (const d of dimensions) {
  const rows = pairs.filter((x) => x.dimension === d);
  const aMeta = A.dimensionScores?.[d] ?? {};
  const bMeta = B.dimensionScores?.[d] ?? {};
  const sameExpectedCount = Number(aMeta.cases) === Number(bMeta.cases);
  const complete = aMeta.complete === true && bMeta.complete === true && sameExpectedCount && rows.length === Number(aMeta.cases);
  if (!complete) everyDimensionComplete = false;
  byDimension[d] = {
    complete,
    expectedCasesA: aMeta.cases ?? null,
    expectedCasesB: bMeta.cases ?? null,
    alignedScoredCases: rows.length,
    comparison: complete ? summarize(rows) : null,
    incompleteReason: complete ? null : "Paired intervals withheld because one or both models lack full aligned coverage for this dimension."
  };
}

const expectedShadowCases = Number(A.shadowCases);
const fullAlignment = Number.isFinite(expectedShadowCases)
  && expectedShadowCases === Number(B.shadowCases)
  && expectedShadowCases === seed.cases.length
  && pairs.length === expectedShadowCases;
const complete = A.complete === true && B.complete === true && everyDimensionComplete && fullAlignment;

const weightedItemBoot = [];
const equalItemBoot = [];
const weightedHierarchicalBoot = [];
const equalHierarchicalBoot = [];
let compositeHierarchicalAvailable = true;
if (complete) {
  for (const d of dimensions) {
    if (groupByPhenomenon(pairs.filter((x) => x.dimension === d)).size < 2) compositeHierarchicalAvailable = false;
  }
  for (let i = 0; i < iterations; i += 1) {
    const itemDimDelta = {};
    const hierarchicalDimDelta = {};
    for (const d of dimensions) {
      const rows = pairs.filter((x) => x.dimension === d);
      itemDimDelta[d] = mean(resample(rows).map((x) => x.diff)) * 100;
      if (compositeHierarchicalAvailable) {
        const sampled = hierarchicalSample(rows);
        hierarchicalDimDelta[d] = mean(sampled.map((x) => x.diff)) * 100;
      }
    }
    weightedItemBoot.push(dimensions.reduce((acc, d) => acc + itemDimDelta[d] * (config.composite.weights[d] / 100), 0));
    equalItemBoot.push(mean(dimensions.map((d) => itemDimDelta[d])));
    if (compositeHierarchicalAvailable) {
      weightedHierarchicalBoot.push(dimensions.reduce((acc, d) => acc + hierarchicalDimDelta[d] * (config.composite.weights[d] / 100), 0));
      equalHierarchicalBoot.push(mean(dimensions.map((d) => hierarchicalDimDelta[d])));
    }
  }
}

function observedComposite(weighted) {
  if (!complete) return null;
  const vals = {};
  for (const d of dimensions) {
    const rows = pairs.filter((x) => x.dimension === d);
    vals[d] = mean(rows.map((x) => x.diff)) * 100;
  }
  return weighted
    ? dimensions.reduce((acc, d) => acc + vals[d] * (config.composite.weights[d] / 100), 0)
    : mean(dimensions.map((d) => vals[d]));
}

const weightedItemCI = complete ? ci95(weightedItemBoot) : null;
const equalItemCI = complete ? ci95(equalItemBoot) : null;
const weightedHierarchicalCI = complete && compositeHierarchicalAvailable ? ci95(weightedHierarchicalBoot) : null;
const equalHierarchicalCI = complete && compositeHierarchicalAvailable ? ci95(equalHierarchicalBoot) : null;
const weightedItemConclusion = conclusionFrom(weightedItemCI);
const equalItemConclusion = conclusionFrom(equalItemCI);
const weightedHierarchicalConclusion = weightedHierarchicalCI ? conclusionFrom(weightedHierarchicalCI) : "insufficient_phenomenon_groups_for_sensitivity_lane";
const equalHierarchicalConclusion = equalHierarchicalCI ? conclusionFrom(equalHierarchicalCI) : "insufficient_phenomenon_groups_for_sensitivity_lane";

const report = {
  version: 3,
  modelA: A.model ?? null,
  modelB: B.model ?? null,
  benchmarkInputs: A.benchmarkInputs,
  taskFileSha256: A.taskFileSha256,
  alignedScoredCases: pairs.length,
  expectedShadowCases: expectedShadowCases || null,
  fullAlignment,
  completeForHeadlineComparison: complete,
  overallPairedItemComparison: complete ? summarize(pairs) : null,
  exploratoryAlignedItemSummary: complete ? null : {
    alignedCases: pairs.length,
    note: "No inferential winner is reported from this partial intersection. Complete aligned scoring is required."
  },
  byDimension,
  compositeComparison: complete ? {
    productWeightedDeltaAminusB100: Number(observedComposite(true).toFixed(3)),
    productWeightedPairedItemBootstrap95: weightedItemCI,
    productWeightedPairedItemConclusion: weightedItemConclusion,
    productWeightedPhenomenonHierarchicalBootstrap95: weightedHierarchicalCI,
    productWeightedPhenomenonHierarchicalConclusion: weightedHierarchicalConclusion,
    productWeightedRobustnessConclusion: combinedRobustnessConclusion(weightedItemConclusion, weightedHierarchicalConclusion),
    equalWeightDeltaAminusB100: Number(observedComposite(false).toFixed(3)),
    equalWeightPairedItemBootstrap95: equalItemCI,
    equalWeightPairedItemConclusion: equalItemConclusion,
    equalWeightPhenomenonHierarchicalBootstrap95: equalHierarchicalCI,
    equalWeightPhenomenonHierarchicalConclusion: equalHierarchicalConclusion,
    equalWeightRobustnessConclusion: combinedRobustnessConclusion(equalItemConclusion, equalHierarchicalConclusion),
    hierarchicalCompositeAvailable: compositeHierarchicalAvailable,
  } : null,
  compositeWithheldReason: complete ? null : "Headline/composite paired conclusions require identical benchmark hashes, identical task file, complete scoring for both models, and full item alignment across all dimensions.",
  interpretationRules: [
    "Comparisons are paired because both models are evaluated on the exact same items; published NLP evaluation work shows that ignoring instance-level pairing can change system conclusions.",
    "Config, private seed, model-visible shadow task, shadow manifest, generative-metric contract, and task-file hashes must match before comparison.",
    "Missing or externally unscored items are never silently reduced to the intersection for a headline winner claim.",
    "Paired item-bootstrap intervals are conditional on the current shadow items. A separate two-level phenomenon/item hierarchical bootstrap is reported as a dependence sensitivity analysis.",
    "The hierarchical lane is not a population-confidence claim because Pari phenomena were deliberately selected rather than randomly sampled from all English usage.",
    "A directional robustness conclusion requires the item-level and phenomenon-hierarchical lanes to agree; disagreement is reported as sensitivity_inconclusive rather than forcing a winner.",
    "If an item-level paired interval includes zero, report the comparison as inconclusive rather than forcing a winner.",
    "A difference on this shadow set is not automatically a universal-English claim; public anchors, prompt/order robustness, distribution validity, and external replication still matter.",
    "Do not use independent-model confidence-interval overlap as a substitute for paired comparison."
  ],
  bootstrapIterations: iterations,
  bootstrapSeed: "0x70a1b00b",
  researchBasis: [
    {
      "reference": "https://aclanthology.org/2021.acl-long.179/",
      "claim": "Peyrard et al. show that preserving instance-level pairing can materially change NLP system conclusions; averages alone discard pairing information."
    },
    {
      "reference": "https://aclanthology.org/2022.acl-demo.12/",
      "claim": "BooStSa motivates bootstrap significance analysis for NLP system comparisons rather than treating small point-estimate differences as decisive."
    },
    {
      "reference": "https://doi.org/10.1016/j.jml.2023.104494",
      "claim": "Hierarchical dependency in language data motivates hierarchical resampling as a sensitivity diagnostic; this does not validate Pari phenomenon tags as a random-effects population."
    }
  ],
  engineeringChoiceDisclosure: "Grouping paired Pari shadow items by benchmark-authored phenomenon tags and requiring item/hierarchical directional agreement is a conservative Pari robustness rule, not a universal statistical standard established by the cited papers."
};

console.log(JSON.stringify(report, null, 2));
