import fs from "fs";
import path from "path";
import vm from "vm";
import { createRequire } from "module";

import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveFile(basePath) {
  const candidates = [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`, `${basePath}.json`];
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
    const resolved = resolveModule(specifier, absolutePath);
    return resolved ? loadTsModule(resolved) : nodeRequire(specifier);
  };
  const wrapper = `(function(exports, require, module, __filename, __dirname) {\n${output}\n})`;
  const compiled = vm.runInThisContext(wrapper, { filename: absolutePath });
  compiled(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function approximately(value, expected, tolerance = 0.001) {
  return Math.abs(value - expected) <= tolerance;
}

const rankerPath = path.join(ROOT_DIR, "src/lib/generation/nativeCandidateRanker.ts");
const {
  rewriteChangeProfile,
  strengthFitScore,
  sortRankedNativeCandidates,
} = loadTsModule(rankerPath);
const { meaningContractIssues } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/meaningContract.ts"));
const { repairSentenceFlow } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/sentenceFlow.ts"));

const issueIds = (original, candidate) => new Set(
  meaningContractIssues(original, candidate).map((issue) => issue.id),
);

const unchanged = rewriteChangeProfile(
  "The editor revised the paragraph carefully.",
  "The editor revised the paragraph carefully.",
);
assert(approximately(unchanged.lexicalChangeRate, 0), "Unchanged text reported lexical change");
assert(approximately(unchanged.orderChangeRate, 0), "Unchanged text reported order change");
assert(approximately(unchanged.combinedChangeRate, 0), "Unchanged text reported combined change");

const oneSubstitution = rewriteChangeProfile(
  "The editor revised the paragraph carefully.",
  "The editor refined the paragraph carefully.",
);
assert(oneSubstitution.lexicalChangeRate > 0.15 && oneSubstitution.lexicalChangeRate < 0.18, `One substitution lexical rate was ${oneSubstitution.lexicalChangeRate}`);
assert(oneSubstitution.orderChangeRate > 0.15 && oneSubstitution.orderChangeRate < 0.18, `One substitution order rate was ${oneSubstitution.orderChangeRate}`);

const clauseSource = "Because the deadline changed, the team revised the plan carefully.";
const clauseMoved = "The team revised the plan carefully because the deadline changed.";
const movedProfile = rewriteChangeProfile(clauseSource, clauseMoved);
assert(approximately(movedProfile.lexicalChangeRate, 0), `Clause movement looked lexical: ${movedProfile.lexicalChangeRate}`);
assert(movedProfile.orderChangeRate >= 0.35 && movedProfile.orderChangeRate <= 0.45, `Clause movement order rate was ${movedProfile.orderChangeRate}`);
assert(movedProfile.combinedChangeRate >= 0.15 && movedProfile.combinedChangeRate <= 0.2, `Clause movement combined rate was ${movedProfile.combinedChangeRate}`);

const naiveWordsA = clauseSource.toLowerCase().match(/[a-z0-9]+(?:['-][a-z0-9]+)*/g) ?? [];
const naiveWordsB = clauseMoved.toLowerCase().match(/[a-z0-9]+(?:['-][a-z0-9]+)*/g) ?? [];
let naiveChanged = Math.abs(naiveWordsA.length - naiveWordsB.length);
for (let index = 0; index < Math.min(naiveWordsA.length, naiveWordsB.length); index += 1) {
  if (naiveWordsA[index] !== naiveWordsB[index]) naiveChanged += 1;
}
const naiveRate = naiveChanged / Math.max(naiveWordsA.length, naiveWordsB.length, 1);
assert(naiveRate > 0.8, `Regression fixture no longer exposes the old position-shift inflation: ${naiveRate}`);
assert(movedProfile.combinedChangeRate < naiveRate * 0.25, "Clause movement is still dominated by token-position inflation");
assert(
  strengthFitScore(clauseSource, clauseMoved, 88) > strengthFitScore(clauseSource, clauseMoved, 12),
  "A real structural rewrite should fit a high rewrite amount better than a light one",
);

const ranked = sortRankedNativeCandidates([
  {
    text: "safe-weak-quality",
    semanticScore: 0.94,
    grammarGain: 0,
    strengthFitScore: 0.95,
    englishQualityScore: 0.78,
    learnedNli: true,
    learnedFluency: true,
    englishQualityReason: "qa",
    safe: true,
  },
  {
    text: "safe-strong-quality",
    semanticScore: 0.9,
    grammarGain: 0,
    strengthFitScore: 0.7,
    englishQualityScore: 0.84,
    learnedNli: true,
    learnedFluency: true,
    englishQualityReason: "qa",
    safe: true,
  },
  {
    text: "unsafe",
    semanticScore: 1,
    grammarGain: 1,
    strengthFitScore: 1,
    englishQualityScore: 1,
    learnedNli: true,
    learnedFluency: true,
    englishQualityReason: "qa",
    safe: false,
  },
]);
assert(ranked[0]?.text === "safe-strong-quality", "Meaningful English-quality advantage did not remain primary");
assert(ranked.at(-1)?.text === "unsafe", "Unsafe candidate outranked a safe candidate");

// Meaning-contract regressions are pure deterministic checks. They deliberately
// avoid the ONNX/embedding path so this QA remains useful on a machine with no
// inference assets installed.
for (const [source, expanded] of [
  ["The editor couldn't change the quote.", "The editor could not change the quote."],
  ["The editor couldn’t change the quote.", "The editor could not change the quote."],
  ["The editor won't change the quote.", "The editor will not change the quote."],
]) {
  const ids = issueIds(source, expanded);
  assert(!ids.has("modality-drift"), `Contraction expansion looked like modality drift: ${source}`);
  assert(!ids.has("negation-drift"), `Contraction expansion looked like negation drift: ${source}`);
}

assert(
  !issueIds("My draft needs work.", "I need to work on the draft.").has("point-of-view-drift"),
  "A first-person possessive recast looked like a speaker change",
);
const directAddressIds = issueIds("Their draft is ready.", "Your draft is ready.");
assert(directAddressIds.has("point-of-view-drift"), "Third-person to second-person drift was missed");
assert(directAddressIds.has("unexpected-direct-address"), "Invented direct address was missed");

assert(
  !issueIds("The tool is so useful for editing.", "The tool is extremely useful for editing.").has("discourse-relation-drift"),
  "Intensifier 'so' was misread as a causal connector",
);
assert(
  issueIds("The deadline moved, so we revised the plan.", "The deadline moved, but we revised the plan.").has("discourse-relation-drift"),
  "Punctuation-delimited causal 'so' was not protected",
);
assert(
  issueIds("The team revised the plan because the deadline moved.", "The team revised the plan; therefore, the deadline moved.").has("discourse-relation-drift"),
  "Cause/result direction reversal was not rejected",
);
assert(
  issueIds("If the file exists, save it.", "Unless the file exists, save it.").has("discourse-relation-drift"),
  "If/unless polarity reversal was not rejected",
);
assert(
  issueIds("Before the meeting starts, send the draft.", "After the meeting starts, send the draft.").has("discourse-relation-drift"),
  "Before/after reversal was not rejected",
);
assert(
  issueIds("Even if the test passes, review the logs.", "If the test passes, review the logs.").has("discourse-relation-drift"),
  "Concessive force from 'even if' was silently weakened",
);
assert(
  !issueIds("Provided that the file exists, save it.", "If the file exists, save it.").has("discourse-relation-drift"),
  "Equivalent positive-condition markers were falsely rejected",
);

assert(
  issueIds("All students submitted the draft.", "Both students submitted the draft.").has("quantity-drift"),
  "All/both quantity drift was not rejected",
);
assert(
  issueIds("Only students can enter.", "All students can enter.").has("quantity-drift"),
  "Exclusive 'only' was treated as universal quantity",
);
assert(
  issueIds("Enough students responded.", "Some students responded.").has("quantity-drift"),
  "Sufficiency was treated as an open subset",
);
assert(
  !issueIds("Some students responded.", "Certain students responded.").has("quantity-drift"),
  "Some/certain open-subset rewrite was falsely rejected",
);

const restoredRelation = repairSentenceFlow(
  "The team kept working, although the deadline changed.",
  "The team kept working, the deadline changed again.",
);
assert(/, although the deadline changed again\./i.test(restoredRelation), `Dropped relation was not restored safely: ${restoredRelation}`);
assert(!/\bespecially\b/i.test(restoredRelation), `Relation repair invented emphasis: ${restoredRelation}`);
assert(/\bagain\b/i.test(restoredRelation), `Relation repair overwrote candidate clause content: ${restoredRelation}`);

const rankerSource = fs.readFileSync(rankerPath, "utf8");
const finalizeIndex = rankerSource.indexOf("const finalizedCandidates = candidates.map");
const embedFinalIndex = rankerSource.indexOf("...finalizedCandidates.map((candidate) => candidate.text)");
const rankFinalIndex = rankerSource.indexOf("finalizedCandidates.map(async (candidate, index)");
assert(finalizeIndex >= 0, "Ranker no longer pre-finalizes candidates before judging");
assert(embedFinalIndex > finalizeIndex, "Semantic embeddings are not based on finalized candidate text");
assert(rankFinalIndex > embedFinalIndex, "Ranker is not judging the same finalized candidates it embedded");

console.log("qa:native:ranker passed");
