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
  assert.deepEqual(found, [], `${label}: equivalent degree wording produced ${JSON.stringify(found)}`);
}

function expectDegreeDrift(original, candidate, label) {
  const found = issues(original, candidate);
  assert(
    found.some((issue) => issue.id === "degree-drift"),
    `${label}: degree/extent drift was accepted (${JSON.stringify(found)})`,
  );
}

expectSafe(
  "The interface barely changed.",
  "The interface hardly changed.",
  "barely-hardly near-zero equivalence",
);
expectSafe(
  "The interface scarcely changed.",
  "The interface barely changed.",
  "scarcely-barely near-zero equivalence",
);
expectSafe(
  "The new build is slightly faster.",
  "The new build is marginally faster.",
  "slightly-marginally small-degree equivalence",
);
expectSafe(
  "The result improved considerably.",
  "The result improved significantly.",
  "considerably-significantly large-degree equivalence",
);
expectSafe(
  "The result improved greatly.",
  "The result improved considerably.",
  "greatly-considerably large-degree equivalence",
);

expectDegreeDrift(
  "The interface barely changed.",
  "The interface slightly changed.",
  "near-zero strengthened to small degree",
);
expectDegreeDrift(
  "The new build is slightly faster.",
  "The new build is significantly faster.",
  "small degree strengthened to large degree",
);
expectDegreeDrift(
  "The result improved significantly.",
  "The result improved slightly.",
  "large degree weakened to small degree",
);
expectDegreeDrift(
  "The interface barely changed.",
  "The interface changed.",
  "near-zero qualifier deleted",
);
expectDegreeDrift(
  "The interface changed.",
  "The interface barely changed.",
  "near-zero qualifier invented",
);
expectDegreeDrift(
  "The result improved significantly.",
  "The result improved.",
  "large-degree qualifier deleted",
);

// Cambridge documents a separate parenthetical sense of "significantly" that
// signals special meaning rather than amount/degree. Do not let the simple
// degree contract hard-fail a discourse-word paraphrase in that frame.
expectSafe(
  "Significantly, the report omitted the date.",
  "Notably, the report omitted the date.",
  "parenthetical significantly excluded from degree contract",
);

console.log("qa:meaning:degree passed");
