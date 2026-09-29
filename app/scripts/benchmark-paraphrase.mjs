import fs from "fs";
import path from "path";
import vm from "vm";
import { createRequire } from "module";

import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
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

const { generateLocalParaphrase } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/generation/localParaphrase.ts")
);
const { createEmptyPreferenceMemory } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/personalization/approvalMemory.ts")
);
const { countSentences, countWords } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/phraseEngine/rewriteText.ts")
);
const { extractProtectedSpans, validateProtectedContent } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts")
);
const { validateRewriteQuality } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/generation/rewriteQuality.ts")
);

const baselinePath = path.join(ROOT_DIR, "tests/fixtures/final-communication-reflection.txt");
const baseline = fs.readFileSync(baselinePath, "utf8").trim();
const eyewitnessFixturePath = path.join(ROOT_DIR, "tests/fixtures/eyewitness-evidence-start.txt");
const eyewitnessFixture = fs.readFileSync(eyewitnessFixturePath, "utf8").trim();

const variedSamples = [
  "The research team revised the proposal after reviewers identified two gaps in the evidence.",
  "Because the service runs offline, the editor can keep private notes on the laptop instead of uploading them.",
  "I was frustrated when the deadline changed, but I asked for clarification before responding.",
  "The class discussed whether silence communicates agreement, uncertainty, or respect in different settings.",
  "Our group met on Tuesday, divided the presentation into three parts, and finished the slides before Friday.",
  "Do not remove the 42.5% result, the 2024 date, Maya Chen, or https://example.com/report.",
  "The manager said, \"Please send the final draft after you check the figures.\"",
  "A clear explanation should define the problem, acknowledge limits, and give readers a practical next step.",
  "When students compare sources, they are less likely to treat the first interpretation as certain.",
  "The tool helps writers organize ideas without forcing every sentence into the same formal style.",
  "Although the method is simple, it may take time to understand how the parts work together.",
  "Our volunteers listened carefully, asked respectful questions, and changed the plan when new information appeared.",
  "The manager asked me to follow up with the client tomorrow.",
  "The students were asked to compare the sources and explain their reasoning.",
  "We need to take the cultural context into account.",
  "The conversation turned into an argument after the misunderstanding.",
  "I appreciate your help with this project.",
  "This change could lead to better communication between the groups.",
  "The teacher gave feedback on my paragraph.",
  "This approach protects their original ideas.",
  "I asked for more time after the deadline changed.",
  "Our group used Microsoft Teams to coordinate the project and divide the work.",
  "I helped clean the room without being asked, and I asked questions when the instructions were unclear.",
  "The presentation depended on strong eye contact and effective communication.",
  "Clear responsibilities helped the group, and our relationships and groups improved over time.",
  "The team made a decision after comparing the risks and took responsibility for the final plan.",
  "The workshop helped students practice listening instead of waiting to be asked questions.",
];

const corpus = [
  { name: "reflection-baseline", text: baseline },
  { name: "eyewitness-evidence-fixture", text: eyewitnessFixture },
  ...variedSamples.map((text, index) => ({ name: `varied-${String(index + 1).padStart(2, "0")}`, text })),
];

const ARTIFACT_PATTERNS = [
  /\b([A-Za-z]+)\s+\1\b/i,
  /\b(?:applied|employed|utilized)\s+(?:[A-Za-z-]+\s+)?applications?\b/i,
  /\b(?:guide|assist|aid|support)\s+(?:me|us|you|him|her|them)\s+[A-Za-z]+\b/i,
  /\b(?:some|any)\s+times\b/i,
  /\b(?:sluggish|gradual|leisurely|unhurried)\s+(?:down|up|off|on)\b/i,
  /\b(?:make clear|make evident)\s+(?:respect|uncertainty|thought|behavior)\b/i,
  /\b(?:inquire|request)\s+(?:respectful|clear|direct)\s+questions?\b/i,
  /\bwithout\s+(?:contribute|provide|offer)\b/i,
  /\bbody\s+(?:speech|tongue)\b/i,
  /\b(?:drew on|turned to)\s+(?:different|varied|contrasting|clear|strong|good)\b/i,
  /\b(?:invited|requested|inquired|encouraged)\s+(?:clean|organize|review|revise|read|write)\b/i,
  /\breadable\s+(?:expectations|behavior|respect|ideas?)\b/i,
  /\bwithout being (?:invited|questioned)\b/i,
  /\b(?:sought|requested|inquired)\s+for\b/i,
  /\b(?:powerful|potent|robust|convincing|compelling|solid|persuasive)\s+eye\s+contact\b/i,
  /\b(?:drew on|turned to|relied on)\s+Microsoft Teams\b/i,
  /\bwithout being (?:sought|requested|questioned|inquired)\b/i,
  /\b(?:sought|requested|inquired|questioned)\s+questions?\b/i,
  /\b(?:direct|understandable|specific)\s+responsibilities\b/i,
  /\b(?:connections?|relations?|bonds)\s+and\s+groups\b/i,
  /\b(?:potent|powerful|robust)\s+communication\b/i,
];

function normalizedTokens(value) {
  return value.toLowerCase().match(/[a-z]+(?:[-'][a-z]+)*/g) ?? [];
}

function lexicalChangeRate(original, output) {
  const originalTokens = normalizedTokens(original);
  const outputTokens = normalizedTokens(output);
  const remaining = new Map();
  for (const token of originalTokens) remaining.set(token, (remaining.get(token) ?? 0) + 1);
  let unchanged = 0;
  for (const token of outputTokens) {
    const count = remaining.get(token) ?? 0;
    if (count > 0) {
      unchanged += 1;
      remaining.set(token, count - 1);
    }
  }
  return originalTokens.length === 0 ? 0 : Math.max(0, 1 - unchanged / originalTokens.length);
}

function anchorValues(value) {
  return [
    ...(value.match(/https?:\/\/[^\s)]+/gi) ?? []),
    ...(value.match(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g) ?? []),
    ...(value.match(/\b\d+(?:\.\d+)?%?\b/g) ?? []),
    ...(value.match(/\b[A-Z]{2,}(?:\s+[A-Z][a-z]+)?\b/g) ?? []),
    ...(value.match(/[“\"]([^”\"]+)[”\"]/g) ?? []),
  ].map((value) => value.toLowerCase());
}

function missingAnchors(original, output) {
  const outputAnchors = new Set(anchorValues(output));
  return anchorValues(original).filter((anchor) => !outputAnchors.has(anchor));
}

function artifactLabels(output) {
  const labels = [];
  if (ARTIFACT_PATTERNS[0].test(output)) labels.push("repeated word");
  if (ARTIFACT_PATTERNS[1].test(output)) labels.push("application collision");
  if (ARTIFACT_PATTERNS[2].test(output)) labels.push("bare pronoun complement");
  if (ARTIFACT_PATTERNS[3].test(output)) labels.push("some-times split");
  if (ARTIFACT_PATTERNS[4].test(output)) labels.push("particle mismatch");
  if (ARTIFACT_PATTERNS[5].test(output)) labels.push("make-clear complement");
  if (ARTIFACT_PATTERNS[6].test(output)) labels.push("question complement");
  if (ARTIFACT_PATTERNS[7].test(output)) labels.push("invalid without phrase");
  if (ARTIFACT_PATTERNS[8].test(output)) labels.push("body-language collision");
  if (ARTIFACT_PATTERNS[9].test(output)) labels.push("resource/adjective collision");
  if (ARTIFACT_PATTERNS[10].test(output)) labels.push("invitation complement");
  if (ARTIFACT_PATTERNS[11].test(output)) labels.push("readable-noun collision");
  if (ARTIFACT_PATTERNS[12].test(output)) labels.push("asked semantic drift");
  if (ARTIFACT_PATTERNS[13].test(output)) labels.push("invalid verb-preposition pair");
  if (ARTIFACT_PATTERNS[14].test(output)) labels.push("eye-contact collocation");
  if (ARTIFACT_PATTERNS[15].test(output)) labels.push("named-tool collocation");
  if (ARTIFACT_PATTERNS[16].test(output)) labels.push("passive-asked collocation");
  if (ARTIFACT_PATTERNS[17].test(output)) labels.push("asked-questions collocation");
  if (ARTIFACT_PATTERNS[18].test(output)) labels.push("responsibilities collocation");
  if (ARTIFACT_PATTERNS[19].test(output)) labels.push("relationships collocation");
  if (ARTIFACT_PATTERNS[20].test(output)) labels.push("communication collocation");
  return labels;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function benchmarkPersonal(level, strength) {
  const memory = createEmptyPreferenceMemory();
  const results = [];
  for (const sample of corpus) {
    const protectedSpans = extractProtectedSpans(sample.text);
    const started = performance.now();
    const result = await generateLocalParaphrase({
      originalText: sample.text,
      examples: [],
      memory,
      mode: "personal",
      strength,
    });
    const durationMs = Math.round(performance.now() - started);
    const artifacts = artifactLabels(result.text);
    const missing = missingAnchors(sample.text, result.text);
    const safe = validateProtectedContent(sample.text, result.text, protectedSpans).safe;
    const quality = validateRewriteQuality(sample.text, result.text, protectedSpans);
    const sentenceDelta = countSentences(result.text) - countSentences(sample.text);
    const item = {
      name: sample.name,
      inputWords: countWords(sample.text),
      outputWords: countWords(result.text),
      lexicalChangeRate: Number(lexicalChangeRate(sample.text, result.text).toFixed(3)),
      sentenceDelta,
      protectedSafe: safe,
      qualitySafe: quality.safe,
      qualityIssues: quality.issues.map((issue) => issue.id),
      anchorCount: anchorValues(sample.text).length,
      missingAnchors: missing,
      artifacts,
      durationMs,
      retries: result.retryCount,
    };
    results.push(item);
    assert(quality.safe, "personal-" + level + "/" + sample.name + ": quality issues " + quality.issues.map((issue) => issue.id).join(", "));
    if (!result.safe || !safe || !quality.safe || sentenceDelta !== 0 || missing.length > 0 || artifacts.length > 0) {
      console.log(`[benchmark:failure] personal-${level}/${sample.name} ${JSON.stringify(item)} notice=${result.notice ?? "none"}\n${result.text}`);
    }
    assert(result.safe, `personal-${level}/${sample.name}: generation was not safe`);
    assert(safe, `personal-${level}/${sample.name}: protected content changed`);
    assert(sentenceDelta === 0, `personal-${level}/${sample.name}: sentence count changed by ${sentenceDelta}`);
    assert(missing.length === 0, `personal-${level}/${sample.name}: missing anchors ${missing.join(", ")}`);
    assert(artifacts.length === 0, `personal-${level}/${sample.name}: quality artifacts ${artifacts.join(", ")}`);
  }
  return results;
}

const personalRuns = [];
for (const [level, strength] of [
  ["light", 16],
  ["balanced", 40],
  ["strong", 60],
  ["deep", 90],
]) {
  personalRuns.push({ name: level, results: await benchmarkPersonal(level, strength) });
}

function summarize(name, results) {
  const changed = results.filter((item) => item.lexicalChangeRate > 0).length;
  const meanChange = results.reduce((sum, item) => sum + item.lexicalChangeRate, 0) / results.length;
  const maxChange = Math.max(...results.map((item) => item.lexicalChangeRate));
  const meanMs = results.reduce((sum, item) => sum + item.durationMs, 0) / results.length;
  console.log(
    `[benchmark:${name}] samples=${results.length} changed=${changed}/${results.length} ` +
      `meanLexicalChange=${meanChange.toFixed(3)} maxLexicalChange=${maxChange.toFixed(3)} ` +
      `meanMs=${Math.round(meanMs)}`
  );
}

for (const run of personalRuns) summarize(`personal-${run.name}`, run.results);
console.log(
  `[benchmark:baseline] words=${personalRuns[1].results[0].inputWords} ` +
    `lexicalChange=${personalRuns[1].results[0].lexicalChangeRate} ` +
    `outputWords=${personalRuns[1].results[0].outputWords} retries=${personalRuns[1].results[0].retries}`
);
console.log("[benchmark:quality] personal-levels=4 protected=100% sentence-count=100% artifacts=0 PASS");
