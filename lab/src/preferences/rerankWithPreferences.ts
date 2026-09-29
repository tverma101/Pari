import type { Candidate, CandidateScores, PreferenceProfile } from "../core/types.js";
import { getDefaultProfile, getProfile } from "./preferenceProfile.js";
import { countProfessorWords, getPreferredReplacement } from "../scoring/naturalnessPenalty.js";

/**
 * Rerank candidates using a user's preference profile.
 * Adjusts the final score with preference-aware bonuses and penalties.
 */
export function rerankWithPreferences(
  candidates: Candidate[],
  profileId?: string
): Candidate[] {
  if (candidates.length === 0) return candidates;

  const profile = profileId ? getProfile(profileId) : getDefaultProfile();
  if (!profile) return candidates;

  return candidates
    .map((candidate) => {
      if (!candidate.scores) return candidate;

      const adjusted = applyPreferences(candidate, profile);
      return { ...candidate, scores: adjusted };
    })
    .sort((a, b) => (b.scores?.finalScore ?? 0) - (a.scores?.finalScore ?? 0));
}

/**
 * Apply preference adjustments to candidate scores.
 */
function applyPreferences(
  candidate: Candidate,
  profile: PreferenceProfile
): CandidateScores {
  const scores = { ...candidate.scores! };
  const text = candidate.restoredCandidate.toLowerCase();

  // Hard banned words — severe penalty
  const hardBannedHit = profile.hardBannedWords.filter((w) => text.includes(w.toLowerCase()));
  if (hardBannedHit.length > 0) {
    scores.banwordPenalty -= hardBannedHit.length * 0.3;
  }

  // Soft disliked words
  const softDislikedHit = profile.softDislikedWords.filter((w) => text.includes(w.toLowerCase()));
  if (softDislikedHit.length > 0) {
    scores.banwordPenalty -= softDislikedHit.length * 0.08;
  }

  // Preferred replacement bonus
  let preferredUsed = 0;
  for (const [original, replacements] of Object.entries(profile.preferredReplacements)) {
    if (!text.includes(original.toLowerCase())) {
      // Original word was NOT used — check if a replacement was used
      for (const replacement of replacements) {
        if (text.includes(replacement.toLowerCase())) {
          preferredUsed++;
          break;
        }
      }
    }
  }
  if (preferredUsed > 0) {
    scores.preferenceBonus += preferredUsed * 0.05;
  }

  // Formality penalty — additional professor word penalty
  const professorInfo = countProfessorWords(candidate.restoredCandidate);
  const professorScore = professorInfo.count / Math.max(text.split(/\s+/).length, 1);
  if (professorScore > 0.05) {
    scores.professorPenalty += professorScore * profile.professorPenaltyWeight;
  }

  // Sentence length adjustment
  const wordCount = text.split(/\s+/).length;
  const origWordCount = candidate.originalSentence.split(/\s+/).length;
  if (profile.sentenceLengthTarget === "shorter" && wordCount > origWordCount * 1.2) {
    scores.finalScore -= 0.05;
  } else if (profile.sentenceLengthTarget === "longer" && wordCount < origWordCount * 0.8) {
    scores.finalScore -= 0.03;
  }

  // Recalculate final score
  const { semanticSimilarity: wSem, nliScore: wNli, naturalness: wNat, grammarScore: wGram, lexicalDifference: wLex, structureDifference: wStr, preferenceBonus: wPref } = { semanticSimilarity: 0.30, nliScore: 0.18, naturalness: 0.16, grammarScore: 0.12, lexicalDifference: 0.10, structureDifference: 0.08, preferenceBonus: 0.06 };

  scores.finalScore =
    scores.semanticSimilarity * wSem +
    scores.nliScore * wNli +
    scores.naturalness * wNat +
    scores.grammarScore * wGram +
    scores.lexicalDifference * wLex +
    scores.structureDifference * wStr +
    scores.preferenceBonus * wPref -
    Math.max(0, scores.banwordPenalty) * 0.1 -
    scores.professorPenalty * 0.1;

  // Clamp to [0, 1]
  scores.finalScore = Math.max(0, Math.min(1, scores.finalScore));

  return scores;
}

export type { PreferenceProfile };
