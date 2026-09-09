/**
 * Best-of-N selector: score every candidate with the eval gates and pick
 * the winner per case. Emits {"id","output"} JSONL for run-eval.mjs.
 *
 * Selection: passing candidates first; among them rank by
 *   sim + 0.01*clampedGrammarGain + 0.05*bandFitBonus,
 * ties broken toward lower temperature (determinism-friendly).
 * If nothing passes, fall back to the greedy (temp=0) candidate.
 */
import fs from "fs";
import path from "path";
import vm from "vm";
import { createRequire } from "module";
import ts from "typescript";
import { scoreCase } from "../eval/metrics.mjs";

const ROOT = path.resolve(new URL("../..", import.meta.url).pathname);
const args = process.argv.slice(2);
function argValue(flag) {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

const corpusPath = path.resolve(ROOT, argValue("--corpus") ?? "benchmarks/eval/corpus.json");
const corpusData = JSON.parse(fs.readFileSync(corpusPath, "utf8"));
const corpus = Array.isArray(corpusData) ? corpusData : corpusData.cases;
const byId = new Map(corpus.map((c) => [c.id, c]));

const inFile = args.find((value, index) => index === 0 && !value.startsWith("--"));
const outFile = args.find((value, index) => index === 1 && !value.startsWith("--"));
if (!inFile || !outFile) {
  throw new Error("usage: node benchmarks/llm-shootout/select-best.mjs <candidates.jsonl> <winners.jsonl> [--corpus <corpus.json>] [--production-postprocess]");
}

const productionPostprocess = args.includes("--production-postprocess");
const productionSafety = args.includes("--production-safety");
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();
function resolveFile(basePath) {
  for (const candidate of [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`Cannot resolve ${basePath}`);
}
function resolveModule(specifier, fromFile) {
  if (specifier.startsWith("@/")) return resolveFile(path.join(ROOT, "src", specifier.slice(2)));
  if (specifier.startsWith(".")) return resolveFile(path.resolve(path.dirname(fromFile), specifier));
  return null;
}
function loadTsModule(filePath) {
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
}

let finalizeDraft = null;
let extractProtectedSpans = null;
let validateProtectedContent = null;
if (productionPostprocess) {
  ({ finalizeDraft } = loadTsModule(path.join(ROOT, "src/lib/generation/localParaphrase.ts")));
  ({ extractProtectedSpans } = loadTsModule(path.join(ROOT, "src/lib/safety/protectedContent.ts")));
}
if (productionSafety) {
  ({ extractProtectedSpans, validateProtectedContent } = loadTsModule(path.join(ROOT, "src/lib/safety/protectedContent.ts")));
}

const rows = fs.readFileSync(inFile, "utf8").split("\n").filter(Boolean).map(JSON.parse);
const out = [];
let nPassFirst = 0;
let nCandidates = 0;

function candidateText(cas, text) {
  if (!productionPostprocess) return text.trim();
  return finalizeDraft(
    text.trim(),
    cas.input,
    extractProtectedSpans(cas.input),
    "personal",
    false,
  ).trim();
}

for (const row of rows) {
  const cas = byId.get(row.id);
  const scored = [];
  for (const cand of row.candidates) {
    if (!cand.text?.trim()) continue;
    nCandidates += 1;
    const text = candidateText(cas, cand.text);
    if (!text) continue;
    const s = await scoreCase(cas, text);
    const validation = productionSafety
      ? validateProtectedContent(cas.input, text, extractProtectedSpans(cas.input))
      : { safe: true };
    scored.push({
      ...s,
      temp: cand.temp,
      text,
      productionSafe: validation.safe,
      productionSafetyReason: validation.reason,
    });
  }
  const rank = (s) =>
    (s.passed ? 100 : 0) +
    s.metrics.cosineSim +
    0.01 * Math.max(0, Math.min(15, s.metrics.grammarGain)) +
    (s.metrics.editDistanceRatio >= 0.08 && s.metrics.editDistanceRatio <= 0.65 ? 0.05 : 0) -
    s.temp * 0.001;
  scored.sort((a, b) => rank(b) - rank(a));
  const winner = scored.find((s) => s.passed && s.productionSafe)
    ?? scored.find((s) => s.temp === 0 && s.productionSafe)
    ?? scored.find((s) => s.productionSafe)
    ?? (productionSafety ? undefined : scored.find((s) => s.passed) ?? scored.find((s) => s.temp === 0) ?? scored[0]);
  if (winner?.passed && winner.productionSafe) nPassFirst += 1;
  const totalSeconds = row.candidates
    .map((candidate) => candidate.seconds)
    .filter((seconds) => Number.isFinite(seconds))
    .reduce((sum, seconds) => sum + seconds, 0);
  out.push({
    id: row.id,
    output: winner?.text ?? "",
    pickedTemp: winner?.temp,
    seconds: winner?.seconds,
    totalSeconds,
    productionSafe: winner?.productionSafe ?? false,
  });
}

fs.writeFileSync(outFile, out.map((r) => JSON.stringify(r)).join("\n"));
console.log(`selected ${out.length} winners from ${nCandidates} usable candidates; ${nPassFirst} cases have a gate-passing candidate${productionPostprocess ? " after Pari finalization" : ""} -> ${outFile}`);
