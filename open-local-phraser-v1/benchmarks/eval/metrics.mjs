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

const { analyzeHarperGrammar } = await (async () => {
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

/** High+medium severity issue count per 100 tokens. Low-severity noise ignored. */
export async function grammarErrorRate(text) {
  await getHarper();
  const issues = await analyzeHarperGrammar(text);
  const tokens = Math.max(1, (text.match(/[A-Za-z0-9']+/g) ?? []).length);
  const significant = issues.filter((i) => i.severity === "high" || i.severity === "medium").length;
  return (significant / tokens) * 100;
}

/** grammar_gain > 0 means output has fewer errors than input. */
export async function grammarGain(input, output) {
  const [inRate, outRate] = await Promise.all([grammarErrorRate(input), grammarErrorRate(output)]);
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

export function missingAnchors(input, output) {
  const norm = (s) => s.toLowerCase().replace(/\s+/g, " ");
  const outAnchors = new Set(anchorValues(output).map(norm));
  return anchorValues(input)
    .map(norm)
    .filter((a) => !outAnchors.has(a));
}

const NEGATION_CUES = /\b(not|no|never|n't|without|neither|nor|cannot|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|hasn't|haven't|hadn't)\b/gi;

export function negationCues(text) {
  return (text.match(NEGATION_CUES) ?? []).length;
}

// ---------------------------------------------------------------------------
// Composite scoring per case
// ---------------------------------------------------------------------------

export const BAND = { editMin: 0.08, editMax: 0.65, overlapMin: 0.3, overlapMax: 0.85 };

export async function scoreCase(cas, outputText) {
  const input = cas.input;
  const [sim, gram, editRatio, overlap, d2] = await Promise.all([
    cosineSimilarity(input, outputText),
    grammarGain(input, outputText),
    Promise.resolve(charEditDistanceRatio(input, outputText)),
    Promise.resolve(contentOverlap(input, outputText)),
    Promise.resolve(distinctN(outputText, 2)),
  ]);

  const missing = missingAnchors(input, outputText);
  const negIn = negationCues(input);
  const negOut = negationCues(outputText);

  const checks = {
    meaningFloor: sim >= 0.72,
    noNewErrors: gram.gain >= -0.5, // small tolerance for harper noise
    anchorSafe: missing.length === 0,
    negationSafe: !(negOut < negIn),
    bandFit: editRatio >= BAND.editMin && editRatio <= BAND.editMax && overlap >= BAND.overlapMin && overlap <= BAND.overlapMax,
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
