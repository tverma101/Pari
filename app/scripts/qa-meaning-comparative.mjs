#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveFile(basePath) {
  for (const candidate of [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`, `${basePath}.json`]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`Cannot resolve ${basePath}`);
}

function loadTsModule(filePath) {
  const absolutePath = resolveFile(filePath);
  if (moduleCache.has(absolutePath)) return moduleCache.get(absolutePath).exports;
  if (absolutePath.endsWith(".json")) {
    const module = { exports: JSON.parse(fs.readFileSync(absolutePath, "utf8")) };
    moduleCache.set(absolutePath, module);
    return module.exports;
  }
  const source = fs.readFileSync(absolutePath, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { esModuleInterop: true, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: absolutePath,
  }).outputText;
  const module = { exports: {} };
  moduleCache.set(absolutePath, module);
  const localRequire = (specifier) => {
    if (specifier.startsWith("@/")) return loadTsModule(path.join(ROOT_DIR, "src", specifier.slice(2)));
    if (specifier.startsWith(".")) return loadTsModule(path.resolve(path.dirname(absolutePath), specifier));
    return nodeRequire(specifier);
  };
  const wrapper = `(function(exports, require, module, __filename, __dirname) {\n${output}\n})`;
  const compiled = vm.runInThisContext(wrapper, { filename: absolutePath });
  compiled(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

const { meaningContractIssues } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/meaningContract.ts"));

function found(original, candidate) {
  return meaningContractIssues(original, candidate);
}

function expectSafe(original, candidate, label) {
  const issues = found(original, candidate);
  assert.deepEqual(issues, [], `${label}: safe wording produced ${JSON.stringify(issues)}`);
}

function expectFlip(original, candidate, label) {
  const issues = found(original, candidate);
  assert(
    issues.some((issue) => issue.id === "comparative-direction-drift"),
    `${label}: direct comparative reversal was accepted (${JSON.stringify(issues)})`,
  );
}

expectFlip(
  "The new build is more reliable.",
  "The new build is less reliable.",
  "more-less adjective reversal",
);
expectFlip(
  "The update has higher cost.",
  "The update has lower cost.",
  "higher-lower noun reversal",
);
expectFlip(
  "More users completed the task.",
  "Fewer users completed the task.",
  "more-fewer count reversal",
);
expectFlip(
  "The change creates greater risk.",
  "The change creates smaller risk.",
  "greater-smaller noun reversal",
);
expectFlip(
  "The app responds more quickly.",
  "The app responds less quickly.",
  "more-less adverb reversal",
);

// Cambridge treats "more or less" as an approximation idiom, not a literal
// comparative polarity pair. It must stay outside this direct-reversal guard.
expectSafe(
  "The migration is more or less finished.",
  "The migration is approximately finished.",
  "more-or-less approximation idiom",
);

// Numeric bounds are already modeled with inclusive/exclusive quantity classes.
// Do not double-count their internal more/less token as a direct comparison.
expectSafe(
  "The room holds no more than 30 people.",
  "The room holds at most 30 people.",
  "no-more-than upper-bound equivalence",
);
expectSafe(
  "At least 10 users responded.",
  "No less than 10 users responded.",
  "no-less-than lower-bound equivalence",
);

// The deterministic guard requires the same lexical head. A changed-head
// paraphrase may be valid and remains for NLI/human evaluation rather than
// being rejected by a shallow polarity heuristic.
expectSafe(
  "The new build is more reliable.",
  "The new build is more dependable.",
  "changed-head paraphrase remains outside direct comparator",
);

console.log("qa:meaning:comparative passed");
