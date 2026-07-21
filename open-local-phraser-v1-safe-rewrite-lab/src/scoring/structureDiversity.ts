/**
 * Compute structural diversity between original and candidate.
 * Measures sentence-level structure changes separately from word choice.
 *
 * Returns a score between 0 and 1.
 * 0 = same structure, 1 = completely different structure.
 */
export function computeStructureDiversity(original: string, candidate: string): number {
  // Sentence count difference
  const origSentences = countSentenceBreaks(original);
  const candSentences = countSentenceBreaks(candidate);
  const sentCountDiff = Math.abs(origSentences - candSentences) / Math.max(origSentences, 1);

  // Length ratio — candidate shouldn't be dramatically different length
  const origLength = original.split(/\s+/).length;
  const candLength = candidate.split(/\s+/).length;
  const lengthRatio = Math.min(origLength, candLength) / Math.max(origLength, 1);

  // Punctuation structure
  const origPunct = getPunctuationSignature(original);
  const candPunct = getPunctuationSignature(candidate);
  const punctDiff = characterLevelDiff(origPunct, candPunct);

  // Clause boundary difference
  const origClauses = countClauseMarkers(original);
  const candClauses = countClauseMarkers(candidate);
  const clauseDiff = Math.abs(origClauses - candClauses) / Math.max(origClauses, 1);

  // Combined score: we want SOME structure change but not too much
  const rawDiversity = (sentCountDiff * 0.3 + punctDiff * 0.3 + clauseDiff * 0.4);

  // Ideal range: 0.15-0.5
  if (rawDiversity < 0.05) return 0; // too similar
  if (rawDiversity < 0.2) return (rawDiversity - 0.05) / 0.15 * 0.6; // ramp up
  if (rawDiversity < 0.5) return 0.6 + (rawDiversity - 0.2) / 0.3 * 0.4; // ideal
  return Math.max(0, 1.0 - (rawDiversity - 0.5) / 0.5); // penalize too much change
}

function countSentenceBreaks(text: string): number {
  return (text.match(/[.!?]+/g) ?? []).length || 1;
}

function getPunctuationSignature(text: string): string {
  return text.replace(/[a-zA-Z0-9\s]/g, "");
}

function characterLevelDiff(sig1: string, sig2: string): number {
  const maxLen = Math.max(sig1.length, sig2.length);
  if (maxLen === 0) return 0;

  let diff = 0;
  for (let i = 0; i < Math.min(sig1.length, sig2.length); i++) {
    if (sig1[i] !== sig2[i]) diff++;
  }
  diff += Math.abs(sig1.length - sig2.length);
  return diff / (maxLen + 1);
}

function countClauseMarkers(text: string): number {
  const markers = ["because", "since", "although", "unless", "while", "when", "if", "which", "that", "who", "whom", "whose", "where", "but", "however", "therefore", "moreover", "furthermore", "nevertheless", "consequently"];
  const lower = text.toLowerCase();
  return markers.filter((m) => lower.includes(m)).length;
}
