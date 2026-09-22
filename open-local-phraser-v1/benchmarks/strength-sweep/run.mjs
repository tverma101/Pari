/**
 * Deterministic strength sweep for Pari's local fallback.
 *
 * This is a diagnostic, not a human-quality score. It records visible change
 * alongside the same protected-content and rewrite-quality gates used by the
 * product, then emits a blinded review sheet for a human to judge naturalness.
 */
import fs from "fs";
import os from "os";
import path from "path";
import vm from "vm";
import { createRequire } from "module";
import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("../..", import.meta.url).pathname);
const CORPUS_PATH = path.join(ROOT_DIR, "benchmarks/strength-sweep/corpus.json");
const DEFAULT_OUT_DIR = path.join(ROOT_DIR, "benchmarks/strength-sweep/results");
const args = process.argv.slice(2);

function argValue(flag) {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

function parseStrengths() {
  const raw = argValue("--strengths") ?? Array.from({ length: 101 }, (_, index) => index).join(",");
  const values = raw.split(",").map((value) => Number(value.trim()));
  if (!values.length || values.some((value) => !Number.isFinite(value) || value < 0 || value > 100)) {
    throw new Error("--strengths must be comma-separated numbers from 0 to 100");
  }
  return [...new Set(values)].sort((left, right) => left - right);
}

const strengths = parseStrengths();
const outDir = path.resolve(argValue("--out-dir") ?? DEFAULT_OUT_DIR);
const corpus = JSON.parse(fs.readFileSync(CORPUS_PATH, "utf8"));
if (!Array.isArray(corpus.cases) || corpus.cases.length === 0) throw new Error("Synthetic corpus is empty");

const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();
function resolveFile(basePath) {
  for (const candidate of [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`, `${basePath}.json`]) {
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
  vm.runInThisContext(wrapper, { filename: absolutePath })(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

const { generateLocalParaphrase } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/localParaphrase.ts"));
const { createEmptyPreferenceMemory } = loadTsModule(path.join(ROOT_DIR, "src/lib/personalization/approvalMemory.ts"));
const { extractProtectedSpans, validateProtectedContent } = loadTsModule(path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts"));
const { validateRewriteQuality } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/rewriteQuality.ts"));
const { meaningContractIssues } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/meaningContract.ts"));
const { countSentences } = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/sentenceSplit.ts"));
const { countWords } = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/tokenizer.ts"));
const { scoreNliBidirectional } = loadTsModule(path.join(ROOT_DIR, "src/lib/scoring/onnxNli.ts"));
const learnedNliCache = new Map();

function tokens(value) {
  return value.toLowerCase().match(/[a-z]+(?:[-'][a-z]+)*/g) ?? [];
}

function lexicalChangeRate(original, output) {
  const originalTokens = tokens(original);
  const outputTokens = tokens(output);
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
  return originalTokens.length ? Math.max(0, 1 - unchanged / originalTokens.length) : 0;
}

function positionalChangeRate(original, output) {
  const left = tokens(original);
  const right = tokens(output);
  const length = Math.max(left.length, right.length);
  if (!length) return 0;
  let changed = Math.abs(left.length - right.length);
  for (let index = 0; index < Math.min(left.length, right.length); index += 1) {
    if (left[index] !== right[index]) changed += 1;
  }
  return changed / length;
}

function sharedTokenOrderChange(original, output) {
  const left = tokens(original);
  const right = tokens(output);
  const leftCounts = new Map();
  const rightCounts = new Map();
  for (const token of left) leftCounts.set(token, (leftCounts.get(token) ?? 0) + 1);
  for (const token of right) rightCounts.set(token, (rightCounts.get(token) ?? 0) + 1);
  let sharedCount = 0;
  for (const [token, count] of leftCounts) sharedCount += Math.min(count, rightCounts.get(token) ?? 0);
  if (sharedCount < 4) return false;

  // LCS distinguishes clause/sentence movement from lexical substitutions:
  // replacing words leaves shared words in order, while moving a clause does not.
  let previous = new Uint16Array(right.length + 1);
  for (const leftToken of left) {
    const current = new Uint16Array(right.length + 1);
    for (let index = 1; index <= right.length; index += 1) {
      current[index] = leftToken === right[index - 1]
        ? previous[index - 1] + 1
        : Math.max(previous[index], current[index - 1]);
    }
    previous = current;
  }
  return sharedCount - previous[right.length] >= 2;
}

function anchorValues(value) {
  return [
    ...(value.match(/https?:\/\/[^\s)]+/gi) ?? []),
    ...(value.match(/[“\"]([^”\"]+)[”\"]/g) ?? []),
    ...(value.match(/\b\d{4}-\d{1,2}-\d{1,2}\b/g) ?? []),
    ...(value.match(/\b\d+(?:\.\d+)?%?\b/g) ?? []),
    ...(value.match(/\$\d[\d,]*(?:\.\d+)?/g) ?? []),
    ...(value.match(/\b[A-Z][a-z]+ [A-Z][a-z]+\b/g) ?? []),
  ].map((value) => value.toLowerCase());
}

function missingAnchors(original, output) {
  const available = new Set(anchorValues(output));
  return [...new Set(anchorValues(original).filter((value) => !available.has(value)))];
}

function round(value, digits = 3) {
  return Number(value.toFixed(digits));
}

async function learnedNliAssessment(original, output) {
  if (original === output) {
    return { available: true, label: "entail", score: 1, hardContradiction: false, reason: "exact identity" };
  }
  const key = `${original}\u241f${output}`;
  if (learnedNliCache.has(key)) return learnedNliCache.get(key);
  try {
    const result = await scoreNliBidirectional(original, output);
    const assessment = {
      available: true,
      label: result.label,
      score: round(result.score),
      hardContradiction: Boolean(result.hardContradiction),
      reason: result.reason,
    };
    learnedNliCache.set(key, assessment);
    return assessment;
  } catch (error) {
    const assessment = {
      available: false,
      label: null,
      score: null,
      hardContradiction: null,
      reason: error instanceof Error ? error.message : String(error),
    };
    learnedNliCache.set(key, assessment);
    return assessment;
  }
}

function aggregate(rows) {
  const mean = (key) => rows.length ? round(rows.reduce((sum, row) => sum + row[key], 0) / rows.length) : 0;
  const changed = rows.filter((row) => row.lexicalChangeRate > 0);
  const eligible = rows.filter((row) => row.lexicalChangeRate > 0 && row.protectedSafe && row.qualitySafe && row.contractSafe);
  const nliEvaluated = changed.filter((row) => row.learnedNliAvailable);
  const nliContradictions = nliEvaluated.filter((row) => row.learnedNliHardContradiction);
  const meaningScreened = nliEvaluated.filter((row) =>
    row.protectedSafe && row.qualitySafe && row.contractSafe && !row.learnedNliHardContradiction
  );
  return {
    cases: rows.length,
    changed: changed.length,
    unchanged: rows.length - changed.length,
    changedRate: round(changed.length / Math.max(1, rows.length)),
    eligibleChanged: eligible.length,
    eligibleChangedRate: round(eligible.length / Math.max(1, rows.length)),
    meanLexicalChangeRate: mean("lexicalChangeRate"),
    meanPositionalChangeRate: mean("positionalChangeRate"),
    meanSentenceDelta: mean("sentenceDelta"),
    structuralChangeRate: round(rows.filter((row) => row.structureChanged).length / Math.max(1, rows.length)),
    sentenceCountChangeRate: round(rows.filter((row) => row.sentenceDelta !== 0).length / Math.max(1, rows.length)),
    tokenOrderChangeRate: round(rows.filter((row) => row.tokenOrderChanged).length / Math.max(1, rows.length)),
    protectedSafeRate: round(rows.filter((row) => row.protectedSafe).length / Math.max(1, rows.length)),
    qualitySafeRate: round(rows.filter((row) => row.qualitySafe).length / Math.max(1, rows.length)),
    contractSafeRate: round(rows.filter((row) => row.contractSafe).length / Math.max(1, rows.length)),
    learnedNliEvaluated: nliEvaluated.length,
    learnedNliAvailabilityRate: round(nliEvaluated.length / Math.max(1, changed.length)),
    learnedNliHardContradictions: nliContradictions.length,
    learnedNliHardContradictionRate: round(nliContradictions.length / Math.max(1, nliEvaluated.length)),
    meaningScreenedChanged: meaningScreened.length,
    meaningScreenedChangedRate: round(meaningScreened.length / Math.max(1, rows.length)),
    meanDurationMs: round(rows.reduce((sum, row) => sum + row.durationMs, 0) / Math.max(1, rows.length), 1),
  };
}

function strengthLabel(strength) {
  if (strength < 25) return "Light";
  if (strength < 50) return "Balanced";
  if (strength < 75) return "Strong";
  return "Deep";
}

const allRows = [];
for (const strength of strengths) {
  const memory = createEmptyPreferenceMemory();
  for (const item of corpus.cases) {
    const protectedSpans = extractProtectedSpans(item.input);
    const started = performance.now();
    let result;
    try {
      result = await generateLocalParaphrase({
        originalText: item.input,
        examples: [],
        memory,
        mode: "personal",
        strength,
      });
    } catch (error) {
      result = {
        text: "",
        source: "local-safe-engine",
        safe: false,
        retryCount: 0,
        notice: error instanceof Error ? error.message : String(error),
      };
    }
    const output = String(result.text ?? "").trim();
    const protection = validateProtectedContent(item.input, output, protectedSpans);
    const quality = validateRewriteQuality(item.input, output, protectedSpans, { allowStructuralRepair: true });
    const contract = meaningContractIssues(item.input, output, "personal");
    const learnedNli = await learnedNliAssessment(item.input, output);
    const sentenceDelta = countSentences(output) - countSentences(item.input);
    const tokenOrderChanged = sharedTokenOrderChange(item.input, output);
    const row = {
      id: item.id,
      category: item.category,
      strength,
      band: strengthLabel(strength),
      input: item.input,
      output,
      source: result.source,
      safe: Boolean(result.safe),
      protectedSafe: protection.safe,
      protectionReason: protection.reason,
      qualitySafe: quality.safe,
      qualityIssues: quality.issues.map((issue) => issue.id),
      contractSafe: contract.length === 0,
      contractIssues: contract.map((issue) => issue.id),
      learnedNliAvailable: learnedNli.available,
      learnedNliLabel: learnedNli.label,
      learnedNliScore: learnedNli.score,
      learnedNliHardContradiction: learnedNli.hardContradiction,
      learnedNliReason: learnedNli.reason,
      missingAnchors: missingAnchors(item.input, output),
      lexicalChangeRate: round(lexicalChangeRate(item.input, output)),
      positionalChangeRate: round(positionalChangeRate(item.input, output)),
      sentenceDelta,
      tokenOrderChanged,
      structureChanged: sentenceDelta !== 0 || tokenOrderChanged,
      inputWords: countWords(item.input),
      outputWords: countWords(output),
      durationMs: Math.round(performance.now() - started),
      retryCount: result.retryCount ?? 0,
      notice: result.notice,
    };
    allRows.push(row);
    if (!row.protectedSafe || !row.qualitySafe || !row.contractSafe || row.missingAnchors.length > 0) {
      console.log(`[strength-sweep:gate] ${strength}/${item.id} safe=${row.protectedSafe && row.qualitySafe && row.contractSafe} issues=${JSON.stringify({ quality: row.qualityIssues, contract: row.contractIssues, anchors: row.missingAnchors })}`);
    }
  }
  const rows = allRows.filter((row) => row.strength === strength);
  console.log(`[strength-sweep:${strengthLabel(strength)}:${strength}] ${JSON.stringify(aggregate(rows))}`);
}

const summaries = Object.fromEntries(strengths.map((strength) => [
  String(strength), aggregate(allRows.filter((row) => row.strength === strength)),
]));
const payload = {
  schemaVersion: 1,
  benchmark: "pari-strength-sweep",
  generatedAt: new Date().toISOString(),
  corpusPath: path.relative(ROOT_DIR, CORPUS_PATH),
  corpusVersion: corpus.schemaVersion,
  corpusCases: corpus.cases.length,
  strengths,
  runtime: { node: process.version, platform: process.platform, arch: process.arch, macOS: os.release() },
  judgeBoundary: "Automatic diagnostics only; human review decides meaning preservation, grammar, naturalness, structure, and usefulness.",
  structuralMetric: "Heuristic: sentence-count movement or at least two shared-token order inversions among four or more shared tokens. It detects restructuring, not quality.",
  summaries,
  rows: allRows,
};
fs.mkdirSync(outDir, { recursive: true });

const byId = new Map(allRows.map((row) => [`${row.id}/${row.strength}`, row]));
const csvEscape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const reviewBands = [
  { label: "Light", min: 0, max: 24, target: 16 },
  { label: "Balanced", min: 25, max: 49, target: 40 },
  { label: "Strong", min: 50, max: 74, target: 60 },
  { label: "Deep", min: 75, max: 100, target: 90 },
];
const selectedReviewStrengths = reviewBands.map((band) => {
  const available = strengths.filter((strength) => strength >= band.min && strength <= band.max);
  if (!available.length) return null;
  return available.reduce((best, strength) =>
    Math.abs(strength - band.target) < Math.abs(best - band.target) ? strength : best,
  available[0]);
});
const pairDefinitions = selectedReviewStrengths.slice(0, -1).flatMap((left, index) => {
  const right = selectedReviewStrengths[index + 1];
  return left !== null && right !== null ? [{ left, right }] : [];
});
const reviewHeader = [
  "pair_id", "category", "input", "candidate_a", "candidate_b",
  "meaning_preservation_winner", "grammar_winner", "naturalness_winner",
  "structure_winner", "change_amount_fit_winner", "overall_winner", "review_notes",
].join(",") + "\n";
const reviewRows = [];
const reviewKey = { generatedAt: payload.generatedAt, pairs: [] };
let pairNumber = 0;
let skippedIdenticalPairs = 0;
for (const item of corpus.cases) {
  for (const comparison of pairDefinitions) {
    const leftRow = byId.get(`${item.id}/${comparison.left}`);
    const rightRow = byId.get(`${item.id}/${comparison.right}`);
    if (!leftRow || !rightRow) continue;
    if (leftRow.output === rightRow.output) {
      skippedIdenticalPairs += 1;
      continue;
    }
    pairNumber += 1;
    const pairId = `pair-${String(pairNumber).padStart(4, "0")}`;
    let hash = 2166136261;
    for (const character of `${corpus.schemaVersion}|${item.id}|${comparison.left}|${comparison.right}`) {
      hash ^= character.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    }
    const swapped = (hash >>> 0) % 2 === 1;
    const candidateA = swapped ? rightRow : leftRow;
    const candidateB = swapped ? leftRow : rightRow;
    reviewRows.push([
      pairId, item.category, item.input, candidateA.output, candidateB.output,
      "", "", "", "", "", "", "",
    ].map(csvEscape).join(","));
    reviewKey.pairs.push({
      pairId,
      caseId: item.id,
      candidateA: { strength: candidateA.strength, band: candidateA.band },
      candidateB: { strength: candidateB.strength, band: candidateB.band },
    });
  }
}
payload.reviewSummary = {
  representativeStrengths: selectedReviewStrengths,
  intendedPairCount: corpus.cases.length * pairDefinitions.length,
  includedPairCount: pairNumber,
  skippedIdenticalPairCount: skippedIdenticalPairs,
};
reviewKey.skippedIdenticalPairCount = skippedIdenticalPairs;
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(payload, null, 2) + "\n");
fs.writeFileSync(path.join(outDir, "human-review.csv"), reviewHeader + reviewRows.join("\n") + "\n");
const internalDir = path.join(outDir, "internal");
fs.mkdirSync(internalDir, { recursive: true });
fs.writeFileSync(path.join(internalDir, "human-review-key.json"), JSON.stringify(reviewKey, null, 2) + "\n");

function bandSummary(band) {
  const entries = strengths
    .filter((strength) => strength >= band.min && strength <= band.max)
    .map((strength) => summaries[String(strength)]);
  const mean = (key) => entries.length
    ? round(entries.reduce((sum, entry) => sum + entry[key], 0) / entries.length)
    : 0;
  return {
    values: entries.length,
    changedRate: mean("changedRate"),
    eligibleChangedRate: mean("eligibleChangedRate"),
    learnedNliAvailabilityRate: mean("learnedNliAvailabilityRate"),
    learnedNliHardContradictionRate: mean("learnedNliHardContradictionRate"),
    meanLexicalChangeRate: mean("meanLexicalChangeRate"),
    structuralChangeRate: mean("structuralChangeRate"),
  };
}
const boundaryStrengths = [0, 24, 25, 49, 50, 74, 75, 100].filter((strength) => summaries[String(strength)]);

const markdown = [
  "# Pari strength sweep",
  "",
  `Synthetic cases: ${corpus.cases.length}; slider values measured: ${strengths.length} (${strengths[0]}–${strengths.at(-1)}).`,
  "",
  "Automatic diagnostics are not a human-quality score. `eligibleChanged` means the output changed and passed Pari's existing protected-content, rewrite-quality, and meaning-contract checks; a human still decides whether the wording is actually better.",
  "",
  "Strength band averages below average per-slider-value measurements, so every setting is represented without printing 101 repetitive rows. Full values and per-case outputs are in `report.json`.",
  "",
  "| Band | Slider values | Changed rate | Existing gates | NLI contradiction / coverage† | Lexical change | Structural change* |",
  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
  ...reviewBands.filter((band) => bandSummary(band).values > 0).map((band) => {
    const summary = bandSummary(band);
    return `| ${band.label} | ${summary.values} | ${summary.changedRate} | ${summary.eligibleChangedRate} | ${summary.learnedNliHardContradictionRate} / ${summary.learnedNliAvailabilityRate} | ${summary.meanLexicalChangeRate} | ${summary.structuralChangeRate} |`;
  }),
  "",
  "Boundary checks:",
  "",
  "| Strength | Changed | Gate-passing changed | Lexical change | Structural change* |",
  "| ---: | ---: | ---: | ---: | ---: |",
  ...boundaryStrengths.map((strength) => {
    const summary = summaries[String(strength)];
    return `| ${strength} (${strengthLabel(strength)}) | ${summary.changed}/${summary.cases} | ${summary.eligibleChanged}/${summary.cases} | ${summary.meanLexicalChangeRate} | ${summary.structuralChangeRate} |`;
  }),
  "",
  "*Structural change is a heuristic: sentence-count movement or changed order among shared tokens. It detects restructuring, not improvement. Sentence-count and token-order rates remain separately available in `report.json`.",
  "†Learned NLI is a contradiction screen, not a paraphrase-quality or naturalness score. If the bundled judge is unavailable, the report records that gap instead of counting the candidate as screened.",
  "",
  `The blinded pairwise sheet contains ${pairNumber} non-identical adjacent-band pairs; ${skippedIdenticalPairs} identical comparisons were omitted. It compares strengths ${selectedReviewStrengths.filter((value) => value !== null).join(", ")}. Share only the CSV file; the separate internal key maps pair IDs to strengths. For each dimension, record A, B, or Tie.`,
  "",
].join("\n");
fs.writeFileSync(path.join(outDir, "report.md"), markdown);
console.log(`[strength-sweep] wrote ${allRows.length} rows to ${path.join(outDir, "report.json")}`);
console.log(`[strength-sweep] human review sheet -> ${path.join(outDir, "human-review.csv")}`);
