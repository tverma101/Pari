import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const DATASET = path.join(ROOT_DIR, "research/grammar-sources/ud-english-ewt/en_ewt-ud-test.conllu");
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveFile(basePath) {
  const candidates = [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`Cannot resolve ${basePath}`);
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
    if (specifier.startsWith("@/")) {
      return loadTsModule(path.join(ROOT_DIR, "src", specifier.slice(2)));
    }
    if (specifier.startsWith(".")) {
      return loadTsModule(path.resolve(path.dirname(absolutePath), specifier));
    }
    return nodeRequire(specifier);
  };
  const wrapper = `(function(exports, require, module, __filename, __dirname) {\n${output}\n})`;
  const compiled = vm.runInThisContext(wrapper, { filename: absolutePath });
  compiled(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(fs.existsSync(DATASET), "UD English EWT test split is missing; run npm run research:grammar:download");
const { grammarSafetyIssues } = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/grammar.ts"));
const texts = fs.readFileSync(DATASET, "utf8")
  .split(/\r?\n/)
  .filter((line) => line.startsWith("# text = "))
  .map((line) => line.slice("# text = ".length).trim())
  .filter((text) => text.split(/\s+/).length >= 6)
  .slice(0, 2_000);

assert(texts.length >= 1_000, `UD English EWT test split yielded only ${texts.length} usable sentences`);
let high = 0;
let medium = 0;
const examples = [];
for (const text of texts) {
  const issues = grammarSafetyIssues(text);
  if (issues.some((issue) => issue.severity === "high")) {
    high += 1;
    if (examples.length < 8) examples.push({ text, issues: issues.map((issue) => issue.id) });
  }
  if (issues.some((issue) => issue.severity === "medium")) medium += 1;
}

const highRate = high / texts.length;
const mediumRate = medium / texts.length;
assert(highRate <= 0.12, `Grammar validator high-severity false-positive rate is ${(highRate * 100).toFixed(2)}%: ${JSON.stringify(examples)}`);
assert(mediumRate <= 0.28, `Grammar validator medium-severity rate is ${(mediumRate * 100).toFixed(2)}%: ${JSON.stringify(examples)}`);
console.log(`[qa:grammar:ewt] sentences=${texts.length} high=${high} (${(highRate * 100).toFixed(2)}%) medium=${medium} (${(mediumRate * 100).toFixed(2)}%) PASS`);
