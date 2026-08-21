/**
 * Reference-free eval metrics for Pari paraphrase quality.
 * All local, zero new dependencies:
 *  - grammaticality: harper.js (already shipped in the app)
 *  - meaning preservation: @huggingface/transformers MiniLM embeddings (already bundled)
 *  - paraphrase band: char edit distance + content-word overlap + distinct-n
 *  - guards: anchors (numbers/names/dates/links), negation cues
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

export const { analyzeHarperGrammar } = await (async () => {
  // harper.js is ESM-only; load it natively instead of through the CJS bridge.
  const [{ LocalLinter }, { binaryInlined }] = await Promise.all([
    import("harper.js"),
    import("harper.js/binaryInlined"),
  ]);
  let linterPromise = null;
  async function getLinter() {
    if (!linterPromise) {
      linterPromise = (async () => {
        const linter = new LocalLinter({ binary: binaryInlined });
        await linter.setup();
        return linter;
      })();
    }
    return linterPromise;
  }
  function severityForKind(kind) {
    if (/agreement|grammar|punctuation|typo|spelling|word order/i.test(kind)) return "high";
    if (/usage|word choice|capitalization|formatting|redundancy|repetition/i.test(kind)) return "medium";
    return "low";
  }
  return {
    async analyzeHarperGrammar(text) {
      const trimmed = text.trim();
      if (!trimmed) return [];
      const linter = await getLinter();
      const lints = await linter.lint(text, { language: "plaintext", dedup: true, isolateEnglish: true });
      return lints.map((lint, index) => {
        try {
          const span = lint.span();
          const kind = lint.lint_kind_pretty() || lint.lint_kind() || "Grammar";
          const issue = {
            id: `harper-${lint.lint_kind()}-${span.start}-${span.end}-${index}`,
            severity: severityForKind(kind),
            label: kind,
            sample: lint.get_problem_text() || undefined,
          };
          span.free();
          return issue;
        } finally {
          lint.free();
        }
      });
    },
  };
})();

// ---------------------------------------------------------------------------
// Harper grammar scoring
// ---------------------------------------------------------------------------

let harperReady = null;
async function getHarper() {
  if (!harperReady) harperReady = analyzeHarperGrammar("The quick brown fox jumps over the lazy dog.");
  await harperReady;
}

/** High-severity issue count per 100 tokens. Medium/low are style noise.
 *  ignoreSamples: lowercase issue samples to skip (deliberate register tokens
 *  preserved from the input are not "new errors"). */
export async function grammarErrorRate(text, ignoreSamples) {
  await getHarper();
  const issues = await analyzeHarperGrammar(text);
  const tokens = Math.max(1, (text.match(/[A-Za-z0-9']+/g) ?? []).length);
  const significant = issues.filter(
    (i) => i.severity === "high" && !(ignoreSamples && ignoreSamples.has((i.sample ?? "").toLowerCase()))
  ).length;
  return (significant / tokens) * 100;
}

/** grammar_gain > 0 means output has fewer errors than input. */
export async function grammarGain(input, output, ignoreSamples) {
  const [inRate, outRate] = await Promise.all([
    grammarErrorRate(input, ignoreSamples),
    grammarErrorRate(output, ignoreSamples),
  ]);
  return { gain: inRate - outRate, inRate, outRate };
}

// ---------------------------------------------------------------------------
// Meaning preservation (MiniLM cosine)
// ---------------------------------------------------------------------------

let embedder = null;
const MODEL_DIR = path.join(ROOT_DIR, "public/models/Xenova/all-MiniLM-L6-v2");

export async function getEmbedder() {
  if (!embedder) {
    const { pipeline } = await import("@huggingface/transformers");
    embedder = await pipeline("feature-extraction", MODEL_DIR, {
      local_files_only: true,
      model_file_name: "model_quantized",
    });
  }
  return embedder;
}

export async function cosineSimilarity(a, b) {
  const extractor = await getEmbedder();
  const [ea, eb] = await Promise.all([
    extractor(a, { pooling: "mean", normalize: true }),
    extractor(b, { pooling: "mean", normalize: true }),
  ]);
  const va = Array.from(ea.data);
  const vb = Array.from(eb.data);
  let dot = 0;
  for (let i = 0; i < va.length; i++) dot += va[i] * vb[i];
  return dot;
}

// ---------------------------------------------------------------------------
// Paraphrase band validators
// ---------------------------------------------------------------------------

const STOPWORDS = new Set(("a an and are as at be been but by can could did do does for from had has have he her him his how i if in into is it its just may me might must my no nor not of on or our out she should so some than that the their them then there these they this those to too us was we were what when where which who will with would you your".split(" ")));

export function tokens(text) {
  return text.toLowerCase().match(/[a-z]+(?:[-'][a-z]+)*/g) ?? [];
}

export function contentWords(text) {
  return tokens(text).filter((t) => !STOPWORDS.has(t));
}

export function charEditDistanceRatio(a, b) {
  // Levenshtein over characters, reported relative to the longer string.
  const m = a.length;
  const n = b.length;
  if (m === 0 && n === 0) return 0;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const curr = [i];
    for (let j = 1; j <= n; j++) {
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = curr;
  }
  return prev[n] / Math.max(m, n);
}

export function contentOverlap(input, output) {
  // Fraction of input content words preserved in output (bag semantics).
  const bag = new Map();
  for (const t of contentWords(output)) bag.set(t, (bag.get(t) ?? 0) + 1);
  const inWords = contentWords(input);
  if (inWords.length === 0) return 1;
  let kept = 0;
  for (const t of inWords) {
    const c = bag.get(t) ?? 0;
    if (c > 0) {
      kept += 1;
      bag.set(t, c - 1);
    }
  }
  return kept / inWords.length;
}

export function distinctN(text, n) {
  const toks = tokens(text);
  if (toks.length < n) return 1;
  const set = new Set();
  for (let i = 0; i <= toks.length - n; i++) set.add(toks.slice(i, i + n).join(" "));
  return set.size / (toks.length - n + 1);
}

// ---------------------------------------------------------------------------
// Guards
// ---------------------------------------------------------------------------

export function anchorValues(text) {
  return [
    ...(text.match(/https?:\/\/[^\s)]+/gi) ?? []),
    ...(text.match(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g) ?? []),
    ...(text.match(/\+?\d[\d\s().-]{5,}\d/g) ?? []), // phone-like
    ...(text.match(/\b\d+(?:[.,]\d+)?%?\b/g) ?? []),
    ...(text.match(/\b[A-Z][a-z]+ [A-Z][a-z]+\b/g) ?? []), // Person Name
    ...(text.match(/[“"]([^”"]+)[”"]/g) ?? []),
  ].map((v) => v.trim());
}

const NUMBER_WORDS = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7,
  eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, fifteen: 15,
  twenty: 20, thirty: 30, fifty: 50, hundred: 100, thousand: 1000,
};

function anchorKeys(value) {
  // A digit anchor also matches its spelled-out form ("3" ~ "three"),
  // and vice versa, so "took me about three hours" preserves the anchor "3".
  const keys = new Set([value.toLowerCase().replace(/\s+/g, " ")]);
  const digit = value.match(/\d+(?:[.,]\d+)?/);
  if (digit) {
    for (const [word, num] of Object.entries(NUMBER_WORDS)) {
      if (String(num) === digit[0].replace(/[.,]\d+$/, "")) keys.add(word);
    }
  } else {
    const num = NUMBER_WORDS[value.toLowerCase()];
    if (num !== undefined) keys.add(String(num));
  }
  return keys;
}

export function missingAnchors(input, output) {
  const outKeys = new Set();
  for (const a of anchorValues(output)) for (const k of anchorKeys(a)) outKeys.add(k);
  // A spelled-out number anywhere in the output preserves its digit anchor
  // ("took me about three hours" keeps the anchor "3").
  const outTokens = new Set(tokens(output));
  for (const [word, num] of Object.entries(NUMBER_WORDS)) {
    if (outTokens.has(word)) outKeys.add(String(num));
  }
  return anchorValues(input).filter((a) => ![...anchorKeys(a)].some((k) => outKeys.has(k)));
}

const NEGATION_CUES = /\b(not|no|never|n't|without|neither|nor|cannot|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|hasn't|haven't|hadn't)\b/gi;

export function negationCues(text) {
  return (text.match(NEGATION_CUES) ?? []).length;
}

// ---------------------------------------------------------------------------
// Typo-tolerant reference (for scoring degenerate inputs)
// ---------------------------------------------------------------------------

let dictSet = null;
function getDict() {
  if (!dictSet) {
    try {
      dictSet = new Set(
        fs.readFileSync("/usr/share/dict/words", "utf8")
          .split("\n").map((w) => w.trim().toLowerCase()).filter((w) => w.length > 1)
      );
    } catch {
      dictSet = new Set();
    }
  }
  return dictSet;
}

const correctionCache = new Map();

/** Optimal-string-alignment distance (transposition-aware), early-exit bound. */
function osaDistance(a, b, max) {
  const m = a.length;
  const n = b.length;
  if (Math.abs(m - n) > max) return max + 1;
  let prev2 = null;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const curr = [i];
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let d = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d = Math.min(d, prev2[j - 2] + 1);
      }
      curr[j] = d;
    }
    prev2 = prev;
    prev = curr;
  }
  return prev[n];
}

function correctToken(token) {
  const lower = token.toLowerCase();
  if (lower.length < 3 || lower.includes("'")) return token;
  const dict = getDict();
  if (dict.size === 0 || dict.has(lower)) return token;
  if (correctionCache.has(lower)) return correctionCache.get(lower);
  let best = null;
  let bestDist = 3;
  for (const word of dict) {
    if (Math.abs(word.length - lower.length) > 2) continue;
    const d = osaDistance(lower, word, 2);
    if (d < bestDist || (d === bestDist && best && word.length > best.length)) {
      best = word;
      bestDist = d;
      if (d === 1 && word.length >= lower.length) break; // good enough
    }
  }
  const corrected = bestDist <= 2 && best ? best : lower;
  // Preserve capitalization pattern of the original token.
  const result = /^[A-Z]/.test(token) && !/^[A-Z]+$/.test(token)
    ? corrected.charAt(0).toUpperCase() + corrected.slice(1)
    : corrected;
  correctionCache.set(lower, result);
  return result;
}

/** Best-effort typo correction used ONLY as the scoring reference for
 *  degenerate-input categories. Guards (anchors/negation) always use raw text. */
export async function correctTypos(text) {
  return text.replace(/[A-Za-z][A-Za-z']+/g, (token) => correctToken(token));
}

// ---------------------------------------------------------------------------
// Composite scoring per case
// ---------------------------------------------------------------------------

export const BAND = { editMin: 0.08, editMax: 0.65, overlapMin: 0.3, overlapMax: 0.85 };

const DEGENERATE = new Set(["broken_words", "word_salad"]);

export async function scoreCase(cas, outputText) {
  const rawInput = cas.input;
  // Degenerate inputs are credited if the rewrite matches EITHER the raw
  // input, a best-effort typo-corrected reference, or a human reference
  // (standard GEC practice: embedders cannot verify heavy shorthand like
  // "smth/tmrw", so curated references stand in).
  // References contribute SIMILARITY credit only; band distance stays
  // measured against the input itself so a reference can never mask a copy.
  const refText = DEGENERATE.has(cas.category) ? await correctTypos(rawInput) : rawInput;
  const simCandidates = [rawInput, refText];
  if (cas.reference) simCandidates.push(cas.reference);

  const sims = await Promise.all(simCandidates.map((ref) => cosineSimilarity(ref, outputText)));
  const sim = Math.max(...sims);
  // For degenerate categories the band may be measured against the
  // input-derived typo correction (never the model's output, so this is not
  // circular), and the meaning floor relaxes to 0.55: embeddings are noisy on
  // garbage text. Overlap + guards carry the protection in these categories.
  const degenerate = DEGENERATE.has(cas.category);
  const bandInput = degenerate ? refText : rawInput;
  const editRatio = charEditDistanceRatio(bandInput, outputText);
  const overlap = contentOverlap(bandInput, outputText);
  const meaningFloor = degenerate ? 0.55 : 0.72;
  const d2 = distinctN(outputText, 2);

  const missing = missingAnchors(rawInput, outputText);
  const negIn = negationCues(rawInput);
  const negOut = negationCues(outputText);

  // Deliberate register tokens (slang, shorthand) preserved from the input
  // are not "new errors" — harper just doesn't know them. Token-level check:
  // any high-severity spelling sample whose token exists in the input is ignored.
  const inputTokenSet = new Set(tokens(rawInput));
  const ignoreSamples = new Set();
  for (const issue of await analyzeHarperGrammar(outputText)) {
    if (issue.severity !== "high" || !issue.sample) continue;
    const sample = issue.sample.toLowerCase();
    if (/^[a-z']+$/.test(sample) && inputTokenSet.has(sample)) {
      ignoreSamples.add(sample);
    }
  }

  const gram = await grammarGain(rawInput, outputText, ignoreSamples);

  const checks = {
    meaningFloor: sim >= meaningFloor,
    noNewErrors: gram.gain >= -0.5, // small tolerance for harper noise
    anchorSafe: missing.length === 0,
    negationSafe: !(negOut < negIn),
    // No overlap ceiling: merging fragments or de-duplicating salad keeps
    // every content word by definition.
    // Edit-distance floor is waived when the rewrite strictly IMPROVED grammar:
    // a surgical tense fix ("was" -> "were") must not be scored like a copy.
    bandFit:
      (editRatio >= BAND.editMin && editRatio <= BAND.editMax && overlap >= BAND.overlapMin) ||
      gram.gain > 0,
  };

  // Canary cases skip band-fit (identity-preserving rewrite is fine) but never skip guards.
  const relevantChecks = cas.category === "canary"
    ? { ...checks, bandFit: true }
    : checks;

  const passed = Object.values(relevantChecks).every(Boolean);

  return {
    id: cas.id,
    category: cas.category,
    passed,
    metrics: {
      cosineSim: Number(sim.toFixed(3)),
      grammarGain: Number(gram.gain.toFixed(2)),
      errorsInPer100: Number(gram.inRate.toFixed(2)),
      errorsOutPer100: Number(gram.outRate.toFixed(2)),
      editDistanceRatio: Number(editRatio.toFixed(3)),
      contentOverlap: Number(overlap.toFixed(3)),
      distinctBigram: Number(d2.toFixed(3)),
      negationCuesIn: negIn,
      negationCuesOut: negOut,
    },
    failedChecks: Object.entries(relevantChecks).filter(([, ok]) => !ok).map(([k]) => k),
    missingAnchors: missing,
  };
}
