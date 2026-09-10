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

const { extractProtectedSpans, validateProtectedContent } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts"),
);

const metreSource = "The cable is 5 m long.";
const spans = extractProtectedSpans(metreSource);
assert(
  spans.some((span) => span.kind === "number" && span.text === "5 m"),
  "SI metre measurement was not captured as one factual span",
);

assert.equal(
  validateProtectedContent(metreSource, "The cable is 5 ft long.", spans).safe,
  false,
  "metre-to-foot unit mutation was accepted",
);
assert.equal(
  validateProtectedContent(metreSource, "The 5 m cable is long.", spans).safe,
  true,
  "moving an unchanged metre measurement was falsely rejected",
);
assert.equal(
  validateProtectedContent("The cable is 5 m long.", "The cable is 6 m long.").safe,
  false,
  "metre quantity mutation was accepted",
);

console.log("qa:protected:units passed");
