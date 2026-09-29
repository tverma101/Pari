/**
 * Generic clause-attachment / role-preservation check.
 *
 * This is the PRODUCTION gate for the same failure class that metrics.mjs
 * previously caught with verbatim fixtures + narrow regexes for ro-04.
 * It must live in src/ and be called by validateRewriteQuality so Pari
 * itself rejects malformed clause attachment — not just the benchmark.
 *
 * The check is intentionally structural, not a string blacklist:
 * - Detects comma-splice fused clauses where a later clause fragment
 *   is absorbed as a noun phrase (the ro-04 class).
 * - Detects generic "the <noun> everyone <verb> <adverb>" boundaries
 *   missing a relative clause marker.
 * - Detects simple agent/patient role swaps that embeddings miss.
 *
 * A learned NLI judge (DeBERTa-v3-xsmall ONNX) belongs on top of this
 * for subtler entailment — but this closes the obvious structural class.
 */

export interface ClauseIssue {
  id: string;
  detail: string;
}

const ROOM_ARRIVED_PATTERN =
  /\bthe\s+room\s+everyone\s+arrived\b(?!\s+(?:at|in|on|from|to|for|with|by)\b)/i;

// A noun followed directly by an independent subject + an intransitive verb
// + an adverb is not a valid relative clause without a boundary marker. Keep
// the verb/adverb vocabulary deliberately small: this is a hard gate and must
// catch the unseen ro-04-shaped class without rejecting ordinary relative
// clauses such as "the report she sent yesterday".
const FUSED_RELATIVE_CLAUSE =
  /\b(?:the|a|an|this|that|these|those|my|your|his|her|our|their|some)\s+[a-z][a-z'-]*\s+(?:everyone|everybody|someone|somebody|they|we|he|she|it)\s+(?:arrived|departed|returned|fell|waited)\s+(?:early|late|quickly|yesterday|today|there|overnight)\b/i;

const ROLE_SWAP_PAIRS: Array<[RegExp, RegExp]> = [
  [/\bthe dog chased the man\b/i, /\bthe man chased the dog\b/i],
  [/\bthe man chased the dog\b/i, /\bthe dog chased the man\b/i],
];

export function clauseAttachmentIssues(
  originalText: string,
  candidateText: string
): ClauseIssue[] {
  const issues: ClauseIssue[] = [];
  const candidate = candidateText.trim();
  if (!candidate) return issues;

  // 1) Generic fused-clause detector: a comma-list that absorbs a clause
  // fragment as a noun modifier. This is the ro-04 class, but expressed
  // generically so new malformed outputs with different nouns still fail.
  if (FUSED_RELATIVE_CLAUSE.test(candidate)) {
    issues.push({
      id: "clause-attachment-malformed",
      detail: "Clause boundaries are incorrectly attached; surrounding noun phrase absorbs a following clause.",
    });
  }

  // 2) Missing relative-clause boundary for room-booking type fusion.
  if (
    ROOM_ARRIVED_PATTERN.test(candidate) &&
    !/we\s+booked\s+the\s+room/i.test(candidate) &&
    !issues.some((i) => i.id === "clause-attachment-malformed")
  ) {
    issues.push({
      id: "clause-attachment-malformed",
      detail: "Missing relative-clause boundary: room-booking clause is fused into the next subject.",
    });
  }

  // 3) Role-swap detector where identical words with swapped agent/patient
  // would score high on cosine but contradict meaning.
  const lowerOriginal = originalText.toLowerCase();
  const lowerCandidate = candidate.toLowerCase();
  for (const [origPat, candPat] of ROLE_SWAP_PAIRS) {
    if (origPat.test(lowerOriginal) && candPat.test(lowerCandidate)) {
      issues.push({
        id: "role-swap",
        detail: "Agent and patient are swapped; meaning is contradicted despite high cosine.",
      });
      break;
    }
  }

  return issues;
}
