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
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
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

const { meaningContractIssues } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/generation/meaningContract.ts"),
);

function issues(original, candidate) {
  return meaningContractIssues(original, candidate);
}

function expectSafe(original, candidate, label) {
  const found = issues(original, candidate);
  assert.deepEqual(found, [], `${label}: equivalent frequency wording produced ${JSON.stringify(found)}`);
}

function expectFrequencyDrift(original, candidate, label) {
  const found = issues(original, candidate);
  assert(
    found.some((issue) => issue.id === "frequency-drift"),
    `${label}: frequency change was accepted (${JSON.stringify(found)})`,
  );
}

expectSafe(
  "I often review the draft.",
  "I frequently review the draft.",
  "often-frequently equivalence",
);
expectSafe(
  "He hardly ever misses class.",
  "He rarely misses class.",
  "hardly-ever-rarely equivalence",
);
expectSafe(
  "He seldom misses class.",
  "He hardly ever misses class.",
  "seldom-hardly-ever equivalence",
);
expectSafe(
  "I never skip the review.",
  "I do not ever skip the review.",
  "never-not-ever equivalence",
);

// The frequency phrase must not leak into the degree contract. This is the
// cross-family regression that motivated the dedicated frequency collector.
const hardlyEver = issues(
  "He hardly ever misses class.",
  "He rarely misses class.",
);
assert(
  !hardlyEver.some((issue) => issue.id === "degree-drift"),
  `hardly ever was incorrectly treated as degree: ${JSON.stringify(hardlyEver)}`,
);
assert(
  !hardlyEver.some((issue) => issue.id === "negation-drift"),
  `hardly ever/rarely equivalence changed negative force: ${JSON.stringify(hardlyEver)}`,
);

expectFrequencyDrift(
  "I sometimes review the draft.",
  "I always review the draft.",
  "sometimes strengthened to always",
);
expectFrequencyDrift(
  "I occasionally review the draft.",
  "I often review the draft.",
  "occasional strengthened to frequent",
);
expectFrequencyDrift(
  "I usually review the draft.",
  "I always review the draft.",
  "usual strengthened to universal frequency",
);
expectFrequencyDrift(
  "I often review the draft.",
  "I sometimes review the draft.",
  "frequent weakened to sometimes",
);
expectFrequencyDrift(
  "I frequently review the draft.",
  "I review the draft.",
  "frequency marker deleted",
);
expectFrequencyDrift(
  "I review the draft.",
  "I frequently review the draft.",
  "frequency marker invented",
);

// Ordinary near-zero degree remains distinct from the frequency expression.
expectSafe(
  "I could hardly hear the speaker.",
  "I could barely hear the speaker.",
  "hardly-barely degree equivalence outside hardly-ever",
);

console.log("qa:meaning:frequency passed");
