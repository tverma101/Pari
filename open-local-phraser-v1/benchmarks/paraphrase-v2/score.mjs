/** Score one model's v2 JSONL output with Pari's shared safety/quality judge. */
import fs from "fs";
import path from "path";
import { scoreCase } from "../eval/metrics.mjs";
import { meaningContractIssuesForBenchmark } from "./meaning-contract-bridge.mjs";
import {
  DEFAULT_CORPUS_PATH,
  loadV2Corpus,
  resolveRepoPath,
  ROOT_DIR,
  validateV2Corpus,
  loadV2Sources,
} from "./schema.mjs";

const args = process.argv.slice(2);
function argValue(flag) {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

const outputsPathArg = argValue("--outputs");
if (!outputsPathArg) throw new Error("usage: node benchmarks/paraphrase-v2/score.mjs --outputs <raw.jsonl> [--out <scored.json>] [--metadata <meta.json>] [--production-postprocess]");
const outputsPath = path.resolve(outputsPathArg);
const corpusPath = resolveRepoPath(argValue("--corpus"), DEFAULT_CORPUS_PATH);
const corpusData = loadV2Corpus(corpusPath);
const validation = validateV2Corpus(corpusData, loadV2Sources());
if (!validation.valid) throw new Error(`v2 corpus is invalid: ${validation.errors.join("; ")}`);
const corpus = corpusData.cases;
const productionPostprocess = args.includes("--production-postprocess");

let rawRows = fs.readFileSync(outputsPath, "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line));
const duplicateIds = rawRows.map((row) => row.id).filter((id, index, all) => all.indexOf(id) !== index);
if (duplicateIds.length) throw new Error(`duplicate output IDs: ${[...new Set(duplicateIds)].join(", ")}`);
const rawById = new Map(rawRows.map((row) => [row.id, row]));
const unknownIds = [...rawById.keys()].filter((id) => !corpus.some((item) => item.id === id));
if (unknownIds.length) throw new Error(`output contains unknown v2 IDs: ${unknownIds.join(", ")}`);

let finalizeDraft;
let extractProtectedSpans;
if (productionPostprocess) {
  const nodeRequire = (await import("module")).createRequire(import.meta.url);
  const ts = (await import("typescript")).default;
  const vm = await import("vm");
  const moduleCache = new Map();
  const resolveFile = (basePath) => {
    for (const candidate of [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`]) {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
    }
    throw new Error(`Cannot resolve ${basePath}`);
  };
  const resolveModule = (specifier, fromFile) => {
    if (specifier.startsWith("@/")) return resolveFile(path.join(ROOT_DIR, "src", specifier.slice(2)));
    if (specifier.startsWith(".")) return resolveFile(path.resolve(path.dirname(fromFile), specifier));
    return null;
  };
  const loadTsModule = (filePath) => {
    const absolutePath = resolveFile(filePath);
    if (moduleCache.has(absolutePath)) return moduleCache.get(absolutePath).exports;
    const source = fs.readFileSync(absolutePath, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: { esModuleInterop: true, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
      fileName: absolutePath,
    }).outputText;
    const module = { exports: {} };
    moduleCache.set(absolutePath, module);
    const localRequire = (specifier) => {
      const resolved = resolveModule(specifier, absolutePath);
      return resolved ? loadTsModule(resolved) : nodeRequire(specifier);
    };
    const wrapper = `(function(exports, require, module, __filename, __dirname) {\n${output}\n})`;
    vm.runInThisContext(wrapper, { filename: absolutePath })(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
    return module.exports;
  };
  ({ finalizeDraft } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/localParaphrase.ts")));
  ({ extractProtectedSpans } = loadTsModule(path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts")));
}

const results = [];
for (const item of corpus) {
  const rawRow = rawById.get(item.id) ?? {};
  let output = String(rawRow.output ?? "");
  if (productionPostprocess && output) {
    output = finalizeDraft(output, item.input, extractProtectedSpans(item.input), "personal", false).trim();
  }
  if (!output) {
    results.push({ id: item.id, category: item.category, output: "", passed: false, meaningSafe: false, englishQuality: false, empty: true, failedChecks: ["empty-output"] });
    continue;
  }
  const scored = await scoreCase(item, output);
  const meaningContractIssues = meaningContractIssuesForBenchmark(item.input, output);
  const meaningContractSafe = meaningContractIssues.length === 0;
  const failedChecks = meaningContractSafe
    ? (scored.failedChecks ?? [])
    : [...new Set([...(scored.failedChecks ?? []), "meaningContractSafe"])];
  results.push({
    ...scored,
    passed: scored.passed && meaningContractSafe,
    meaningSafe: scored.meaningSafe && meaningContractSafe,
    failedChecks,
    meaningContract: {
      safe: meaningContractSafe,
      issues: meaningContractIssues,
    },
    output,
    ...(Number.isFinite(rawRow.seconds) ? { seconds: rawRow.seconds } : {}),
    ...(Number.isFinite(rawRow.totalSeconds) ? { totalSeconds: rawRow.totalSeconds } : {}),
    ...(Number.isFinite(rawRow.pickedTemp) ? { temperature: rawRow.pickedTemp } : {}),
  });
}

const byCategory = aggregateByCategory(results);
const overall = aggregate(results);
const hardSafetyFailures = results.filter((row) => !row.meaningSafe).length;
const metadataPath = argValue("--metadata");
const metadata = metadataPath && fs.existsSync(path.resolve(metadataPath))
  ? JSON.parse(fs.readFileSync(path.resolve(metadataPath), "utf8"))
  : {};
const engine = {
  ...(metadata.engine ?? { name: path.basename(outputsPath, path.extname(outputsPath)), role: "unclassified" }),
  ...(argValue("--engine-name") ? { name: argValue("--engine-name") } : {}),
};
const outPath = path.resolve(argValue("--out") ?? path.join(ROOT_DIR, "benchmarks/paraphrase-v2/results", `${path.basename(outputsPath, path.extname(outputsPath))}${productionPostprocess ? ".pari-postprocess" : ""}.scored.json`));
fs.mkdirSync(path.dirname(outPath), { recursive: true });
const payload = {
  schemaVersion: 1,
  benchmark: "pari-paraphrase-v2",
  generatedAt: new Date().toISOString(),
  corpus: { path: corpusPath, version: corpusData.version, cases: corpus.length },
  outputs: { path: outputsPath, productionPostprocess },
  engine,
  metadata,
  overall,
  byCategory,
  safety: { hardSafetyFailures, allCasesSafe: hardSafetyFailures === 0 },
  automaticJudgeBoundary: "Diagnostics only; automatic scores do not replace the blinded human preference protocol.",
  results,
};
fs.writeFileSync(outPath, JSON.stringify(payload, null, 2) + "\n");

console.log(`[v2:score] ${payload.engine.name ?? "engine"} ${overall.passed}/${overall.total} full-gate cases`);
console.log(`[v2:score] meaning-safe=${overall.meaningSafe}/${overall.total} english-quality=${overall.englishQuality}/${overall.total} hard-safety-failures=${hardSafetyFailures}`);
console.log(`[v2:score] automaticDiagnosticIndex=${overall.automaticDiagnosticIndex} -> ${outPath}`);
if (args.includes("--fail-on-hard-safety") && hardSafetyFailures > 0) process.exitCode = 1;

function mean(rows, key) {
  const values = rows.map((row) => row.metrics?.[key]).filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(3));
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function aggregate(rows) {
  const total = rows.length;
  const passed = rows.filter((row) => row.passed).length;
  const meaningSafe = rows.filter((row) => row.meaningSafe).length;
  const englishQuality = rows.filter((row) => row.englishQuality).length;
  const meanEnglish = mean(rows, "englishQualityScore") ?? 0;
  const meanFluency = mean(rows, "fluencyScore") ?? 0;
  const automaticDiagnosticIndex = total === 0 ? 0 : Number((100 * (
    0.35 * passed / total +
    0.25 * meaningSafe / total +
    0.2 * englishQuality / total +
    0.1 * meanEnglish +
    0.1 * meanFluency
  )).toFixed(2));
  const failedChecks = {};
  for (const row of rows) for (const check of row.failedChecks ?? []) failedChecks[check] = (failedChecks[check] ?? 0) + 1;
  return {
    total,
    passed,
    passRate: total ? Number((passed / total).toFixed(3)) : 0,
    meaningSafe,
    meaningSafeRate: total ? Number((meaningSafe / total).toFixed(3)) : 0,
    englishQuality,
    englishQualityRate: total ? Number((englishQuality / total).toFixed(3)) : 0,
    automaticDiagnosticIndex,
    failedChecks,
    meanMetrics: Object.fromEntries([
      "cosineSim", "grammarGain", "englishQualityScore", "fluencyScore", "errorsInPer100",
      "errorsOutPer100", "editDistanceRatio", "contentOverlap", "distinctBigram",
    ].map((key) => [key, mean(rows, key)])),
  };
}

function aggregateByCategory(rows) {
  const categories = {};
  for (const row of rows) (categories[row.category] ??= []).push(row);
  return Object.fromEntries(Object.entries(categories).map(([category, categoryRows]) => [category, aggregate(categoryRows)]));
}
