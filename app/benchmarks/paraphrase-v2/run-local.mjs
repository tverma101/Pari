/** Generate the deterministic local-safe reference on the v2 corpus. */
import fs from "fs";
import os from "os";
import path from "path";
import vm from "vm";
import { createRequire } from "module";
import ts from "typescript";
import {
  DEFAULT_CORPUS_PATH,
  loadV2Corpus,
  resolveRepoPath,
  validateV2Corpus,
  loadV2Sources,
  ROOT_DIR,
} from "./schema.mjs";

const args = process.argv.slice(2);
function argValue(flag) {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

const corpusPath = resolveRepoPath(argValue("--corpus"), DEFAULT_CORPUS_PATH);
const corpusData = loadV2Corpus(corpusPath);
const validation = validateV2Corpus(corpusData, loadV2Sources());
if (!validation.valid) throw new Error(`v2 corpus is invalid: ${validation.errors.join("; ")}`);

const outPath = path.resolve(argValue("--out") ?? path.join(ROOT_DIR, "benchmarks/paraphrase-v2/results/local-safe-engine.jsonl"));
const strength = Number(argValue("--strength") ?? 60);
if (!Number.isFinite(strength) || strength < 0 || strength > 100) throw new Error("--strength must be between 0 and 100");
fs.mkdirSync(path.dirname(outPath), { recursive: true });

const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();
function resolveFile(basePath) {
  for (const candidate of [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`Cannot resolve ${basePath}`);
}
function resolveModule(specifier, fromFile) {
  if (specifier.startsWith("@/")) return resolveFile(path.join(ROOT_DIR, "src", specifier.slice(2)));
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

const { generateLocalParaphrase } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/localParaphrase.ts"));
const { createEmptyPreferenceMemory } = loadTsModule(path.join(ROOT_DIR, "src/lib/personalization/approvalMemory.ts"));
const memory = createEmptyPreferenceMemory();
const doneIds = new Set();
if (fs.existsSync(outPath)) {
  for (const line of fs.readFileSync(outPath, "utf8").split("\n").filter(Boolean)) {
    try { doneIds.add(JSON.parse(line).id); } catch { /* leave malformed rows visible for manual cleanup */ }
  }
}

const startedAt = performance.now();
const rows = [];
const handle = fs.openSync(outPath, "a");
try {
  for (const item of corpusData.cases) {
    if (doneIds.has(item.id)) continue;
    const caseStarted = performance.now();
    let result;
    try {
      result = await generateLocalParaphrase({
        originalText: item.input,
        examples: [],
        memory,
        mode: "personal",
        strength,
      });
    } catch (error) {
      result = {
        text: "",
        source: "local-safe-engine",
        safe: false,
        retryCount: 0,
        notice: error instanceof Error ? error.message : String(error),
      };
    }
    const row = {
      id: item.id,
      output: result.text ?? "",
      seconds: Number(((performance.now() - caseStarted) / 1000).toFixed(3)),
      source: result.source,
      safe: Boolean(result.safe),
      retryCount: result.retryCount ?? 0,
      notice: result.notice,
    };
    fs.writeSync(handle, JSON.stringify(row) + "\n");
    rows.push(row);
    console.log(`${item.id.padEnd(7)} ${row.seconds.toFixed(3)}s ${row.output.slice(0, 88)}`);
  }
} finally {
  fs.closeSync(handle);
}

const metaPath = path.resolve(argValue("--metadata") ?? `${outPath}.meta.json`);
const meta = {
  schemaVersion: 1,
  benchmark: "pari-paraphrase-v2",
  generatedAt: new Date().toISOString(),
  corpusPath,
  corpusVersion: corpusData.version,
  caseCount: corpusData.cases.length,
  productInstruction: corpusData.defaultInstruction,
  engine: {
    name: "local-safe-engine",
    role: "deterministic-safety-reference",
    runtime: "Pari TypeScript local-safe engine",
    license: "project code; see repository license",
    quantization: "deterministic rules and synonym bank",
    installedEvidence: false,
  },
  settings: { strength, nativeModelUsed: false },
  hardware: {
    platform: process.platform,
    arch: process.arch,
    node: process.version,
    macOS: os.release(),
    totalMemoryGiB: Number((os.totalmem() / 1024 ** 3).toFixed(2)),
  },
  timing: {
    completedCases: rows.length,
    totalSeconds: Number(((performance.now() - startedAt) / 1000).toFixed(3)),
    medianCaseSeconds: median(rows.map((row) => row.seconds)),
    peakProcessRssGiB: Number((process.memoryUsage().rss / 1024 ** 3).toFixed(3)),
  },
};
fs.mkdirSync(path.dirname(metaPath), { recursive: true });
fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2) + "\n");
console.log(`[v2:local] wrote ${rows.length} rows -> ${outPath}`);
console.log(`[v2:local] metadata -> ${metaPath}`);

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return Number((sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2).toFixed(3));
}
