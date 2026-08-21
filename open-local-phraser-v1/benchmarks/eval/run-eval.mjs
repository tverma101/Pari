/**
 * Pari adversarial eval runner.
 *
 * Usage:
 *   node benchmarks/eval/run-eval.mjs                       # engine = built-in generateLocalParaphrase
 *   node benchmarks/eval/run-eval.mjs --outputs out.jsonl   # score external outputs ({id, output} lines)
 *
 * Exit code 1 if hard gates fail (meaning floor, anchors, negation, new grammar errors).
 */
import fs from "fs";
import path from "path";
import vm from "vm";
import { createRequire } from "module";
import ts from "typescript";
import {
  scoreCase,
  grammarErrorRate,
} from "./metrics.mjs";

const ROOT_DIR = path.resolve(new URL("../..", import.meta.url).pathname);
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveFile(basePath) {
  const candidates = [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`];
  for (const candidate of candidates) {
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
  const compiled = vm.runInThisContext(wrapper, { filename: absolutePath });
  compiled(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

const args = process.argv.slice(2);
function argValue(flag) {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : undefined;
}

const corpus = JSON.parse(fs.readFileSync(path.join(ROOT_DIR, "benchmarks/eval/corpus.json"), "utf8")).cases;

async function main() {
  let outputs; // Map<id, string>
  let engineName;

  const outputsPath = argValue("--outputs");
  if (outputsPath) {
    engineName = path.basename(outputsPath);
    outputs = new Map();
    for (const line of fs.readFileSync(outputsPath, "utf8").split("\n").filter(Boolean)) {
      const row = JSON.parse(line);
      outputs.set(row.id, row.output);
    }
  } else {
    const { generateLocalParaphrase } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/localParaphrase.ts"));
    const { createEmptyPreferenceMemory } = loadTsModule(path.join(ROOT_DIR, "src/lib/personalization/approvalMemory.ts"));
    engineName = "local-safe-engine";
    const memory = createEmptyPreferenceMemory();
    outputs = new Map();
    for (const cas of corpus) {
      try {
        const result = await generateLocalParaphrase({
          originalText: cas.input,
          examples: [],
          memory,
          mode: "personal",
          strength: 60,
        });
        outputs.set(cas.id, result.text);
      } catch (error) {
        outputs.set(cas.id, "");
        console.error(`[engine-error] ${cas.id}: ${error.message}`);
      }
    }
  }

  const results = [];
  for (const cas of corpus) {
    const output = (outputs.get(cas.id) ?? "").trim();
    if (!output) {
      results.push({ id: cas.id, category: cas.category, passed: false, empty: true, failedChecks: ["empty-output"] });
      continue;
    }
    const scored = await scoreCase(cas, output);
    scored.output = output;
    results.push(scored);
  }

  // Aggregate
  const byCategory = {};
  for (const r of results) {
    byCategory[r.category] ??= { total: 0, passed: 0 };
    byCategory[r.category].total += 1;
    if (r.passed) byCategory[r.category].passed += 1;
  }
  const totalPassed = results.filter((r) => r.passed).length;

  console.log(`\n=== Pari adversarial eval — engine: ${engineName} ===`);
  for (const [cat, agg] of Object.entries(byCategory)) {
    const pct = ((agg.passed / agg.total) * 100).toFixed(0);
    console.log(`${cat.padEnd(16)} ${String(agg.passed).padStart(2)}/${agg.total}  (${pct}%)`);
  }
  console.log(`OVERALL          ${totalPassed}/${results.length}  (${((totalPassed / results.length) * 100).toFixed(0)}%)\n`);

  for (const r of results.filter((r) => !r.passed)) {
    const m = r.metrics ?? {};
    console.log(
      `[FAIL] ${r.id} (${r.category}) checks=${(r.failedChecks ?? []).join(",")} ` +
      `sim=${m.cosineSim ?? "-"} gain=${m.grammarGain ?? "-"} edit=${m.editDistanceRatio ?? "-"} overlap=${m.contentOverlap ?? "-"}` +
      (r.missingAnchors?.length ? ` missingAnchors=${JSON.stringify(r.missingAnchors)}` : "")
    );
    console.log(`       IN : ${(corpus.find((c) => c.id === r.id)?.input ?? "").slice(0, 110)}`);
    console.log(`       OUT: ${(r.output ?? "").slice(0, 110)}`);
  }

  // Hard gates: guards must never fail. Band-fit is reported but not fatal yet.
  const guardFailures = results.filter(
    (r) => r.failedChecks?.some((c) => ["anchorSafe", "negationSafe", "noNewErrors", "meaningFloor"].includes(c))
  );
  const outPath = argValue("--out") ?? path.join(ROOT_DIR, `benchmarks/eval/results-${engineName.replace(/[^\w.-]/g, "_")}.json`);
  fs.writeFileSync(outPath, JSON.stringify({ engine: engineName, generatedAt: new Date().toISOString(), byCategory, overall: { passed: totalPassed, total: results.length }, results }, null, 2));
  console.log(`saved -> ${outPath}`);

  if (guardFailures.length > 0) {
    console.error(`\nHARD GATE FAILURE: ${guardFailures.length} case(s) violated meaning/anchor/negation/grammar guards.`);
    process.exit(1);
  }
}

await main();
