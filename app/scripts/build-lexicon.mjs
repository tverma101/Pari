import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(SCRIPT_DIR, "..");
const WORDNET_DB_DIR = path.join(ROOT_DIR, "node_modules", "wordnet", "db");
const MOBY_WORDS_PATH = path.join(ROOT_DIR, "node_modules", "moby", "words.txt");
const OUTPUT_PATH = path.join(ROOT_DIR, "src", "lib", "rewriteStack", "wordnetLexicon.json");
const MAX_OPTIONS_PER_TERM = 48;
const MAX_SENSES_PER_TERM = 3;
const MAX_THESAURUS_OPTIONS_PER_TERM = 96;

const SOURCES = [
  ["data.noun", "noun"],
  ["data.verb", "verb"],
  ["data.adj", "adjective"],
  ["data.adv", "adverb"],
];

function cleanTerm(value) {
  return value
    .replace(/_/g, " ")
    .replace(/\((?:a|p|ip)\)$/i, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function isUsableTerm(value) {
  if (!value || value.length < 2 || value.length > 48) return false;
  if (value.split(/\s+/).length > 5) return false;
  if (!/^[a-z][a-z' -]*$/i.test(value)) return false;
  if (/^(?:a|an|the|be|do|go|have|make|get|take)$/i.test(value)) return false;
  return true;
}

function isUsableThesaurusTerm(value, rawValue = value) {
  if (!isUsableTerm(value)) return false;
  // Moby includes proper names and place names. They are useful as reference
  // data, but are not safe inline replacements for an ordinary word.
  if (/^[A-Z][a-z]/.test(rawValue.trim())) return false;
  if (/\b(?:inc|corp|ltd|co)\.?$/i.test(value)) return false;
  return true;
}

function parseMobyLine(line) {
  const values = line.split(",");
  const rawTerm = (values.shift() ?? "").trim();
  const term = cleanTerm(rawTerm);
  if (!isUsableThesaurusTerm(term, rawTerm)) return null;

  const alternatives = [];
  for (const rawValue of values) {
    const value = cleanTerm(rawValue);
    if (!isUsableThesaurusTerm(value, rawValue)) continue;
    if (value === term || alternatives.includes(value)) continue;
    alternatives.push(value);
    if (alternatives.length >= MAX_THESAURUS_OPTIONS_PER_TERM) break;
  }

  return alternatives.length > 0 ? { term, rawTerm, alternatives } : null;
}

function parseSynset(line) {
  if (!line || line.startsWith(" ")) return null;

  const metadata = line.split("|")[0].trim().split(/\s+/);
  const offset = metadata[0];
  const wordCount = Number.parseInt(metadata[3] ?? "0", 16);
  const words = [];

  for (let index = 0; index < wordCount; index += 1) {
    const rawWord = metadata[4 + index * 2];
    const word = cleanTerm(rawWord ?? "");
    if (isUsableTerm(word)) words.push(word);
  }

  return { offset, words: [...new Set(words)] };
}

function parseIndex(line) {
  if (!line || line.startsWith(" ")) return null;

  const parts = line.trim().split(/\s+/);
  const term = cleanTerm(parts[0] ?? "");
  const pointerCount = Number.parseInt(parts[3] ?? "0", 10);
  const offsetStart = 6 + pointerCount;
  const offsets = parts.slice(offsetStart, offsetStart + Number.parseInt(parts[2] ?? "0", 10));

  return isUsableTerm(term) && offsets.length > 0 ? { term, offsets } : null;
}

async function main() {
  const entries = new Map();
  const synsets = new Map();

  for (const [fileName, partOfSpeech] of SOURCES) {
    const source = await fs.readFile(path.join(WORDNET_DB_DIR, fileName), "utf8");

    for (const line of source.split("\n")) {
      const synset = parseSynset(line);
      if (!synset || synset.words.length < 2) continue;
      synsets.set(`${partOfSpeech}:${synset.offset}`, synset.words);
    }
  }

  for (const [fileName, partOfSpeech] of SOURCES) {
    const indexFileName = fileName.replace("data.", "index.");
    const source = await fs.readFile(path.join(WORDNET_DB_DIR, indexFileName), "utf8");

    for (const line of source.split("\n")) {
      const indexEntry = parseIndex(line);
      if (!indexEntry) continue;

      const key = indexEntry.term;
      const entry = entries.get(key) ?? { noun: [], verb: [], adjective: [], adverb: [] };
      const bucket = entry[partOfSpeech];
      const offsets = indexEntry.offsets.slice(0, MAX_SENSES_PER_TERM);

      for (const offset of offsets) {
        const synset = synsets.get(`${partOfSpeech}:${offset}`) ?? [];
        for (const replacement of synset) {
          if (replacement === key || bucket.includes(replacement)) continue;
          bucket.push(replacement);
          if (bucket.length >= MAX_OPTIONS_PER_TERM) break;
        }

        if (bucket.length >= MAX_OPTIONS_PER_TERM) break;
      }

      entries.set(key, entry);
    }
  }

  // Moby is intentionally consumed at build time. The app ships a compact,
  // offline index and never needs a network thesaurus request at runtime.
  // WordNet gives higher-precision same-sense synonyms first; Moby supplies
  // the broader, human-facing discovery list needed by the inline chooser.
  const mobySource = await fs.readFile(MOBY_WORDS_PATH, "utf8");
  const mobyTerms = new Map();
  const mobyRawTerms = new Map();
  for (const line of mobySource.split("\n")) {
    const parsed = parseMobyLine(line);
    if (!parsed) continue;

    mobyTerms.set(parsed.term, parsed.alternatives);
    mobyRawTerms.set(parsed.term, parsed.rawTerm);
    const entry = entries.get(parsed.term) ?? { noun: [], verb: [], adjective: [], adverb: [] };
    entry.thesaurus = parsed.alternatives;
    entries.set(parsed.term, entry);
  }

  // A compact second hop makes the chooser useful for inflected, compound,
  // and under-described words without inventing numbered placeholders. These
  // are deliberately labelled as related in the UI and never enter automatic
  // paragraph rewriting.
  const reverseMoby = new Map();
  const addReverse = (key, value) => {
    const bucket = reverseMoby.get(key) ?? [];
    if (!bucket.includes(value)) bucket.push(value);
    reverseMoby.set(key, bucket);
  };
  for (const [term, alternatives] of mobyTerms) {
    for (const alternative of alternatives) addReverse(alternative, term);
  }

  const relatedTerms = new Set([...mobyTerms.keys(), ...reverseMoby.keys()]);
  for (const term of relatedTerms) {
    const directAlternatives = mobyTerms.get(term) ?? [];
    if (directAlternatives.length >= 40) continue;
    const related = [];
    const seen = new Set(directAlternatives);
    const addRelated = (candidate) => {
      if (!isUsableThesaurusTerm(candidate, mobyRawTerms.get(candidate) ?? candidate)) return;
      if (candidate === term || seen.has(candidate) || related.includes(candidate)) return;
      related.push(candidate);
    };

    for (const candidate of reverseMoby.get(term) ?? []) addRelated(candidate);
    const firstHop = [term, ...directAlternatives.slice(0, 24), ...(reverseMoby.get(term) ?? []).slice(0, 24)];
    for (const seed of firstHop) {
      for (const candidate of reverseMoby.get(seed) ?? []) addRelated(candidate);
      for (const candidate of (mobyTerms.get(seed) ?? []).slice(0, 24)) addRelated(candidate);
      if (related.length >= MAX_THESAURUS_OPTIONS_PER_TERM) break;
    }

    if (related.length < 40) {
      const secondHop = related.slice(0, 32);
      for (const seed of secondHop) {
        for (const candidate of reverseMoby.get(seed) ?? []) addRelated(candidate);
        for (const candidate of (mobyTerms.get(seed) ?? []).slice(0, 16)) addRelated(candidate);
        if (related.length >= MAX_THESAURUS_OPTIONS_PER_TERM) break;
      }
    }

    if (related.length > 0) {
      const entry = entries.get(term) ?? { noun: [], verb: [], adjective: [], adverb: [] };
      entry.related = related.slice(0, MAX_THESAURUS_OPTIONS_PER_TERM);
      entries.set(term, entry);
    }
  }

  const compact = {};
  for (const key of [...entries.keys()].sort()) {
    const entry = entries.get(key);
    const parts = Object.fromEntries(
      Object.entries(entry)
        .map(([partOfSpeech, options]) => [partOfSpeech, options.slice(0, MAX_OPTIONS_PER_TERM)])
        .filter(([, options]) => options.length > 0)
    );
    if (Object.keys(parts).length > 0) compact[key] = parts;
  }

  await fs.mkdir(path.dirname(OUTPUT_PATH), { recursive: true });
  await fs.writeFile(
    OUTPUT_PATH,
    `${JSON.stringify({ version: 2, source: "WordNet + Moby Thesaurus", entries: compact })}\n`,
    "utf8"
  );

  console.log(`[lexicon] generated ${Object.keys(compact).length.toLocaleString()} terms at ${path.relative(ROOT_DIR, OUTPUT_PATH)}`);
}

main().catch((error) => {
  console.error(`[lexicon] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
