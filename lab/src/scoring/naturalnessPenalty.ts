/**
 * Professor/slop word penalty and naturalness scoring.
 */

const PROFESSOR_WORDS = new Set([
  "utilize", "facilitate", "elucidate", "aforementioned", "moreover",
  "furthermore", "therefore", "thus", "underscores", "underscore",
  "significant", "comprehensive", "multifaceted", "individuals",
  "demonstrates", "illustrates", "exemplifies", "imperative", "crucial",
  "pivotal", "subsequently", "nevertheless", "notwithstanding",
  "heretofore", "thereafter", "thereby", "therein", "thereupon",
  "whilst", "amongst", "bespoke", "delineate", "leverage",
  "paradigm", "holistic", "synthesize", "contextualize",
  "operationalize", "problematize", "conceptualize", "methodology",
  "heterogeneous", "homogeneous", "epistemological", "ontological",
  "heuristic", "idiosyncratic", "juxtaposition", "quintessential",
  "substantiate", "corroborate", "ameliorate", "scrutinize",
  "dichotomy", "hegemony", "normative", "pedagogy", "discourse",
  "paradigm", "rigor", "robust", "actionable", "bandwidth",
  "circle back", "deep dive", "synergy", "leverage", "scalable",
  "in conclusion", "it is important to note",
  "this highlights the importance of",
  "this demonstrates the significance of",
  "it should be noted that",
  "it is worth noting that",
]);

const PREFERRED_REPLACEMENTS: Record<string, string[]> = {
  utilize: ["use"],
  individuals: ["people"],
  demonstrates: ["shows"],
  illustrates: ["shows"],
  moreover: ["also"],
  therefore: ["so"],
  significant: ["important", "clear", "big"],
  crucial: ["important"],
  facilitate: ["help"],
  aforementioned: ["earlier"],
  elucidate: ["explain"],
  comprehensive: ["full", "complete"],
  multifaceted: ["complex", "many-sided"],
  subsequently: ["later", "after", "then"],
  imperative: ["important", "necessary"],
  pivotal: ["key", "central"],
  underscores: ["shows", "highlights"],
  underscore: ["show", "highlight"],
};

/**
 * Compute professor/slop penalty for a candidate.
 * Returns a score between 0 and 1, where 0 = heavy slop, 1 = natural.
 */
export function computeNaturalnessPenalty(candidate: string): number {
  const lowerText = candidate.toLowerCase();
  const words = lowerText.split(/\s+/);
  const wordSet = new Set(lowerText.split(/\b\w+\b/).filter(Boolean));

  // Count professor words
  let slopCount = 0;
  let totalReplacements = 0;

  // Check each word
  for (const word of words) {
    const cleanWord = word.replace(/[^a-z]/g, "");
    if (PROFESSOR_WORDS.has(cleanWord)) {
      slopCount++;
    }
  }

  // Check phrases
  const phraseChecks = [
    "in conclusion", "it is important to note", "this highlights the importance of",
    "this demonstrates the significance of", "it should be noted",
    "it is worth noting", "it is crucial to",
  ];
  for (const phrase of phraseChecks) {
    if (lowerText.includes(phrase)) {
      slopCount += 3; // Heavier penalty for long phrases
    }
  }

  if (slopCount === 0) return 1.0; // No penalty

  // Calculate penalty: each slop word reduces score
  const penalty = Math.min(slopCount * 0.15, 0.8);
  return Math.max(0.2, 1.0 - penalty);
}

/**
 * Count professor/slop words in text (for reporting).
 */
export function countProfessorWords(text: string): { count: number; words: string[] } {
  const lower = text.toLowerCase();
  const words = lower.split(/\s+/);
  const found: string[] = [];

  for (const word of words) {
    const clean = word.replace(/[^a-z]/g, "");
    if (PROFESSOR_WORDS.has(clean)) {
      found.push(clean);
    }
  }

  return { count: found.length, words: found };
}

/**
 * Get preferred replacement for a word.
 */
export function getPreferredReplacement(word: string): string | null {
  const replacements = PREFERRED_REPLACEMENTS[word.toLowerCase()];
  return replacements?.[0] ?? null;
}

export { PROFESSOR_WORDS, PREFERRED_REPLACEMENTS };
