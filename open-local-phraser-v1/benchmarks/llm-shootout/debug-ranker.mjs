/**
 * Debug: run rankNativeCandidates outside the app against live worker output.
 */
import fs from "fs";
import path from "path";
import vm from "vm";
import { createRequire } from "module";
import ts from "typescript";

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

const { rankNativeCandidates } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/nativeCandidateRanker.ts"));
const { extractProtectedSpans } = loadTsModule(path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts"));

const originalText = "My ADHD makes it difficult for me to sustain attention for long periods, stay focused when there are distractions, organize tasks and assignments, and remember information or instructions. I can also have difficulty listening continuously during lectures and completing work that requires sustained mental effort. These symptoms can affect my test performance, note-taking, time management, and ability to keep up with longer assignments.";

// Live worker output captured earlier
const candidates = [
  { text: "My ADHD makes it difficult for me to sustain attention for long periods, stay focused when there are distractions, organize tasks and assignments, and remember information or instructions. I can also have difficulty listening continuously during lectures and completing work that requires sustained mental effort. These symptoms can affect my test performance, note-taking, time management, and ability to keep up with longer assignments.", temperature: 0.24 },
  { text: "My ADHD makes it difficult for me to sustain attention over long periods, maintain focus when distractions are present, organize tasks and assignments, and recall information or instructions. I also struggle with listening continuously during lectures and completing work that requires sustained mental effort. These symptoms can negatively impact my test performance, note-taking, time management, and ability to keep up with longer assignments.", temperature: 0.9 },
];

try {
  const ranked = await rankNativeCandidates(candidates, {
    originalText,
    protectedSpans: extractProtectedSpans(originalText),
    mode: "personal",
    structuralRepair: false,
    finalizeDraft: (text) => text,
    warmthPolish: false,
  });
  for (const r of ranked) {
    console.log(JSON.stringify({ temp: r.temperature, safe: r.safe, sim: Number(r.semanticScore.toFixed(3)), gain: Number(r.grammarGain.toFixed(2)), text: r.text.slice(0, 70) }));
  }
} catch (error) {
  console.error("RANKER THREW:", error?.stack ?? error);
}
