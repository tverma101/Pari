import type { TokenAlternative } from "../core/types.js";
import { computeNaturalnessPenalty } from "../scoring/naturalnessPenalty.js";

/**
 * Rank alternatives by multiple criteria for display.
 */
export function rankAlternativesForDisplay(
  alternatives: TokenAlternative[],
  contextSentence: string
): TokenAlternative[] {
  return alternatives
    .map((alt) => {
      const scores = scoreAlternative(alt, contextSentence);
      return { alt, totalScore: scores.total };
    })
    .sort((a, b) => b.totalScore - a.totalScore)
    .map((item) => item.alt);
}

interface AlternativeScores {
  semanticFit: number;
  naturalness: number;
  professorPenalty: number;
  typeBonus: number;
  total: number;
}

function scoreAlternative(
  alt: TokenAlternative,
  context: string
): AlternativeScores {
  const naturalness = computeNaturalnessPenalty(alt.text);

  // Type bonus
  let typeBonus = 0;
  switch (alt.type) {
    case "true_synonym": typeBonus = 15; break;
    case "simpler_word": typeBonus = 12; break;
    case "near_synonym": typeBonus = 8; break;
    case "contextual_replacement": typeBonus = 10; break;
    case "phrase_rewrite": typeBonus = 5; break;
    case "not_recommended": typeBonus = -20; break;
  }

  // Context bonus: if the alternative fits well in the sentence
  const contextFit = checkContextFit(alt.text, context);

  const total = alt.semanticScore * 25 +
    alt.naturalnessScore * 20 +
    (1 - alt.professorPenalty) * 10 +
    typeBonus +
    contextFit * 15;

  return {
    semanticFit: alt.semanticScore,
    naturalness,
    professorPenalty: alt.professorPenalty,
    typeBonus,
    total,
  };
}

/**
 * Check if an alternative fits grammatically in a context sentence.
 * Simple heuristic: just checks if the replacement can swap in without
 * obvious grammar breakage.
 */
function checkContextFit(alternative: string, context: string): number {
  const altWords = alternative.split(/\s+/);
  const contextWords = context.split(/\s+/);

  // Very basic: if the alternative is a single word and the context
  // has similar-length words around potential replacement points, it's likely fine
  if (altWords.length === 1) {
    const avgWordLen = contextWords.reduce((sum, w) => sum + w.length, 0) / contextWords.length;
    const lenDiff = Math.abs(altWords[0].length - avgWordLen);
    if (lenDiff > 5) return 0.3; // Unusual word length for this context
    return 0.8;
  }

  // Multi-word alternatives: check if first word fits
  if (altWords.length > 0) {
    const firstWord = altWords[0];
    if (contextWords.some((w) => w.toLowerCase() === firstWord.toLowerCase())) {
      return 0.5; // Word already in context
    }
  }

  return 0.6;
}
