import * as bridge from "../generation/pythonBridge.js";

/**
 * NLI (Natural Language Inference) check for factual drift.
 * Determines whether the candidate contradicts, entails, or is neutral
 * with respect to the original text.
 */

export interface NLIResult {
  /** Score: 0-1 where 1 = no contradiction */
  score: number;
  contradiction: number;
  entailment: number;
  neutral: number;
  label: string;
  details: string;
}

/**
 * Check for contradiction between original and candidate.
 * Uses Python NLI model if available.
 */
export function checkNLIContradiction(
  original: string,
  candidate: string,
  model = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
): NLIResult {
  try {
    const result = bridge.nliCheck(original, candidate, model);
    if (result.success) {
      const data = result.data as unknown as bridge.NLIOutput;
      const scores = data.scores;

      // Normalize: higher contradiction = lower score
      const contradictionScore = (scores.contradiction ?? 0) / 100;
      const entailmentScore = (scores.entailment ?? 0) / 100;
      const neutralScore = (scores.neutral ?? 0) / 100;

      // Score: 0 if contradiction is > 50%, 1 if entailment > 50%
      let score: number;
      if (contradictionScore > 0.5) {
        score = 1.0 - contradictionScore;
      } else if (entailmentScore > 0.5) {
        score = entailmentScore;
      } else {
        // Neutral zone — score based on entailment/neutral ratio
        score = 0.5 + entailmentScore * 0.5;
      }

      return {
        score: Math.max(0, Math.min(1, score)),
        contradiction: contradictionScore,
        entailment: entailmentScore,
        neutral: neutralScore,
        label: scores.label ?? "neutral",
        details: `ent=${(entailmentScore * 100).toFixed(1)}% con=${(contradictionScore * 100).toFixed(1)}% neu=${(neutralScore * 100).toFixed(1)}%`,
      };
    }
  } catch {
    // NLI unavailable
  }

  // Fallback: heuristic contradiction detection
  return heuristicNLICheck(original, candidate);
}

/**
 * Heuristic NLI fallback when no NLI model is available.
 * Checks for negation flips, number changes, and antonym replacement.
 */
function heuristicNLICheck(original: string, candidate: string): NLIResult {
  const contradictions: string[] = [];

  // Check negation flips
  const origHasNot = /\b(not|never|no|n't)\b/i.test(original);
  const candHasNot = /\b(not|never|no|n't)\b/i.test(candidate);

  if (origHasNot && !candHasNot) {
    contradictions.push("Negation removed");
  }
  if (!origHasNot && candHasNot) {
    contradictions.push("Negation added");
  }

  // Check common antonym pairs
  const antonymPairs = [
    ["good", "bad"], ["big", "small"], ["always", "never"],
    ["more", "less"], ["better", "worse"], ["increase", "decrease"],
    ["positive", "negative"], ["help", "harm"], ["benefit", "drawback"],
  ];

  for (const [a, b] of antonymPairs) {
    const origWord = new RegExp(`\\b${a}\\b`, "i").test(original) ? a :
                     new RegExp(`\\b${b}\\b`, "i").test(original) ? b : null;
    const candWord = new RegExp(`\\b${a}\\b`, "i").test(candidate) ? a :
                     new RegExp(`\\b${b}\\b`, "i").test(candidate) ? b : null;

    if (origWord && candWord && origWord !== candWord) {
      contradictions.push(`Antonym flip: "${origWord}" -> "${candWord}"`);
    }
  }

  if (contradictions.length > 0) {
    return {
      score: Math.max(0, 1.0 - contradictions.length * 0.33),
      contradiction: Math.min(1, contradictions.length * 0.33),
      entailment: 0,
      neutral: 0,
      label: "contradiction",
      details: `Heuristic contradiction: ${contradictions.join("; ")}`,
    };
  }

  return {
    score: 0.85, // Slightly less than 1.0 since we can't verify
    contradiction: 0,
    entailment: 0.5,
    neutral: 0.5,
    label: "likely_neutral",
    details: "No heuristic contradiction detected (model unavailable)",
  };
}

/**
 * Scores are more lenient: only flag clear contradictions.
 * NLI score is used at 0.18 weight in final formula.
 */
export function computeNLIScore(original: string, candidate: string): number {
  const result = checkNLIContradiction(original, candidate);
  return result.score;
}
