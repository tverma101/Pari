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
  for (const candidate of [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`Cannot resolve ${basePath}`);
}

function loadTsModule(filePath) {
  const absolutePath = resolveFile(filePath);
  if (moduleCache.has(absolutePath)) return moduleCache.get(absolutePath).exports;
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

async function main() {
  const { assessEnglishQuality, assessEnglishQualityWithOnnx } = loadTsModule(
    path.join(ROOT_DIR, "src/lib/scoring/englishQuality.ts")
  );
  const { scoreNli, scoreNliBidirectional } = loadTsModule(
    path.join(ROOT_DIR, "src/lib/scoring/onnxNli.ts")
  );
  const { sortRankedNativeCandidates } = loadTsModule(
    path.join(ROOT_DIR, "src/lib/generation/nativeCandidateRanker.ts")
  );

  const source = "The curator mailed the rare manuscript to the archive.";
  const roleSwap = "The archive mailed the rare manuscript to the curator.";
  const natural = "The committee approved the proposal after a long discussion.";
  const awkward = "The committee after a long discussion approved proposal the.";

  const directContradiction = await scoreNli(source, roleSwap);
  assert.equal(directContradiction.label, "contradict", "DeBERTa label mapping must identify contradiction");
  assert.equal(directContradiction.hardContradiction, true, "strong contradiction must be a hard veto");

  const bidirectional = await scoreNliBidirectional(
    source,
    "The curator sent the manuscript to the archive."
  );
  assert.match(bidirectional.reason, /reverse/, "both NLI directions must be exercised");

  const naturalQuality = await assessEnglishQuality(natural, natural);
  const awkwardQuality = await assessEnglishQuality(natural, awkward);
  assert.equal(naturalQuality.learnedNli, true, "production quality must run learned NLI");
  assert.equal(naturalQuality.learnedFluency, true, "production quality must run learned fluency");
  assert.ok(
    naturalQuality.fluencyScore > awkwardQuality.fluencyScore + 0.05,
    `masked-LM fluency should prefer natural English (${naturalQuality.fluencyScore} <= ${awkwardQuality.fluencyScore})`
  );

  const roleQuality = await assessEnglishQuality(source, roleSwap);
  assert.equal(roleQuality.entailment, "contradict", "unseen subject/object reversal must be rejected");

  const repairedContraction = await assessEnglishQuality(
    "i dont know what happened, but it looked like the meeting went badly",
    "I don't know what happened, but it looked like the meeting went badly."
  );
  assert.notEqual(repairedContraction.entailment, "contradict", "misspelled contractions must not trigger a false contradiction");

  const explicitNegationFlip = await assessEnglishQuality(
    "The proposal was approved.",
    "The proposal was not approved."
  );
  assert.equal(explicitNegationFlip.entailment, "contradict", "direct negation flips must remain hard failures");

  const formattingOnly = await assessEnglishQuality(
    "The doctor prescribed 50mg twice daily after meals.",
    "The doctor prescribed 50 mg twice daily after meals."
  );
  assert.notEqual(formattingOnly.entailment, "contradict", "spacing-only numeric repairs must not be rejected as meaning drift");

  const awkwardCandidate = {
    text: roleSwap,
    semanticScore: 0.96,
    grammarGain: 4,
    englishQualityScore: 0.61,
    learnedNli: true,
    learnedFluency: true,
    englishQualityReason: "synthetic awkward candidate",
    safe: true,
  };
  const naturalCandidate = {
    text: natural,
    semanticScore: 0.81,
    grammarGain: 2,
    englishQualityScore: 0.88,
    learnedNli: true,
    learnedFluency: true,
    englishQualityReason: "synthetic natural candidate",
    safe: true,
  };
  const ranked = sortRankedNativeCandidates([awkwardCandidate, naturalCandidate]);
  assert.equal(ranked[0].text, natural, "learned English quality must outrank MiniLM similarity");

  const nliUnavailable = await assessEnglishQualityWithOnnx(
    natural,
    natural,
    async () => { throw new Error("synthetic NLI outage"); }
  );
  assert.equal(nliUnavailable.learnedNli, false, "NLI outage must be explicit");
  assert.equal(nliUnavailable.learnedFluency, true, "NLI outage must retain the independent fluency model");
  assert.match(nliUnavailable.reason, /nli unavailable/, "NLI fallback reason must be visible");

  console.log(JSON.stringify({
    model: "Xenova/nli-deberta-v3-xsmall + Xenova/distilbert-base-uncased",
    contradiction: directContradiction,
    natural: {
      englishQualityScore: naturalQuality.englishQualityScore,
      fluencyScore: naturalQuality.fluencyScore,
      learnedNli: naturalQuality.learnedNli,
      learnedFluency: naturalQuality.learnedFluency,
    },
    awkward: {
      englishQualityScore: awkwardQuality.englishQualityScore,
      fluencyScore: awkwardQuality.fluencyScore,
    },
    fallback: {
      learnedNli: nliUnavailable.learnedNli,
      learnedFluency: nliUnavailable.learnedFluency,
    },
  }, null, 2));
}

main().catch((error) => {
  console.error(`[qa:learned:judge] ${error.stack ?? error}`);
  process.exitCode = 1;
});
