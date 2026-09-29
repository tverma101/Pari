import type { Candidate, CandidateScores, ProtectedSpan } from "../core/types.js";
import { filterHardRejections } from "./hardRejection.js";
import { computeSemanticSimilarity } from "./semanticSimilarity.js";
import { computeLexicalDiversity } from "./lexicalDiversity.js";
import { computeStructureDiversity } from "./structureDiversity.js";
import { computeNaturalnessPenalty } from "./naturalnessPenalty.js";
import { computeBanwordPenalty } from "./banwordPenalty.js";
import { checkGrammar } from "./grammarCheck.js";
import { computeNLIScore } from "./nliCheck.js";

export const DEFAULT_SCORE_WEIGHTS = {
  semanticSimilarity: 0.30,
  nliScore: 0.18,
  naturalness: 0.16,
  grammarScore: 0.12,
  lexicalDifference: 0.10,
  structureDifference: 0.08,
  preferenceBonus: 0.06,
};

/**
 * Score a single candidate.
 * Runs hard rejection first, then computes all sub-scores.
 */
export function scoreCandidate(
  candidate: Candidate,
  original: string,
  spans: ProtectedSpan[]
): CandidateScores {
  const startTime = performance.now();

  // Semantic similarity — original vs restored candidate
  const semanticSimilarity = computeSemanticSimilarity(original, candidate.restoredCandidate);

  // NLI check — original vs candidate (contradiction detection)
  const nliScore = computeNLIScore(original, candidate.restoredCandidate);

  // Naturalness / professor penalty
  const naturalnessRaw = computeNaturalnessPenalty(candidate.restoredCandidate);

  // Grammar check
  const grammarResult = checkGrammar(candidate.restoredCandidate);
  const grammarScore = grammarResult.score;

  // Lexical difference
  const lexicalDifference = computeLexicalDiversity(original, candidate.restoredCandidate);

  // Structure difference
  const structureDifference = computeStructureDiversity(original, candidate.restoredCandidate);

  // Banword penalty
  const banwordPenalty = computeBanwordPenalty(candidate.restoredCandidate);

  // Combine into final score
  const { semanticSimilarity: wSem, nliScore: wNli, naturalness: wNat, grammarScore: wGram, lexicalDifference: wLex, structureDifference: wStr, preferenceBonus: wPref } = DEFAULT_SCORE_WEIGHTS;

  // Professor penalty reduces naturalness score
  const naturalness = naturalnessRaw;

  // Preference bonus is 0 for now (no preference profile applied at this stage)
  const preferenceBonus = 0;

  // Banword penalty is subtracted from total (not weighted)
  const penalties = (1 - banwordPenalty) * 0.1;

  const finalScore =
    semanticSimilarity * wSem +
    nliScore * wNli +
    naturalness * wNat +
    grammarScore * wGram +
    lexicalDifference * wLex +
    structureDifference * wStr +
    preferenceBonus * wPref -
    penalties;

  const subScores: Record<string, number> = {
    semanticSimilarity: round(semanticSimilarity),
    nliScore: round(nliScore),
    naturalness: round(naturalness),
    grammarScore: round(grammarScore),
    lexicalDifference: round(lexicalDifference),
    structureDifference: round(structureDifference),
    preferenceBonus: round(preferenceBonus),
    banwordPenalty: round(banwordPenalty),
    professorPenalty: round(1 - naturalness),
  };

  return {
    semanticSimilarity: round(semanticSimilarity),
    nliScore: round(nliScore),
    naturalness: round(naturalness),
    grammarScore: round(grammarScore),
    lexicalDifference: round(lexicalDifference),
    structureDifference: round(structureDifference),
    preferenceBonus: round(preferenceBonus),
    professorPenalty: round(1 - naturalness),
    banwordPenalty: round(1 - banwordPenalty),
    finalScore: round(finalScore),
    subScores,
  };
}

function round(n: number, decimals = 4): number {
  const factor = Math.pow(10, decimals);
  return Math.round(n * factor) / factor;
}

/**
 * Score multiple candidates and return sorted by score (descending).
 */
export function scoreAndRankCandidates(
  candidates: Candidate[],
  original: string,
  spans: ProtectedSpan[]
): { accepted: Candidate[]; rejected: Candidate[] } {
  // Step 1: hard rejection filter
  const accepted = filterHardRejections(candidates, original, spans);
  const rejected = candidates.filter((c) => !c.accepted);

  // Step 2: score accepted candidates
  for (const cand of accepted) {
    cand.scores = scoreCandidate(cand, original, spans);
  }

  // Step 3: sort by final score descending
  accepted.sort((a, b) => (b.scores?.finalScore ?? 0) - (a.scores?.finalScore ?? 0));

  return { accepted, rejected };
}

/**
 * Pick the best candidate from a scored list.
 */
export function pickBestCandidate(accepted: Candidate[]): Candidate | null {
  if (accepted.length === 0) return null;
  return accepted[0];
}
