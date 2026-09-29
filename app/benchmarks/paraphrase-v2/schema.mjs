import fs from "fs";
import path from "path";

export const ROOT_DIR = path.resolve(new URL("../..", import.meta.url).pathname);
export const DEFAULT_CORPUS_PATH = path.join(ROOT_DIR, "benchmarks/paraphrase-v2/corpus.json");
export const DEFAULT_SOURCES_PATH = path.join(ROOT_DIR, "benchmarks/paraphrase-v2/sources.json");

export const EXPECTED_CATEGORIES = [
  "meaning_equivalence",
  "cohesion_known_new",
  "logical_relations",
  "reference_coreference",
  "modality_negation_precision",
  "factual_anchors",
  "grammar_minimal_edit",
  "sentence_structure",
  "lexical_collocation",
  "register_tone",
  "paragraph_unity_redundancy",
  "ambiguity_non_invention",
];

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

export function resolveRepoPath(value, fallback) {
  const selected = value ?? fallback;
  if (path.isAbsolute(selected)) return selected;
  const cwdPath = path.resolve(process.cwd(), selected);
  return fs.existsSync(cwdPath) ? cwdPath : path.resolve(ROOT_DIR, selected);
}

export function loadV2Corpus(corpusPath = DEFAULT_CORPUS_PATH) {
  return readJson(corpusPath);
}

export function loadV2Sources(sourcesPath = DEFAULT_SOURCES_PATH) {
  return readJson(sourcesPath);
}

export function validateV2Corpus(corpus, sources) {
  const errors = [];
  const cases = corpus && Array.isArray(corpus.cases) ? corpus.cases : [];
  const sourceMap = sources && sources.sources && typeof sources.sources === "object"
    ? sources.sources
    : {};

  if (!corpus || typeof corpus !== "object" || Array.isArray(corpus)) {
    errors.push("corpus must be a JSON object");
  }
  if (corpus?.version !== 2) errors.push(`corpus.version must be 2 (got ${String(corpus?.version)})`);
  if (typeof corpus?.defaultInstruction !== "string" || !corpus.defaultInstruction.trim()) {
    errors.push("corpus.defaultInstruction must be a non-empty string");
  }
  if (cases.length !== 72) errors.push(`corpus must contain exactly 72 cases (got ${cases.length})`);

  const ids = new Set();
  const counts = Object.fromEntries(EXPECTED_CATEGORIES.map((category) => [category, 0]));
  for (const [index, item] of cases.entries()) {
    const label = `case[${index}]`;
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      errors.push(`${label} must be an object`);
      continue;
    }
    if (typeof item.id !== "string" || !item.id.trim()) errors.push(`${label}.id must be non-empty`);
    if (ids.has(item.id)) errors.push(`${label}.id is duplicated: ${item.id}`);
    ids.add(item.id);
    if (!EXPECTED_CATEGORIES.includes(item.category)) {
      errors.push(`${label}.category is not an expected v2 category: ${String(item.category)}`);
    } else {
      counts[item.category] += 1;
    }
    if (typeof item.input !== "string" || !item.input.trim()) errors.push(`${label}.input must be non-empty`);
    for (const field of ["standardRefs", "mustPreserve", "riskTags"]) {
      if (!Array.isArray(item[field]) || item[field].length === 0) {
        errors.push(`${label}.${field} must be a non-empty array`);
      }
    }
    for (const ref of item.standardRefs ?? []) {
      if (typeof ref !== "string" || !Object.prototype.hasOwnProperty.call(sourceMap, ref)) {
        errors.push(`${label}.standardRefs has no matching sources.json entry: ${String(ref)}`);
      }
    }
  }

  for (const category of EXPECTED_CATEGORIES) {
    if (counts[category] !== 6) errors.push(`category ${category} must contain 6 cases (got ${counts[category]})`);
  }

  if (!sources || typeof sources !== "object" || Array.isArray(sources)) {
    errors.push("sources must be a JSON object");
  }
  for (const [id, source] of Object.entries(sourceMap)) {
    if (!source || typeof source !== "object") {
      errors.push(`source ${id} must be an object`);
      continue;
    }
    for (const field of ["authority", "title", "url", "sourceType", "claimsUsed"]) {
      if (field === "claimsUsed") {
        if (!Array.isArray(source[field]) || source[field].length === 0) errors.push(`source ${id}.${field} must be a non-empty array`);
      } else if (typeof source[field] !== "string" || !source[field].trim()) {
        errors.push(`source ${id}.${field} must be a non-empty string`);
      }
    }
    if (typeof source.url === "string" && !/^https?:\/\//i.test(source.url)) {
      errors.push(`source ${id}.url must be http(s): ${source.url}`);
    }
  }

  const usedRefs = [...new Set(cases.flatMap((item) => item.standardRefs ?? []))];
  return {
    valid: errors.length === 0,
    errors,
    corpus: {
      version: corpus?.version ?? null,
      cases: cases.length,
      categories: counts,
      standardRefs: usedRefs.length,
    },
    sources: { entries: Object.keys(sourceMap).length },
  };
}
