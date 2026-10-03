#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildProvenance,
  reconcileScoreStructure,
  selectScoreView,
} from "./english-core-snapshot-binding.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));

const USAGE = [
  "Usage: node analyze-english-core-statistics.mjs <score.json> [bootstrap_iterations]",
  "         [--benchmark-dir <dir>] [--source-score-manifest <file>] [--score-view <name>]",
  "",
  "  --benchmark-dir         Directory holding the exact benchmark snapshot named by the",
  "                          source score artifact. Defaults to this script's own directory.",
  "                          Every consumed file is hashed and compared with the score's",
  "                          benchmarkInputs before any statistic is computed (issue #65).",
  "  --source-score-manifest Optional frozen manifest of expected source score file hashes;",
  "                          use it to prove a score artifact was not edited after recording.",
  "  --score-view            Explicit strict|recoverable score view to analyze. Only valid when",
  "                          the source score artifact declares that view (issue #64).",
].join("\n");

function parseCli(argv) {
  const positional = [];
  const options = { benchmarkDir: null, sourceScoreManifest: null, scoreView: null };
  const optionNames = {
    "--benchmark-dir": "benchmarkDir",
    "--source-score-manifest": "sourceScoreManifest",
    "--score-view": "scoreView",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (Object.prototype.hasOwnProperty.call(optionNames, token)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${token} requires a path argument`);
      options[optionNames[token]] = value;
      index += 1;
      continue;
    }
    if (token.startsWith("--")) throw new Error(`Unknown option: ${token}`);
    positional.push(token);
  }
  return { positional, options };
}

const { positional, options } = parseCli(process.argv.slice(2));
const scorePath = positional[0];
const iterations = Number(positional[1] ?? 10000);
const benchmarkDir = path.resolve(options.benchmarkDir ?? here);
if (!scorePath) {
  console.error(USAGE);
  process.exit(2);
}
if (!Number.isInteger(iterations) || iterations < 1000) throw new Error("bootstrap_iterations must be an integer >= 1000");

const sourceScoreBytes = fs.readFileSync(scorePath);
const sourceScoreFileSha256 = crypto.createHash("sha256").update(sourceScoreBytes).digest("hex");
const score = JSON.parse(sourceScoreBytes.toString("utf8"));
if (score.schemaVersion !== 1 || score.artifactType !== "pari.english-core.shadow-score") {
  throw new Error("Input is not a supported versioned English Core shadow-score artifact");
}
const inputResultSchema = score.inputResultSchema;
if (inputResultSchema?.resultSchemaVersion !== 1 || !/^[0-9a-f]{64}$/.test(inputResultSchema?.schemaSha256 ?? "")) {
  throw new Error("Score report lacks current English Core result-schema validation provenance");
}
if (!Number.isInteger(score.version)) {
  throw new Error(`Score report carries no integer scorer version (got ${JSON.stringify(score.version)})`);
}

const provenance = buildProvenance({
  label: "Source score",
  scorePath,
  sourceScoreFileSha256,
  score,
  benchmarkDir,
  analysisScriptName: "analyze-english-core-statistics.mjs",
  analysisScriptDir: here,
  scorerName: "score-english-core.mjs",
  sourceScoreManifest: options.sourceScoreManifest,
  bootstrapSeed: "0x45c0a11d",
  iterations,
});

const config = provenance.snapshot.config;
const seed = provenance.snapshot.seed;
const structure = reconcileScoreStructure({
  score,
  snapshot: provenance.snapshot,
  config,
  label: "Source score",
  requirePromotionReady: false,
});
const scoreView = selectScoreView({
  scoreView: provenance.scoreView,
  requested: options.scoreView,
  label: "Source score",
});
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
function sampleWithReplacement(rows, count = rows.length) {
  const out = [];
  for (let i = 0; i < count; i += 1) out.push(rows[Math.floor(random() * rows.length)]);
  return out;
}
function groupByPhenomenon(rows) {
  const groups = new Map();
  for (const row of rows) {
    const phenomenon = metadata.get(row.id)?.phenomenon ?? "unspecified";
    if (!groups.has(phenomenon)) groups.set(phenomenon, []);
    groups.get(phenomenon).push(row);
  }
  return groups;
}
function phenomenonHierarchicalBootstrap(rows) {
  const groups = [...groupByPhenomenon(rows).entries()].map(([name, items]) => ({ name, items }));
  if (groups.length < 2) {
    return {
      phenomenonCount: groups.length,
      hierarchicalBootstrap95: null,
      note: "Too few phenomenon groups to run a between-phenomenon resampling sensitivity analysis."
    };
  }

  const boot = [];
  for (let b = 0; b < iterations; b += 1) {
    const sampledGroups = sampleWithReplacement(groups, groups.length);
    const sampledRows = [];
    for (const group of sampledGroups) {
      // Preserve the selected phenomenon's original item count while also
      // resampling within that phenomenon. This is a two-level hierarchical
      // sensitivity analysis rather than a plain whole-cluster bootstrap.
      sampledRows.push(...sampleWithReplacement(group.items, group.items.length));
    }
    boot.push(mean(sampledRows.map((x) => x.score)) * 100);
  }

  return {
    phenomenonCount: groups.length,
    hierarchicalBootstrap95: ci95(boot),
    groupSizes: Object.fromEntries(groups.map((g) => [g.name, g.items.length])),
    note: "Exploratory sensitivity only. Phenomena and items were benchmark-designed rather than sampled randomly from a universal English population, so this interval is not a population-confidence claim and no universal minimum phenomenon count is asserted."
  };
}

const scored = (score.detail ?? []).filter((x) => typeof x.score === "number");
const dimensions = Object.keys(config.composite.weights);
const byDimension = Object.fromEntries(dimensions.map((d) => [d, scored.filter((x) => x.dimension === d)]));

const dimensionReport = {};
for (const dimension of dimensions) {
  const rows = byDimension[dimension];
  // ReconcileScoreStructure already proved declared.cases === observed rows ===
  // bound-seed rows, so the denominator is the bound snapshot's, not a
  // per-dimension fallback chosen at analysis time.
  const expectedCases = structure.seedCountByDimension[dimension];
  const complete = rows.length === expectedCases && expectedCases > 0
    && score.dimensionScores?.[dimension]?.complete === true;
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
    itemBootstrap95: complete ? ci95(boot) : null,
    phenomenonHierarchicalSensitivity: complete ? phenomenonHierarchicalBootstrap(rows) : null,
    incompleteReason: complete ? null : "Uncertainty withheld because the dimension is not completely scored; partial-item intervals would overstate comparability.",
    phenomena: Object.fromEntries(Object.entries(phenomena).map(([k, xs]) => [k, {
      cases: xs.length,
      score100Exploratory: Number((mean(xs) * 100).toFixed(3))
    }]))
  };
}

const allDimensionsComplete = structure.reconciledComplete
  && dimensions.every((d) => dimensionReport[d].complete);
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
  version: 5,
  schemaVersion: 1,
  artifactType: "pari.english-core.uncertainty-report",
  inputResultSchema,
  provenance,
  scoreView,
  structureReconciliation: {
    reconciledComplete: structure.reconciledComplete,
    dimensionsComplete: structure.dimensionsComplete,
    detailComplete: structure.detailComplete,
    note: "Score detail rows, per-dimension counts and the bound seed snapshot were reconciled independently before any resampling; declared complete/cases fields are treated as claims, not truth.",
  },
  runId: score.runId ?? null,
  model: score.model ?? null,
  benchmarkInputs: score.benchmarkInputs ?? null,
  taskFileSha256: score.taskFileSha256 ?? null,
  bootstrapIterations: iterations,
  bootstrapSeed: "0x45c0a11d",
  dimensions: dimensionReport,
  compositeComplete: allDimensionsComplete,
  compositeUncertainty: allDimensionsComplete ? {
    productWeightedItemBootstrap95: ci95(weightedBoot),
    equalWeightItemBootstrap95: ci95(equalBoot)
  } : null,
  compositeWithheldReason: allDimensionsComplete ? null : "Composite uncertainty is withheld until every English Core dimension is completely scored.",
  interpretationRules: [
    "Item-bootstrap intervals are nonparametric resampling intervals conditional on the current English Core shadow items.",
    "Items share designed linguistic phenomena and may not be independent; each dimension therefore also reports a two-level phenomenon/item hierarchical-bootstrap sensitivity analysis.",
    "The hierarchical result is a robustness sensitivity analysis, not a population confidence interval: the benchmark phenomena themselves were deliberately selected rather than randomly sampled from all English usage.",
    "No universal minimum number of phenomenon groups is asserted. Small group counts should be shown directly and interpreted cautiously rather than converted into an invented adequacy threshold.",
    "Neither uncertainty lane implies that the handcrafted shadow set is an i.i.d. sample from a universal distribution of English.",
    "A dimension must be fully scored before uncertainty is reported; missing generative judgments are not silently ignored.",
    "Expected per-dimension case counts come from the bound benchmark snapshot after it matched the source score artifact's benchmarkInputs hashes; the full seed size is never used as a dimension fallback.",
    "Composite uncertainty is reported only when the score report itself is complete and all seven dimensions have full item coverage.",
    "Very wide or materially different item-vs-hierarchical intervals are evidence against fine-grained winner claims.",
    "Per-phenomenon descriptive values remain visible and exploratory because many phenomena contain very few items.",
    "Use paired comparison on the same items when comparing two models; do not infer a model-vs-model significance result from separate confidence-interval overlap."
  ],
  researchBasis: [
    {
      "reference": "https://aclanthology.org/2022.acl-demo.12/",
      "claim": "Bootstrap-based uncertainty/significance is useful for NLP evaluation; slightly higher point estimates alone are insufficient."
    },
    {
      "reference": "https://aclanthology.org/2021.acl-long.179/",
      "claim": "Model comparisons on the same instances should preserve pairing rather than rely only on independent averages."
    },
    {
      "reference": "https://aclanthology.org/2024.naacl-long.86/",
      "claim": "Benchmark data distributions can materially change absolute scores and relative model rankings."
    },
    {
      "reference": "https://doi.org/10.1016/j.jml.2023.104494",
      "claim": "Language data can have hierarchical dependency structures for which hierarchical resampling is a useful diagnostic; this paper is not evidence that Pari phenomena are a random-effects population."
    },
    {
      "reference": "https://arxiv.org/abs/2606.26422",
      "claim": "Recent nested-text simulations distinguish cluster and hierarchical bootstrap behavior; Pari uses the hierarchical lane only as a sensitivity diagnostic because its nesting structure and small groups differ from the paper's simulated settings.",
      "status": "preprint"
    }
  ],
  engineeringChoiceDisclosure: "Grouping shadow items by Pari's phenomenon tags for hierarchical resampling is an application-specific robustness choice motivated by dependence concerns; no cited paper validates these exact tags as a statistically sampled population."
};

console.log(JSON.stringify(report, null, 2));
