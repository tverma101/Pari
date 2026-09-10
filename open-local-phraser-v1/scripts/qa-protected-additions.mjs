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

function expectSafe(original, candidate, label) {
  const result = validateProtectedContent(original, candidate, extractProtectedSpans(original));
  assert.equal(result.safe, true, `${label}: safe rewrite rejected ${JSON.stringify(result)}`);
}

function expectUnsafeKind(original, candidate, kind, label) {
  const result = validateProtectedContent(original, candidate, extractProtectedSpans(original));
  assert.equal(result.safe, false, `${label}: invented ${kind} was accepted`);
  assert.match(
    result.reason ?? "",
    new RegExp(`unsupported ${kind}`, "i"),
    `${label}: wrong failure reason ${JSON.stringify(result)}`,
  );
}

expectUnsafeKind(
  "Read the documentation before editing.",
  "Read https://example.org before editing.",
  "url",
  "invented URL",
);
expectUnsafeKind(
  "Contact the support team for help.",
  "Contact help@example.org for help.",
  "email",
  "invented email",
);
expectUnsafeKind(
  "The draft is ready for review.",
  "The draft is \"ready\" for review.",
  "quote",
  "invented quotation",
);
expectUnsafeKind(
  "The result is documented in the report.",
  "The result is documented in the report [source].",
  "citation",
  "invented bracket citation",
);

expectSafe(
  "Read https://example.org before editing.",
  "Before editing, read https://example.org.",
  "existing URL moved",
);
expectSafe(
  "Email help@example.org after class.",
  "After class, email help@example.org.",
  "existing email moved",
);
expectSafe(
  "The label says \"ready\" in the current draft.",
  "In the current draft, the label says \"ready\".",
  "existing quotation moved",
);
expectSafe(
  "The result is documented [source].",
  "As documented [source], the result is available.",
  "existing bracket citation moved",
);
expectSafe(
  "The draft is ready for review.",
  "The draft is ready to be reviewed.",
  "ordinary anchor-free rewrite",
);

console.log("qa:protected:additions passed");
