import { computeJaccardSimilarity } from "./semanticSimilarity.js";

/**
 * Compute lexical diversity score between original and candidate.
 * Measures how different the word choice is.
 *
 * Returns a score between 0 and 1.
 * 0 = all same words, 1 = completely different vocabulary.
 */
export function computeLexicalDiversity(original: string, candidate: string): number {
  const jaccard = computeJaccardSimilarity(original, candidate);
  // Lexical difference = 1 - word overlap (but cap so it doesn't reward too much change)
  const rawDiff = 1 - jaccard;

  // Scale: 0.2-0.5 is ideal lexical diversity
  // 0.0 = identical words (bad rewrite)
  // 0.1-0.3 = conservative change
  // 0.3-0.6 = good natural rewrite
  // >0.6 = too much change, risk of meaning drift
  if (rawDiff < 0.1) return 0; // too close
  if (rawDiff < 0.3) return (rawDiff - 0.1) / 0.2 * 0.7; // ramp up
  if (rawDiff < 0.6) return 0.7 + (rawDiff - 0.3) / 0.3 * 0.3; // ideal zone
  return Math.max(0, 1.0 - (rawDiff - 0.6) / 0.4); // penalize too much change
}

/**
 * Count unique word types vs tokens for a text.
 * Type-token ratio is a measure of vocabulary richness.
 */
export function typeTokenRatio(text: string): number {
  const words = text.toLowerCase().split(/\s+/).filter((w) => w.length > 0);
  if (words.length === 0) return 0;
  const types = new Set(words);
  return types.size / words.length;
}

/**
 * Compute n-gram overlap (bigrams) for a more structural lexical comparison.
 */
export function bigramOverlap(text1: string, text2: string): number {
  const bigrams1 = getBigrams(text1);
  const bigrams2 = getBigrams(text2);

  if (bigrams1.size === 0 || bigrams2.size === 0) return 0;

  let intersection = 0;
  for (const b of bigrams1) {
    if (bigrams2.has(b)) intersection++;
  }

  const union = bigrams1.size + bigrams2.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

function getBigrams(text: string): Set<string> {
  const words = text.toLowerCase().split(/\s+/).filter((w) => w.length > 0);
  const bigrams = new Set<string>();
  for (let i = 0; i < words.length - 1; i++) {
    bigrams.add(`${words[i]} ${words[i + 1]}`);
  }
  return bigrams;
}
